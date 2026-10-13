"""
Bot de trading SPOT para Binance (solo compras, sin apalancamiento). v2: estrategia candidata
del laboratorio (research.py) con trailing stop. EXPERIMENTAL: no tiene ventaja demostrada.

Instalar:  pip install ccxt pandas python-dotenv
Claves:    archivo .env junto a este archivo con
             BINANCE_API_KEY=tu_clave_testnet
             BINANCE_SECRET=tu_secreto_testnet
           (Testnet: https://testnet.binance.vision). NUNCA compartas estas claves.

Uso:
  python bot.py backtest   # prueba con 4 años de datos reales (no necesita claves)
  python bot.py live       # bucle continuo en tu PC (TESTNET mientras USE_TESTNET = True)
  python bot.py once       # una sola revisión y termina (para ejecutarlo desde la nube)
  python bot.py resumen    # cómo va el Testnet frente a comprar y mantener

Estrategia (velas de 4h): compra cuando el precio rompe el máximo de las últimas 40 velas,
con el precio sobre su EMA100, momentum de 30 velas positivo y RSI > 50.
Stop inicial a 2 ATR; el stop sube siguiendo al máximo a 4 ATR (trailing). Salida por tiempo a
las 300 velas (50 días).

El bot guarda su posición en state.json y cada operación en trades.csv,
así que puede reiniciarse sin perder el stop.
"""
import csv
import json
import os
import sys
import time

import ccxt
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ---------------- CONFIGURACIÓN ----------------
SYMBOL = "BTC/USDT"
TIMEFRAME = "4h"
BAR_MS = 4 * 3600 * 1000
DON_N = 40              # ruptura del máximo de 40 velas
EMA_N = 100             # precio sobre esta EMA
RSI_MIN = 50
RISK_PER_TRADE = 0.02   # arriesga 2% del capital por operación
ATR_STOP_MULT = 2.0     # stop inicial a 2 ATR bajo la entrada
TRAIL_MULT = 4.0        # el stop sigue al máximo a 4 ATR
MAX_BARS = 300          # salida por tiempo (en velas)
MAX_DAILY_LOSS = 0.03   # si pierde 3% en el día, no opera más ese día
FEE = 0.001             # comisión Binance 0.1% por lado
SLIP = 0.0005           # deslizamiento supuesto por lado (solo backtest)
MIN_NOTIONAL = 10.0     # orden mínima en USDT
USE_TESTNET = True      # NO lo cambies hasta que el Testnet le gane a comprar y mantener
STATE_FILE = "state.json"
TRADES_FILE = "trades.csv"
# -----------------------------------------------


def to_df(ohlcv):
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    return df.drop_duplicates("ts").reset_index(drop=True)


def indicators(df):
    c = df["close"]
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    df["ema200"] = c.ewm(span=200, adjust=False).mean()
    df["ema_f"] = c.ewm(span=EMA_N, adjust=False).mean()
    df["roc30"] = c.pct_change(30)
    df["don"] = df["high"].rolling(DON_N).max().shift(1)

    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + gain / loss)

    tr = pd.concat(
        [df["high"] - df["low"],
         (df["high"] - c.shift()).abs(),
         (df["low"] - c.shift()).abs()],
        axis=1,
    ).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["vol_ma"] = df["volume"].rolling(20).mean()
    return df


def signals(df):
    """True en cada vela donde se cumple la señal de compra (confluencia)."""
    breakout = (df.close > df.don) & (df.close.shift(1) <= df.don.shift(1))
    ok = (df.close > df.ema_f) & (df.roc30 > 0) & (df.rsi > RSI_MIN)
    return (breakout & ok).to_numpy()


# ---------------- BACKTEST ----------------
def fetch_history(ex, years=4):
    since = ex.milliseconds() - years * 365 * 24 * 3600 * 1000
    out = []
    while True:
        batch = ex.fetch_ohlcv(SYMBOL, TIMEFRAME, since=since, limit=1000)
        if not batch:
            break
        out += batch
        since = batch[-1][0] + 1
        if len(batch) < 1000:
            break
    return to_df(out)


