"""
Laboratorio de investigación v3: inventa y prueba estrategias sin parar, y las valida con rigor.

Modo manual (en tu PC):
  py -3.14 research.py run [min]   # busca (retoma donde quedó). Ctrl+C para detener
  py -3.14 research.py status      # mejores hasta ahora (NO toca los datos finales)
  py -3.14 research.py report      # examen final antiguo, UNA sola vez

Modo autónomo (pensado para correr solo en la nube, ver research.yml):
  py -3.14 research.py auto [min]  # busca durante `min` minutos, elige campeón y actualiza STATUS.md

Cómo funciona el modo autónomo:
  * Inventa estrategias: disparadores clásicos (RSI, EMA, rupturas, Bollinger, MACD, estocástico,
    momentum...) y también "expr": combinaciones libres de 1-3 condiciones sobre 11 indicadores
    con umbrales por percentil. Las mejores se mutan y se vuelven a probar, para siempre.
  * Explora riesgo alto (hasta 10% del capital por operación). Solo se descartan las que en
    promedio pierden más del 60% desde su máximo: eso no es una estrategia, es ruina.
  * Todo es SIMULACIÓN. Nada de esto toca dinero: opera solo bot.py, en Testnet.
  * Selección con datos hasta forward.json; los datos POSTERIORES (que crecen cada día) nunca se
    usan para elegir. Sirven para ver, con datos realmente nuevos, si el campeón funciona.
"""
import copy
import json
import os
import random
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

COINS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]
YEARS = 4
FEE = 0.001            # comisión por lado
SLIP = 0.0005          # deslizamiento por lado
RISK = 0.02            # riesgo por operación por defecto
RISKS = [0.01, 0.02, 0.05, 0.10]
MAX_BARS = 300         # salida por tiempo si no toca stop ni objetivo
HOLDOUT = 0.2          # modo manual: último 20% reservado
N_FOLDS = 4
MIN_TRADES = 40        # mínimo de operaciones entre todos los tramos
MIN_POS_RATIO = 0.6    # al menos 60% de los tramos deben terminar en positivo
MAX_DD = 0.6           # caída máxima media tolerada
RESULTS = "results.jsonl"
HOLDOUT_LOG = "holdout_used.json"
AUTO_RESULTS = "auto_results.jsonl"
AUTO_STATS = "auto_stats.json"
FORWARD_FILE = "forward.json"
CHAMPION_FILE = "champion.json"
STATUS_FILE = "STATUS.md"
KEEP_TOP = 2000
DATA_DIR = "data"
EMAS = [10, 20, 30, 50, 100, 200]
DONS = [20, 40, 60, 100]
BBK = [2.0, 2.5]
ROCS = [10, 30, 60]
TRAILS = [None, None, 2.0, 3.0, 4.0]
FEATS = ["rsi", "stoch", "adx", "zema", "roc10", "roc30", "roc60",
         "atr_ratio", "vol_ratio", "bbz", "gap"]
QGRID = [0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9]
BASES = ["https://data-api.binance.vision", "https://api.binance.com"]
EXPLORE_RISK = False   # el modo auto lo activa


# ---------------- DATOS (sin ccxt: solo la librería estándar) ----------------
def now_ms():
    return int(time.time() * 1000)


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def klines(coin, since_ms):
    sym = coin.replace("/", "")
    out, err = [], None
    while True:
        batch = None
        for base in BASES:
            try:
                batch = http_json(f"{base}/api/v3/klines?symbol={sym}&interval=1h"
                                  f"&startTime={since_ms}&limit=1000")
                break
            except Exception as e:      # noqa: BLE001 - probamos el siguiente servidor
                err = e
        if batch is None:
            raise RuntimeError(f"No pude descargar {coin}: {err}")
        if not batch:
            break
        out += [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
                for k in batch]
        since_ms = int(batch[-1][0]) + 3600_000
        if len(batch) < 1000:
            break
    return out


def load_coin(coin, since_ms=None, ttl=86400):
    os.makedirs(DATA_DIR, exist_ok=True)
    tag = f"_{since_ms}" if since_ms else ""
    path = os.path.join(DATA_DIR, coin.replace("/", "_") + f"_1h{tag}.csv")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        return pd.read_csv(path)
    print(f"Descargando {coin} (puede tardar un minuto)...")
    since = since_ms or now_ms() - YEARS * 365 * 24 * 3600 * 1000
    df = pd.DataFrame(klines(coin, since), columns=["ts", "open", "high", "low", "close", "volume"])
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
    d["zema"] = (c / d.ema50 - 1) / d.atrp
    # --- indicadores extra (v3) ---
    d["atr_ratio"] = d.atrp / d.atrp_med
    d["vol_ratio"] = d.volume / d.vol_ma
    d["bbz"] = (c - mid) / sd.replace(0, np.nan)
    d["gap"] = d.ema20 / d.ema100 - 1
    return d.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)


