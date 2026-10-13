"""
Laboratorio de investigación v2: busca estrategias nuevas sin parar y las valida con rigor.

  py -3.14 research.py run        # busca sin parar (Ctrl+C para detener; retoma donde quedó)
  py -3.14 research.py run 30     # igual, pero se detiene a los 30 minutos
  py -3.14 research.py status     # muestra las mejores hasta ahora (NO toca los datos finales)
  py -3.14 research.py report     # examen final, UNA sola vez (luego se bloquea)
  py -3.14 research.py report force   # repetir el examen (gasta los datos finales: no lo hagas)

Cómo funciona:
  * Genera estrategias nuevas combinando disparadores (RSI, cruces de EMA, rupturas, Bollinger,
    MACD, estocástico, momentum, distancia a la media), filtros (tendencia, volumen, volatilidad,
    ADX) y salidas (stop + objetivo, o trailing stop). Además muta las mejores.
  * Cada una se prueba en 4 monedas y 4 tramos de tiempo, con comisión y deslizamiento.
  * El último 20% de los datos queda RESERVADO: solo lo usa `report`, y solo una vez.
  * Resultados en results.jsonl. Debe estar junto a bot.py, no necesita claves.
"""
import copy
import json
import os
import random
import sys
import time

import ccxt
import numpy as np
import pandas as pd

COINS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]
YEARS = 4
FEE = 0.001            # comisión por lado
SLIP = 0.0005          # deslizamiento por lado
RISK = 0.02            # arriesga 2% del capital por operación
MAX_BARS = 300         # salida por tiempo si no toca stop ni objetivo
HOLDOUT = 0.2          # último 20% reservado
N_FOLDS = 4
MIN_TRADES = 40        # mínimo de operaciones entre todos los tramos
MIN_POS_RATIO = 0.6    # al menos 60% de los tramos deben terminar en positivo
RESULTS = "results.jsonl"
HOLDOUT_LOG = "holdout_used.json"
DATA_DIR = "data"
EMAS = [10, 20, 30, 50, 100, 200]
DONS = [20, 40, 60, 100]
BBK = [2.0, 2.5]
ROCS = [10, 30, 60]
TRAILS = [None, None, 2.0, 3.0, 4.0]


