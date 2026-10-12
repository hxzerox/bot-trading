"""
Bot de trading SPOT para Binance (solo compras, sin apalancamiento). Base educativa.

Instalar:  pip install ccxt pandas python-dotenv
Claves:    archivo .env junto a este archivo con
             BINANCE_API_KEY=tu_clave_testnet
             BINANCE_SECRET=tu_secreto_testnet
           (Testnet: https://testnet.binance.vision). NUNCA compartas estas claves.

Uso:
  python bot.py backtest   # prueba con 2 años de datos reales (no necesita claves)
  python bot.py live       # bucle continuo en tu PC (TESTNET mientras USE_TESTNET = True)
  python bot.py once       # una sola revisión y termina (para ejecutarlo desde la nube)

El bot guarda su posición en state.json y cada operación en trades.csv,
así que puede reiniciarse sin perder el stop ni el objetivo.
"""
import csv
import json
import os
import sys
import time

import ccxt
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ---------------- CONFIGURACIÓN ----------------
SYMBOL = "BTC/USDT"
TIMEFRAME = "1h"
RISK_PER_TRADE = 0.01   # arriesga 1% del capital por operación
ATR_STOP_MULT = 3.0     # stop-loss a 3 ATR por debajo de la entrada
RR = 3.0                # take-profit = 3 veces el riesgo
RSI_LEVEL = 45          # compra cuando el RSI sube cruzando este nivel
MAX_DAILY_LOSS = 0.03   # si pierde 3% en el día, no opera más ese día
FEE = 0.001             # comisión Binance 0.1% por lado
USE_TESTNET = True      # NO lo cambies hasta tener buenos resultados de backtest + testnet
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


def buy_signal(row, prev):
    """Compra por confluencia: tendencia alcista + rebote del RSI + volumen."""
    uptrend = row.ema50 > row.ema200 and row.close > row.ema200
    rsi_rebound = prev.rsi < RSI_LEVEL <= row.rsi
    volume_ok = row.volume > row.vol_ma
    return bool(uptrend and rsi_rebound and volume_ok)


# ---------------- BACKTEST ----------------
def fetch_history(ex, years=2):
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


def backtest(capital=1000.0):
    df = indicators(fetch_history(ccxt.binance({"enableRateLimit": True})))
    df = df.dropna().reset_index(drop=True)

    eq, peak, max_dd = capital, capital, 0.0
    pnls, pos = [], None

    for i in range(1, len(df) - 1):
        r = df.iloc[i]
        if pos:
            if r.low <= pos["stop"]:
                exit_p = pos["stop"]          # si toca ambos, asumimos el peor caso
            elif r.high >= pos["tp"]:
                exit_p = pos["tp"]
            else:
                continue
            a, e = pos["amount"], pos["entry"]
            pnl = a * (exit_p - e) - FEE * a * (exit_p + e)
            eq += pnl
            pnls.append(pnl)
            pos = None
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak)
            continue

        if buy_signal(r, df.iloc[i - 1]):
            entry = df.iloc[i + 1].open       # entra en la vela siguiente (sin "hacer trampa")
            risk = ATR_STOP_MULT * r.atr
            amount = min(eq * RISK_PER_TRADE / risk, eq * 0.95 / entry)
            pos = {"entry": entry, "stop": entry - risk,
                   "tp": entry + RR * risk, "amount": amount}

    wins = sum(p > 0 for p in pnls)
    hold = capital * df.iloc[-1].close / df.iloc[0].close
    print(f"Operaciones: {len(pnls)} | Ganadoras: {wins} "
          f"({100 * wins / max(len(pnls), 1):.0f}%)")
    print(f"Capital final: {eq:.2f} (inicio {capital:.2f}) "
          f"= {100 * (eq / capital - 1):+.1f}%")
    print(f"Caída máxima: {100 * max_dd:.1f}%")
    print(f"Comprar y mantener habría dado: {hold:.2f} "
          f"= {100 * (hold / capital - 1):+.1f}%")


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
    return {"pos": None, "day": None, "day_start": None,
            "last_check_ms": None, "last_signal_ts": 0}


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


def step(ex, s):
    """Una revisión completa: gestiona la posición abierta o busca una señal nueva."""
    base = SYMBOL.split("/")[0]
    now_ms = ex.milliseconds()
    price = ex.fetch_ticker(SYMBOL)["last"]
    eq = equity(ex, price)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if s["day"] != today:
        s["day"], s["day_start"] = today, eq

    pos = s["pos"]
    if pos:
        # Revisa todas las velas de 1 minuto desde la última revisión, para no
        # perder un stop u objetivo tocado entre dos ejecuciones.
        since = s["last_check_ms"] or (now_ms - 3600 * 1000)
        candles = ex.fetch_ohlcv(SYMBOL, "1m", since=since, limit=1000)
        low = min([c[3] for c in candles] + [price])
        high = max([c[2] for c in candles] + [price])
        reason = "stop" if low <= pos["stop"] else ("objetivo" if high >= pos["tp"] else None)
        if reason:
            free = ex.fetch_balance()[base]["free"]
            amount = float(ex.amount_to_precision(SYMBOL, min(pos["amount"], free)))
            order = ex.create_market_sell_order(SYMBOL, amount)
            fill = order.get("average") or price
            log_trade("venta", fill, amount, reason, eq)
            print(f"Venta ({reason}) {amount} a {fill:.2f} | capital {eq:.2f}")
            s["pos"] = None
    elif eq < s["day_start"] * (1 - MAX_DAILY_LOSS):
        print("Tope de pérdida diaria alcanzado. Sin operar hasta mañana.")
    else:
        df = indicators(to_df(ex.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=300)))
        row, prev = df.iloc[-2], df.iloc[-3]          # última vela CERRADA
        # Cada vela solo puede disparar UNA compra (evita recomprar tras un stop).
        if int(row.ts) > s["last_signal_ts"] and buy_signal(row, prev):
            s["last_signal_ts"] = int(row.ts)
            risk = float(ATR_STOP_MULT * row.atr)
            amount = min(eq * RISK_PER_TRADE / risk, eq * 0.95 / price)
            amount = float(ex.amount_to_precision(SYMBOL, amount))
            order = ex.create_market_buy_order(SYMBOL, amount)
            fill = float(order.get("average") or price)
            s["pos"] = {"stop": fill - risk, "tp": fill + RR * risk, "amount": amount}
            log_trade("compra", fill, amount, "señal", eq)
            print(f"Compra {amount} a {fill:.2f} | stop {fill - risk:.2f} "
                  f"| objetivo {fill + RR * risk:.2f}")
    s["last_check_ms"] = now_ms


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


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "backtest"
    {"backtest": backtest, "live": live, "once": once}.get(mode, backtest)()