SPAN = {"1h": 0, "4h": 3 * 3600_000}     # una vela de 4h empieza 3 h antes de cerrar


def load_all(fwd=None):
    data = {}
    for coin in COINS:
        if fwd:
            raw = load_coin(coin, fwd["data_start_ts"], ttl=3600)
            raw = raw.iloc[:-1].reset_index(drop=True)    # descarta la vela aún abierta
        else:
            raw = load_coin(coin)
        for tf, df in (("1h", raw), ("4h", resample(raw, "4h"))):
            D = prep(df)
            n = len(D)
            if fwd:
                hold = int((D.ts <= fwd["start_ts"] - SPAN[tf]).sum())
            else:
                hold = int(n * (1 - HOLDOUT))
            D.attrs["hold"] = hold
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


def thr(D, f, q):
    """Umbral = percentil q del indicador f, calculado SOLO con los datos de selección."""
    cache = D.attrs.setdefault("_q", {})
    if f not in cache:
        hold = D.attrs.get("hold", int(len(D) * (1 - HOLDOUT)))
        cache[f] = np.sort(D[f].to_numpy()[:hold])
    return float(np.quantile(cache[f], q))


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
    elif f == "expr":
        now = np.ones(len(D), dtype=bool)
        for c in s["conds"]:
            v, t = D[c["f"]].to_numpy(), thr(D, c["f"], c["q"])
            now &= (v > t) if c["op"] == ">" else (v < t)
        return now & ~np.r_[False, now[:-1]]     # solo el instante en que se cumplen todas
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
    rk = cand.get("risk", RISK)
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
        amt = min(eq * rk / r, eq * 0.95 / entry)
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
    dd = float(np.mean(dds))
    ok = trades >= MIN_TRADES and pos >= MIN_POS_RATIO and dd <= MAX_DD
    return {"cand": cand, "score": raw if ok else -999.0, "raw": raw,
            "mean": float(rets.mean()), "pos": pos, "trades": int(trades), "dd": dd}


# ---------------- GENERADOR DE ESTRATEGIAS ----------------
def rand_cond():
    return {"f": random.choice(FEATS), "op": random.choice([">", "<"]),
            "q": random.choice(QGRID)}


def mutate_expr(s):
    conds = s["conds"]
    r = random.random()
    if r < 0.35:
        c = random.choice(conds)
        i = QGRID.index(c["q"])
        c["q"] = QGRID[min(max(i + random.choice([-1, 1]), 0), len(QGRID) - 1)]
    elif r < 0.5:
        c = random.choice(conds)
        c["op"] = "<" if c["op"] == ">" else ">"
    elif r < 0.7:
        random.choice(conds)["f"] = random.choice(FEATS)
    elif r < 0.85 and len(conds) < 3:
        conds.append(rand_cond())
    elif len(conds) > 1:
        conds.pop(random.randrange(len(conds)))
    else:
        conds[0] = rand_cond()


def rand_trig(fam=None):
    fam = fam or random.choice(["rsi_rebound", "ema_cross", "donchian", "bb_rebound",
                                "macd_cross", "stoch_up", "roc_up", "zema_up",
                                "expr", "expr", "expr"])
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
    elif fam == "expr":
        s["conds"] = [rand_cond() for _ in range(random.choice([1, 2, 2, 3]))]
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
            "trail": random.choice(TRAILS),
            "risk": random.choice(RISKS if EXPLORE_RISK else [RISK])}


def mutate(c):
    c = copy.deepcopy(c)
    r = random.random()
    if r < 0.12:
        c["atr"] = random.choice([1.5, 2.0, 2.5, 3.0, 4.0])
    elif r < 0.24:
        c["rr"] = random.choice([1.5, 2.0, 3.0, 4.0])
    elif r < 0.32:
        c["trail"] = random.choice(TRAILS)
    elif r < 0.38 and EXPLORE_RISK:
        c["risk"] = random.choice(RISKS)
    elif r < 0.55:
        if c["trig"]["fam"] == "expr":
            mutate_expr(c["trig"])
        else:
            c["trig"] = rand_trig(c["trig"]["fam"])      # ajusta parámetros
    elif r < 0.66:
        c["trig"] = rand_trig()                          # método nuevo
    elif r < 0.82 and len(c["filters"]) < 3:
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
FEAT_NAMES = {"rsi": "RSI", "stoch": "estocástico", "adx": "ADX", "zema": "distancia a EMA50",
              "roc10": "momentum 10", "roc30": "momentum 30", "roc60": "momentum 60",
              "atr_ratio": "volatilidad relativa", "vol_ratio": "volumen relativo",
              "bbz": "posición en Bollinger", "gap": "brecha EMA20/EMA100"}