# ---------------- DATOS ----------------
def load_coin(ex, coin):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, coin.replace("/", "_") + "_1h.csv")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
        return pd.read_csv(path)
    print(f"Descargando {coin} (puede tardar un minuto)...")
    since = ex.milliseconds() - YEARS * 365 * 24 * 3600 * 1000
    out = []
    while True:
        b = ex.fetch_ohlcv(coin, "1h", since=since, limit=1000)
        if not b:
            break
        out += b
        since = b[-1][0] + 1
        if len(b) < 1000:
            break
    df = pd.DataFrame(out, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts").reset_index(drop=True)
    df.to_csv(path, index=False)
    return df


def resample(df, rule):
    d = df.copy()
    d.index = pd.to_datetime(d["ts"], unit="ms")
    out = d.resample(rule).agg({"ts": "first", "open": "first", "high": "max",
                                "low": "min", "close": "last", "volume": "sum"})
    return out.dropna().reset_index(drop=True)


def prep(df):
    d = df.copy()
    c = d.close
    for n in EMAS:
        d[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    d["rsi"] = 100 - 100 / (1 + gain / loss)
    tr = pd.concat([d.high - d.low, (d.high - c.shift()).abs(),
                    (d.low - c.shift()).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    d["vol_ma"] = d.volume.rolling(20).mean()
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    for k in BBK:
        d[f"bb{k}"] = mid - k * sd
    for n in DONS:
        d[f"don{n}"] = d.high.rolling(n).max().shift(1)
    d["macd"] = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    d["macd_sig"] = d.macd.ewm(span=9, adjust=False).mean()
    d["atrp"] = d.atr / c
    d["atrp_med"] = d.atrp.rolling(200).median()
    # --- indicadores nuevos (v2) ---
    for n in ROCS:
        d[f"roc{n}"] = c.pct_change(n)
    lo, hi = d.low.rolling(14).min(), d.high.rolling(14).max()
    d["stoch"] = 100 * (c - lo) / (hi - lo).replace(0, np.nan)
    up, dn = d.high.diff(), -d.low.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=d.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=d.index)
    pdi = 100 * pdm.ewm(alpha=1 / 14, adjust=False).mean() / d.atr
    mdi = 100 * mdm.ewm(alpha=1 / 14, adjust=False).mean() / d.atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    d["adx"] = dx.ewm(alpha=1 / 14, adjust=False).mean()
    d["zema"] = (c / d.ema50 - 1) / d.atrp          # distancia a la EMA50 en "unidades de volatilidad"
    return d.dropna().reset_index(drop=True)


def load_all():
    ex = ccxt.binance({"enableRateLimit": True})
    data = {}
    for coin in COINS:
        raw = load_coin(ex, coin)
        for tf, df in (("1h", raw), ("4h", resample(raw, "4h"))):
            D = prep(df)
            n = len(D)
            hold = int(n * (1 - HOLDOUT))
            data[(coin, tf)] = {
                "D": D, "n": n, "hold": hold,
                "o": D.open.to_numpy(), "h": D.high.to_numpy(), "l": D.low.to_numpy(),
                "c": D.close.to_numpy(), "atr": D.atr.to_numpy(),
                "edges": np.linspace(0, hold, N_FOLDS + 1).astype(int),
            }
    return data


# ---------------- SEÑALES ----------------
def cross_up(x, lvl):
    return ((x.shift(1) < lvl) & (x >= lvl)).to_numpy()


def trig(D, s):
    f = s["fam"]
    if f == "rsi_rebound":
        x = (D.rsi.shift(1) < s["lvl"]) & (D.rsi >= s["lvl"])
    elif f == "ema_cross":
        a, b = D[f"ema{s['fast']}"], D[f"ema{s['slow']}"]
        x = (a.shift(1) <= b.shift(1)) & (a > b)
    elif f == "donchian":
        k = f"don{s['n']}"
        x = (D.close > D[k]) & (D.close.shift(1) <= D[k].shift(1))
    elif f == "bb_rebound":
        lo = D[f"bb{s['k']}"]
        x = (D.close.shift(1) < lo.shift(1)) & (D.close >= lo)
    elif f == "stoch_up":
        return cross_up(D.stoch, s["lvl"])
    elif f == "roc_up":
        return cross_up(D[f"roc{s['n']}"], s["lvl"])
    elif f == "zema_up":
        return cross_up(D.zema, s["lvl"])
    else:  # macd_cross
        x = (D.macd.shift(1) <= D.macd_sig.shift(1)) & (D.macd > D.macd_sig)
    return x.to_numpy()


def filt(D, s):
    f = s["fam"]
    if f == "above_ema":
        x = D.close > D[f"ema{s['n']}"]
    elif f == "ema_stack":
        x = D.ema50 > D.ema200
    elif f == "rsi_above":
        x = D.rsi > s["lvl"]
    elif f == "vol_above":
        x = D.volume > D.vol_ma
    elif f == "calm":
        x = D.atrp < D.atrp_med
    elif f == "adx_above":
        x = D.adx > s["lvl"]
    elif f == "roc_pos":
        x = D.roc30 > 0
    else:  # volatile
        x = D.atrp >= D.atrp_med
    return x.to_numpy()


def signal(D, cand):
    x = trig(D, cand["trig"])
    for f in cand["filters"]:
        x = x & filt(D, f)
    return x


# ---------------- BACKTEST RÁPIDO ----------------
def trail_exit(h, l, c, o, atr_i, entry, r, i, end, N, k):
    """Stop que sube siguiendo al máximo. Usa solo información de velas anteriores."""
    stop, hh = entry - r, entry
    for j in range(i + 1, end):
        if o[j] <= stop:
            return j, o[j]                      # hueco a la baja: sale a la apertura
        if l[j] <= stop:
            return j, stop
        hh = max(hh, h[j])
        stop = max(stop, hh - k * atr_i)
    if i + 1 + MAX_BARS > N:
        return None                             # sigue abierta al final: se ignora
    return end - 1, c[end - 1]


def run(P, sig, a, b, cand, capital=1000.0):
    o, h, l, c, atr = (P[k][a:b] for k in ("o", "h", "l", "c", "atr"))
    sig = sig[a:b]
    N = len(o)
    idx = np.flatnonzero(sig)
    eq, peak, mdd, n, k = capital, capital, 0.0, 0, 0
    trail = cand.get("trail")
    while k < len(idx):
        i = idx[k]
        if i + 1 >= N:
            break
        entry = o[i + 1] * (1 + SLIP)
        r = cand["atr"] * atr[i]
        if not r > 0:
            k += 1
            continue
        end = min(N, i + 1 + MAX_BARS)
        if trail:
            res = trail_exit(h, l, c, o, atr[i], entry, r, i, end, N, trail)
            if res is None:
                break
            j, exit_p = res
        else:
            stop, tp = entry - r, entry + cand["rr"] * r
            ls, hs = l[i + 1:end] <= stop, h[i + 1:end] >= tp
            js = int(ls.argmax()) if ls.any() else -1
            jt = int(hs.argmax()) if hs.any() else -1
            if js == -1 and jt == -1:
                if i + 1 + MAX_BARS > N:
                    break                       # operación aún abierta al final: se ignora
                j, exit_p = end - 1, c[end - 1]
            elif jt == -1 or (js != -1 and js <= jt):
                j, exit_p = i + 1 + js, stop    # si toca ambos, asumimos el peor caso
            else:
                j, exit_p = i + 1 + jt, tp
        exit_p *= (1 - SLIP)
        amt = min(eq * RISK / r, eq * 0.95 / entry)
        eq += amt * (exit_p - entry) - FEE * amt * (exit_p + entry)
        n += 1
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
        k = int(np.searchsorted(idx, j, side="right"))
    return eq / capital - 1, mdd, n


def evaluate(cand, data):
    rets, dds, trades = [], [], 0
    for coin in COINS:
        P = data[(coin, cand["tf"])]
        sig = signal(P["D"], cand)
        e = P["edges"]
        for a, b in zip(e[:-1], e[1:]):
            r = run(P, sig, a, b, cand)
            rets.append(r[0])
            dds.append(r[1])
            trades += r[2]
    rets = np.array(rets)
    pos = float((rets > 0).mean())
    raw = float(rets.mean() - 0.5 * rets.std())     # premia ganar y ser consistente
    ok = trades >= MIN_TRADES and pos >= MIN_POS_RATIO
    return {"cand": cand, "score": raw if ok else -999.0, "raw": raw,
            "mean": float(rets.mean()), "pos": pos, "trades": int(trades),
            "dd": float(np.mean(dds))}


# ---------------- GENERADOR DE ESTRATEGIAS ----------------
def rand_trig(fam=None):
    fam = fam or random.choice(["rsi_rebound", "ema_cross", "donchian", "bb_rebound",
                                "macd_cross", "stoch_up", "roc_up", "zema_up"])
    s = {"fam": fam}
    if fam == "rsi_rebound":
        s["lvl"] = random.choice([25, 30, 35, 40, 45, 50, 55])
    elif fam == "ema_cross":
        s["fast"] = random.choice([10, 20, 30, 50])
        s["slow"] = random.choice([x for x in [50, 100, 200] if x > s["fast"]])
    elif fam == "donchian":
        s["n"] = random.choice(DONS)
    elif fam == "bb_rebound":
        s["k"] = random.choice(BBK)
    elif fam == "stoch_up":
        s["lvl"] = random.choice([10, 20, 30, 50])
    elif fam == "roc_up":
        s["n"] = random.choice(ROCS)
        s["lvl"] = random.choice([0.0, 0.02, 0.05])
    elif fam == "zema_up":
        s["lvl"] = random.choice([-3.0, -2.0, -1.0, 0.0])
    return s


def rand_filter():
    fam = random.choice(["above_ema", "ema_stack", "rsi_above", "vol_above", "calm",
                         "volatile", "adx_above", "roc_pos"])
    s = {"fam": fam}
    if fam == "above_ema":
        s["n"] = random.choice([50, 100, 200])
    elif fam == "rsi_above":
        s["lvl"] = random.choice([40, 50, 55])
    elif fam == "adx_above":
        s["lvl"] = random.choice([20, 25])
    return s


def random_candidate():
    return {"tf": random.choice(["1h", "4h"]), "trig": rand_trig(),
            "filters": [rand_filter() for _ in range(random.choice([0, 1, 1, 2]))],
            "atr": random.choice([1.5, 2.0, 2.5, 3.0, 4.0]),
            "rr": random.choice([1.5, 2.0, 3.0, 4.0]),
            "trail": random.choice(TRAILS)}


def mutate(c):
    c = copy.deepcopy(c)
    r = random.random()
    if r < 0.15:
        c["atr"] = random.choice([1.5, 2.0, 2.5, 3.0, 4.0])
    elif r < 0.30:
        c["rr"] = random.choice([1.5, 2.0, 3.0, 4.0])
    elif r < 0.40:
        c["trail"] = random.choice(TRAILS)
    elif r < 0.52:
        c["trig"] = rand_trig(c["trig"]["fam"])          # ajusta parámetros
    elif r < 0.64:
        c["trig"] = rand_trig()                          # método nuevo
    elif r < 0.80 and len(c["filters"]) < 3:
        c["filters"].append(rand_filter())
    elif c["filters"]:
        c["filters"].pop(random.randrange(len(c["filters"])))
    else:
        c["tf"] = "4h" if c["tf"] == "1h" else "1h"
    return c


NAMES = {"rsi_rebound": "RSI cruza hacia arriba el nivel {lvl}",
         "ema_cross": "EMA{fast} cruza sobre EMA{slow}",
         "donchian": "ruptura del máximo de {n} velas",
         "bb_rebound": "rebote desde la banda de Bollinger inferior ({k} desv.)",
         "macd_cross": "MACD cruza hacia arriba",
         "stoch_up": "estocástico cruza hacia arriba el nivel {lvl}",
         "roc_up": "momentum de {n} velas cruza {lvl}",
         "zema_up": "distancia a la EMA50 cruza {lvl} (en unidades de volatilidad)"}
FNAMES = {"above_ema": "precio sobre EMA{n}", "ema_stack": "EMA50 sobre EMA200",
          "rsi_above": "RSI mayor a {lvl}", "vol_above": "volumen sobre su promedio",
          "calm": "volatilidad baja", "volatile": "volatilidad alta",
          "adx_above": "ADX mayor a {lvl} (hay tendencia)", "roc_pos": "momentum de 30 velas positivo"}


def describe(c):
    t = NAMES[c["trig"]["fam"]].format(**c["trig"])
    f = " + ".join(FNAMES[x["fam"]].format(**x) for x in c["filters"]) or "sin filtros"
    exit_ = (f"stop inicial {c['atr']}xATR y trailing {c['trail']}xATR" if c.get("trail")
             else f"stop {c['atr']}xATR, objetivo {c['rr']}x")
    return f"velas {c['tf']} | compra: {t} | filtros: {f} | {exit_}"


# ---------------- COMANDOS ----------------
def load_results():
    out = []
    if os.path.exists(RESULTS):
        with open(RESULTS, encoding="utf-8") as f:
            out = [json.loads(line) for line in f if line.strip()]
    return out


def normalize(c):
    # ordena y quita filtros repetidos (antes "volumen + volumen" contaba como estrategia distinta)
    uniq = {json.dumps(f, sort_keys=True): f for f in c["filters"]}
    c["filters"] = [uniq[k] for k in sorted(uniq)]
    if c.get("trail"):
        c["rr"] = 0          # con trailing no hay objetivo: evita duplicados equivalentes
    else:
        c["trail"] = None
    return c


def search(minutes=None):
    data = load_all()
    results = load_results()
    seen = {json.dumps(normalize(copy.deepcopy(r["cand"])), sort_keys=True) for r in results}
    best = max([r["score"] for r in results], default=-999.0)
    t0, n = time.time(), 0
    print(f"Buscando... ({len(results)} variantes ya probadas). Ctrl+C para detener.")
    try:
        while minutes is None or time.time() - t0 < minutes * 60:
            good = sorted((r for r in results if r["score"] > -900),
                          key=lambda r: -r["score"])[:20]
            if len(good) >= 10 and random.random() < 0.6:
                cand = mutate(random.choice(good)["cand"])
            else:
                cand = random_candidate()
            cand = normalize(cand)
            key = json.dumps(cand, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            res = evaluate(cand, data)
            results.append(res)
            with open(RESULTS, "a", encoding="utf-8") as f:
                f.write(json.dumps(res) + "\n")
            n += 1
            if res["score"] > best:
                best = res["score"]
                print(f"\nNueva mejor (puntaje {best:+.3f}, positivos {res['pos']:.0%}, "
                      f"{res['trades']} ops):\n  {describe(cand)}")
            if n % 100 == 0:
                print(f"  ... {n} nuevas en esta sesión, {len(results)} en total")
    except KeyboardInterrupt:
        pass
    print(f"\nListo. {len(results)} variantes probadas en total. "
          f"Mira el avance con:  py -3.14 research.py status")


def status():
    results = load_results()
    good = sorted((r for r in results if r["score"] > -900), key=lambda r: -r["score"])
    print(f"Variantes probadas: {len(results)} | pasaron los filtros de selección: {len(good)}")
    for r in good[:5]:
        print(f"  puntaje {r['raw']:+.3f} | {r['pos']:.0%} tramos positivos | "
              f"{r['trades']} ops | {describe(r['cand'])}")
    print("(Solo datos de selección. El examen final es 'report'.)")


def report(force=False):
    if os.path.exists(HOLDOUT_LOG) and not force:
        with open(HOLDOUT_LOG, encoding="utf-8") as f:
            info = json.load(f)
        print(f"Los datos finales ya se usaron el {info['fecha']} (con {info['variantes']} variantes).\n"
              "Repetir el examen los contamina: acabarías eligiendo lo que casualmente aprueba.\n"
              "Sigue con 'run' y 'status'. Si de verdad quieres repetirlo: report force")
        return
    data = load_all()
    results = load_results()
    good = sorted((r for r in results if r["score"] > -900), key=lambda r: -r["score"])
    print(f"Variantes probadas: {len(results)} | pasaron los filtros: {len(good)}")
    if not good:
        print("Todavía ninguna pasa. Deja correr 'run' más tiempo.")
        return
    print("Evaluando las 5 más distintas entre las mejores, en datos FINALES "
          "(nunca usados para elegir)...\n")
    distintas, vistos = [], set()
    for r in good:
        marca = json.dumps([r["cand"]["tf"], r["cand"]["trig"]], sort_keys=True)
        if marca not in vistos:
            vistos.add(marca)
            distintas.append(r)
        if len(distintas) == 5:
            break
    for r in distintas:
        c = r["cand"]
        rows, wins, rets = [], 0, []
        for coin in COINS:
            P = data[(coin, c["tf"])]
            ret = run(P, signal(P["D"], c), P["hold"], P["n"], c)[0]
            hold = P["c"][P["n"] - 1] / P["c"][P["hold"]] - 1
            wins += ret > 0
            rets.append(ret)
            rows.append(f"{coin.split('/')[0]} {ret:+.1%} (comprar y mantener {hold:+.1%})")
        mean = float(np.mean(rets))
        verdict = "PASA" if wins >= 3 and mean > 0 else "NO PASA"
        print(f"[{verdict}] {describe(c)}")
        print(f"   en los tramos de selección: puntaje {r['raw']:+.3f}, "
              f"{r['pos']:.0%} de tramos positivos, {r['trades']} operaciones")
        print("   en datos finales: " + " | ".join(rows) + "\n")
    with open(HOLDOUT_LOG, "w", encoding="utf-8") as f:
        json.dump({"fecha": time.strftime("%Y-%m-%d %H:%M"), "variantes": len(results)}, f)
    print(f"OJO: con {len(results)} variantes probadas, algunas pasan solo por azar "
          "(en pruebas con datos aleatorios, ~3% de las que pasan la selección aprueban igual). "
          "Una que PASA no es una promesa: solo merece ir al Testnet.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "report":
        report(len(sys.argv) > 2 and sys.argv[2] == "force")
    elif cmd == "status":
        status()
    else:
        search(float(sys.argv[2]) if len(sys.argv) > 2 else None)