def simulate(df, capital=1000.0):
    """Devuelve (capital final, caída máxima, lista de resultados por operación)."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    atr, sig = df.atr.to_numpy(), signals(df)
    N = len(df)
    idx = np.flatnonzero(sig)
    eq, peak, mdd, pnls, k = capital, capital, 0.0, [], 0
    while k < len(idx):
        i = idx[k]
        if i + 1 >= N:
            break
        entry = o[i + 1] * (1 + SLIP)
        risk = ATR_STOP_MULT * atr[i]
        if not risk > 0:
            k += 1
            continue
        stop, hh, end, exit_j, exit_p = entry - risk, entry, min(N, i + 1 + MAX_BARS), None, None
        for j in range(i + 1, end):
            if o[j] <= stop:
                exit_j, exit_p = j, o[j]
                break
            if l[j] <= stop:
                exit_j, exit_p = j, stop
                break
            hh = max(hh, h[j])
            stop = max(stop, hh - TRAIL_MULT * atr[i])
        if exit_j is None:
            if i + 1 + MAX_BARS > N:
                break                      # operación aún abierta al final: se ignora
            exit_j, exit_p = end - 1, c[end - 1]
        exit_p *= (1 - SLIP)
        amt = min(eq * RISK_PER_TRADE / risk, eq * 0.95 / entry)
        pnl = amt * (exit_p - entry) - FEE * amt * (exit_p + entry)
        eq += pnl
        pnls.append(pnl)
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
        k = int(np.searchsorted(idx, exit_j, side="right"))
    return eq, mdd, pnls


def backtest(capital=1000.0, df=None):
    if df is None:
        df = indicators(fetch_history(ccxt.binance({"enableRateLimit": True})))
    df = df.dropna().reset_index(drop=True)
    eq, mdd, pnls = simulate(df, capital)
    wins = sum(p > 0 for p in pnls)
    hold = capital * df.iloc[-1].close / df.iloc[0].close
    print(f"Operaciones: {len(pnls)} | Ganadoras: {wins} "
          f"({100 * wins / max(len(pnls), 1):.0f}%)")
    print(f"Capital final: {eq:.2f} (inicio {capital:.2f}) = {100 * (eq / capital - 1):+.1f}%")
    print(f"Caída máxima: {100 * mdd:.1f}%")
    print(f"Comprar y mantener habría dado: {hold:.2f} = {100 * (hold / capital - 1):+.1f}%")
    return eq


# ---------------- EN VIVO ----------------
def make_exchange():
    ex = ccxt.binance({
        "apiKey": os.getenv("BINANCE_API_KEY"),
        "secret": os.getenv("BINANCE_SECRET"),
        "enableRateLimit": True,
    })
    if USE_TESTNET:
        ex.set_sandbox_mode(True)
    return ex


def equity(ex, price):
    base, quote = SYMBOL.split("/")
    bal = ex.fetch_balance()
    return bal[quote]["total"] + bal[base]["total"] * price


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"pos": None, "day": None, "day_start": None, "last_signal_ts": 0, "start": None}


def save_state(s):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)


def log_trade(side, price, amount, reason, eq):
    new = not os.path.exists(TRADES_FILE)
    with open(TRADES_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["fecha_utc", "lado", "precio", "cantidad", "motivo", "capital"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), side,
                    round(price, 2), amount, reason, round(eq, 2)])


def fetch_1m(ex, since):
    out = []
    while True:
        b = ex.fetch_ohlcv(SYMBOL, "1m", since=since, limit=1000)
        if not b:
            break
        out += b
        since = b[-1][0] + 1
        if len(b) < 1000:
            break
    return out


def step(ex, s):
    """Una revisión completa: gestiona la posición abierta o busca una señal nueva."""
    base = SYMBOL.split("/")[0]
    now_ms = ex.milliseconds()
    price = ex.fetch_ticker(SYMBOL)["last"]
    eq = equity(ex, price)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if not s.get("start"):
        s["start"] = {"fecha": today, "capital": eq, "precio": price}
    if s["day"] != today:
        s["day"], s["day_start"] = today, eq

    pos = s["pos"]
    if pos:
        # Recorre las velas de 1 minuto YA CERRADAS desde la última revisión, en orden, para no
        # perder un stop tocado entre dos ejecuciones ni subir el stop con un máximo que aún
        # no ocurrió.
        reason = None
        for ts, _o, hi, lo, _c, _v in fetch_1m(ex, pos["seen_ts"] + 1):
            if ts + 60000 > now_ms:
                break                               # vela de este minuto, aún abierta
            pos["seen_ts"] = ts
            if lo <= pos["stop"]:
                reason = "trailing" if pos["stop"] > pos["stop0"] else "stop"
                break
            pos["hh"] = max(pos["hh"], hi)
            pos["stop"] = max(pos["stop"], pos["hh"] - TRAIL_MULT * pos["atr"])
        if reason is None and price <= pos["stop"]:
            reason = "trailing" if pos["stop"] > pos["stop0"] else "stop"
        if reason is None and now_ms - pos["entry_ms"] >= MAX_BARS * BAR_MS:
            reason = "tiempo"
        if reason:
            free = ex.fetch_balance()[base]["free"]
            amount = float(ex.amount_to_precision(SYMBOL, min(pos["amount"], free)))
            order = ex.create_market_sell_order(SYMBOL, amount)
            fill = float(order.get("average") or price)
            log_trade("venta", fill, amount, reason, eq)
            print(f"Venta ({reason}) {amount} a {fill:.2f} | capital {eq:.2f}")
            s["pos"] = None
    elif eq < s["day_start"] * (1 - MAX_DAILY_LOSS):
        print("Tope de pérdida diaria alcanzado. Sin operar hasta mañana.")
    else:
        df = indicators(to_df(ex.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=300)))
        sig = signals(df)
        row = df.iloc[-2]                              # última vela CERRADA
        # Cada vela solo puede disparar UNA compra (evita recomprar tras un stop).
        if int(row.ts) > s["last_signal_ts"] and sig[-2] and row.atr > 0:
            s["last_signal_ts"] = int(row.ts)
            risk = float(ATR_STOP_MULT * row.atr)
            amount = min(eq * RISK_PER_TRADE / risk, eq * 0.95 / price)
            amount = float(ex.amount_to_precision(SYMBOL, amount))
            if amount * price < MIN_NOTIONAL:
                print("Señal ignorada: la orden sería menor al mínimo de Binance.")
            else:
                order = ex.create_market_buy_order(SYMBOL, amount)
                fill = float(order.get("average") or price)
                s["pos"] = {"entry_ms": now_ms, "entry": fill, "amount": amount,
                            "atr": float(row.atr), "hh": fill, "stop0": fill - risk,
                            "stop": fill - risk, "seen_ts": now_ms // 60000 * 60000 - 1}
                log_trade("compra", fill, amount, "señal", eq)
                print(f"Compra {amount} a {fill:.2f} | stop {fill - risk:.2f} "
                      f"(sube siguiendo al máximo a {TRAIL_MULT}xATR)")


def once():
    ex = make_exchange()
    ex.load_markets()
    s = load_state()
    try:
        step(ex, s)
    finally:
        save_state(s)


def live():
    ex = make_exchange()
    ex.load_markets()
    s = load_state()
    print(f"Bot iniciado ({'TESTNET' if USE_TESTNET else 'REAL'}). "
          f"Posición guardada: {'sí' if s['pos'] else 'no'}")
    while True:
        try:
            step(ex, s)
        except Exception as e:
            print("Error:", e)
        save_state(s)
        time.sleep(60)


def resumen():
    """Compara el Testnet con simplemente comprar y mantener desde el primer día."""
    ex = make_exchange()
    ex.load_markets()
    s = load_state()
    if not s.get("start"):
        print("Todavía no hay datos: deja correr el bot al menos una vez.")
        return
    price = ex.fetch_ticker(SYMBOL)["last"]
    eq = equity(ex, price)
    st = s["start"]
    mine, hold = eq / st["capital"] - 1, price / st["precio"] - 1
    print(f"Desde {st['fecha']}: bot {mine:+.1%} | comprar y mantener {hold:+.1%}")
    ops = []
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        buy = None
        for r in rows:
            if r["lado"] == "compra":
                buy = r
            elif buy:
                ops.append((float(r["precio"]) - float(buy["precio"])) * float(r["cantidad"]))
                buy = None
    wins = sum(p > 0 for p in ops)
    print(f"Operaciones cerradas: {len(ops)} | ganadoras: {wins}")
    if len(ops) < 20:
        print("Pocas operaciones aún: no concluyas nada hasta tener varias semanas de datos.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "backtest"
    {"backtest": backtest, "live": live, "once": once, "resumen": resumen}.get(mode, backtest)()