def describe(c):
    t = c["trig"]
    if t["fam"] == "expr":
        txt = " Y ".join(f"{FEAT_NAMES[x['f']]} {x['op']} percentil {int(x['q'] * 100)}"
                         for x in t["conds"])
        trig_txt = f"se cumplen a la vez: {txt}"
    else:
        trig_txt = NAMES[t["fam"]].format(**t)
    f = " + ".join(FNAMES[x["fam"]].format(**x) for x in c["filters"]) or "sin filtros"
    exit_ = (f"stop inicial {c['atr']}xATR y trailing {c['trail']}xATR" if c.get("trail")
             else f"stop {c['atr']}xATR, objetivo {c['rr']}x")
    risk = c.get("risk", RISK)
    extra = f" | riesgo {risk:.0%} por operación" if risk != RISK else ""
    return f"velas {c['tf']} | compra: {trig_txt} | filtros: {f} | {exit_}{extra}"


# ---------------- BÚSQUEDA ----------------
def load_results(path=None):
    path = path or RESULTS
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            out = [json.loads(line) for line in f if line.strip()]
    return out


def normalize(c):
    # ordena y quita filtros/condiciones repetidos
    uniq = {json.dumps(f, sort_keys=True): f for f in c["filters"]}
    c["filters"] = [uniq[k] for k in sorted(uniq)]
    if c["trig"]["fam"] == "expr":
        uniq = {json.dumps(x, sort_keys=True): x for x in c["trig"]["conds"]}
        c["trig"]["conds"] = [uniq[k] for k in sorted(uniq)]
    if c.get("trail"):
        c["rr"] = 0          # con trailing no hay objetivo: evita duplicados equivalentes
    else:
        c["trail"] = None
    c.setdefault("risk", RISK)
    return c


def search(minutes=None, data=None, path=None):
    path = path or RESULTS
    data = data or load_all()
    results = load_results(path)
    seen = {json.dumps(normalize(copy.deepcopy(r["cand"])), sort_keys=True) for r in results}
    best = max([r["score"] for r in results], default=-999.0)
    t0, n, good = time.time(), 0, []
    print(f"Buscando... ({len(results)} variantes ya probadas). Ctrl+C para detener.")
    try:
        while minutes is None or time.time() - t0 < minutes * 60:
            if n % 200 == 0:        # reordenar en cada vuelta sería lentísimo
                good = sorted((r for r in results if r["score"] > -900),
                              key=lambda r: -r["score"])[:20]
            if len(good) >= 10 and random.random() < 0.6:
                cand = mutate(random.choice(good)["cand"])
            else:
                cand = random_candidate()
            cand = normalize(cand)
            key = json.dumps(cand, sort_keys=True)
            if key in seen:
                n += 1
                continue
            seen.add(key)
            res = evaluate(cand, data)
            results.append(res)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(res) + "\n")
            n += 1
            if res["score"] > best:
                best = res["score"]
                print(f"\nNueva mejor (puntaje {best:+.3f}, positivos {res['pos']:.0%}, "
                      f"{res['trades']} ops):\n  {describe(cand)}")
            if n % 1000 == 0:
                print(f"  ... {n} intentos en esta sesión, {len(results)} guardadas")
    except KeyboardInterrupt:
        pass
    print(f"\nListo. {len(results)} variantes en total.")
    return len(results)


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


# ---------------- MODO AUTÓNOMO ----------------
def create_forward():
    """Primera vez: fija hasta qué momento se puede SELECCIONAR. Todo lo posterior es 'futuro'."""
    since = (now_ms() - YEARS * 365 * 24 * 3600 * 1000) // 3600_000 * 3600_000
    last = []
    for coin in COINS:
        raw = load_coin(coin, since, ttl=3600)
        last.append(int(raw.ts.iloc[-2]))                 # última vela CERRADA
    fwd = {"data_start_ts": since, "start_ts": min(last),
           "creado": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}
    with open(FORWARD_FILE, "w", encoding="utf-8") as f:
        json.dump(fwd, f, indent=2)
    return fwd


