# Bot Trading

A research and simulation lab for exploring crypto trading strategies. The current project status and the latest out-of-sample notes are in [STATUS.md](STATUS.md).

## Scope

This repository is for research and simulation. Its published results are not evidence of future performance and should not be treated as a live trading recommendation. Check the limitations and sample sizes in STATUS.md before drawing conclusions.

The Jarvis idea (voice, home automation, chats, crypto and equities) is documented separately in [docs/JARVIS_ROADMAP.md](docs/JARVIS_ROADMAP.md). The assistant should remain a separate service from this strategy research code; it should not gain direct access to exchange keys or order execution.

## Current files

- `bot.py` — existing bot entry point.
- `research.py` — strategy research.
- `STATUS.md` — current experiment status and caveats.
- `champion.json`, `forward.json`, `auto_stats.json` — generated experiment metadata/results.

## Safety principles

- Keep experiments in simulation or paper-trading mode.
- Do not commit API keys, tokens, private account data or other secrets.
- A language model can explain a signal, but a separate risk layer must validate any future order.
- Never give an assistant withdrawal permissions.
