---
name: trading-research
description: Use when exploring, explaining, comparing or reviewing trading strategies, crypto or equities market data, backtests or paper-trading results. Do not use this skill to place live orders.
---

# Trading research

## Goals

Give clear, reproducible analysis. Separate observations from assumptions and never describe a backtest as a promise of future performance.

## Review checklist

- Identify the data source, asset, timeframe, date range, timezone and missing-data treatment.
- Check whether the strategy was selected using the same data used to report its results. Prefer a genuinely unseen out-of-sample period and walk-forward analysis.
- Include realistic fees, spread, slippage, liquidity constraints and funding/borrow costs when relevant.
- Compare with a simple benchmark such as buy-and-hold and a cash baseline.
- Report number of trades, exposure, drawdown, volatility and uncertainty along with returns. Small samples are inconclusive.
- Check survivorship bias, look-ahead leakage, repeated parameter search and data snooping.
- Show assumptions and enough steps to reproduce calculations. Do not hide losing assets or inactive periods.

## Safety rules

- Default to read-only analysis, backtesting or paper trading.
- Never call a live order endpoint, request a seed phrase, or put secrets in source files, logs or a report.
- Never assume a risk percentage from a prior experiment is appropriate. Surface position sizing and loss limits for review.
- Escalate live execution as a separate product decision requiring independent risk controls and explicit human confirmation.
- State plainly when data is insufficient. Do not call a strategy profitable based only on an in-sample score.