def forward_eval(data, cand):
    rows = []
    for coin in COINS:
        P = data[(coin, cand["tf"])]
        if P["n"] - P["hold"] < 50:
            continue
        ret, _dd, n = run(P, signal(P["D"], cand), P["hold"], P["n"], cand)
        hold = float(P["c"][P["n"] - 1] / P["c"][P["hold"]] - 1)
        rows.append({"coin": coin.split("/")[0], "ret": float(ret), "hold": hold, "ops": int(n)})
    return rows


def write_status(stats, fwd, data, champs):
    days = (max(int(P["D"].ts.iloc[-1]) for P in data.values()) - fwd["start_ts"]) / 86400_000
    L = ["# Estado del laboratorio", "",
         f"- Actualizado: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
         f"- Variantes probadas en total: **{stats['tested_total']:,}** en {stats['runs']} ejecuciones",
         f"- Datos de selección hasta: {time.strftime('%Y-%m-%d', time.gmtime(fwd['start_ts'] / 1000))}"
         f" | días de datos NUEVOS desde entonces: **{days:.1f}**", "",
         "Todo esto es simulación. Que algo se vea bien aquí NO significa que gane dinero real.", ""]
    if not champs:
        L.append("Todavía no hay campeón.")
    for k, ch in enumerate(champs, 1):
        L += [f"## Campeón {k}" if k == 1 else f"## Finalista {k}", "",
              describe(ch["cand"]), "",
              f"En los datos de selección: puntaje {ch['raw']:+.3f}, {ch['pos']:.0%} de tramos "
              f"positivos, {ch['trades']} operaciones.", ""]
        rows = ch.get("forward") or []
        if not rows:
            L += ["Datos nuevos: aún muy pocos para juzgar.", ""]
            continue
        L += ["Con datos NUEVOS (que nunca se usaron para elegir):", "",
              "| Moneda | Estrategia | Comprar y mantener | Operaciones |", "|---|---|---|---|"]
        L += [f"| {r['coin']} | {r['ret']:+.1%} | {r['hold']:+.1%} | {r['ops']} |" for r in rows]
        wins = sum(r["ret"] > 0 for r in rows)
        beat = sum(r["ret"] > r["hold"] for r in rows)
        L += ["", f"Ganó dinero en {wins} de {len(rows)} monedas y le ganó a comprar y mantener "
                  f"en {beat}. Con menos de ~60 días y ~20 operaciones no concluyas nada.", ""]
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def auto(minutes=45):
    global EXPLORE_RISK
    EXPLORE_RISK = True
    fwd = json.load(open(FORWARD_FILE, encoding="utf-8")) if os.path.exists(FORWARD_FILE) \
        else create_forward()
    data = load_all(fwd)
    before = len(load_results(AUTO_RESULTS))
    search(minutes, data, AUTO_RESULTS)
    results = load_results(AUTO_RESULTS)
    new = max(len(results) - before, 0)
    # el archivo solo conserva las mejores (GitHub no aguanta millones de líneas)
    good = sorted((r for r in results if r["score"] > -900), key=lambda r: -r["score"])[:KEEP_TOP]
    with open(AUTO_RESULTS, "w", encoding="utf-8") as f:
        for r in good:
            f.write(json.dumps(r) + "\n")
    stats = {"tested_total": 0, "runs": 0}
    if os.path.exists(AUTO_STATS):
        stats = json.load(open(AUTO_STATS, encoding="utf-8"))
    stats["tested_total"] += new
    stats["runs"] += 1
    json.dump(stats, open(AUTO_STATS, "w", encoding="utf-8"))
    # los 3 más distintos entre sí (por señal), el primero es el campeón
    champs, vistos = [], set()
    for r in good:
        marca = json.dumps([r["cand"]["tf"], r["cand"]["trig"]], sort_keys=True)
        if marca not in vistos:
            vistos.add(marca)
            r = dict(r)
            r["forward"] = forward_eval(data, r["cand"])
            champs.append(r)
        if len(champs) == 3:
            break
    if champs:
        json.dump(champs[0], open(CHAMPION_FILE, "w", encoding="utf-8"), indent=1)
    write_status(stats, fwd, data, champs)
    print(f"STATUS.md actualizado. Campeón: {describe(champs[0]['cand']) if champs else 'ninguno'}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "report":
        report(len(sys.argv) > 2 and sys.argv[2] == "force")
    elif cmd == "status":
        status()
    elif cmd == "auto":
        auto(float(sys.argv[2]) if len(sys.argv) > 2 else 45)
    else:
        search(float(sys.argv[2]) if len(sys.argv) > 2 else None)
