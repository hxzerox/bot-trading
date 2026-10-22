# Jarvis roadmap: voice, home automation, chats and markets

This document prepares the project for a later installation on a dedicated computer. GitHub stores the code, skills and documentation; it does not run the assistant by itself. No runtime or trading package is installed by adding these files.

## Keep responsibilities separate

Keep this repository as the strategy research and simulation lab. Build Jarvis as a separate service that can read approved market data and request reports from this lab. Do not let the conversation agent import trading internals or hold broker/exchange credentials.

Suggested layout for the future Jarvis repository:

```text
jarvis/
  api/                   # validated HTTP interfaces
  assistant/             # conversation and orchestration
  channels/              # voice and chat adapters
  connectors/            # MCP, Home Assistant, market data and brokers
  domain/                # shared business rules and typed models
  trading/
    market_data/         # normalized market data
    research/            # backtests and analysis
    risk/                # limits and pre-trade checks
    execution/           # paper mode first; isolated from the agent
  storage/               # history and persistence
  observability/         # logs, metrics and audit trail
  .agents/skills/        # project-specific agent instructions
```

## Candidate building blocks

Choose only the pieces required for the first working version. Verify current maintenance, licensing, security and country availability before adopting a dependency.

| Need | Candidate | Notes |
|---|---|---|
| Voice and home automation | [Home Assistant](https://github.com/home-assistant/core) + [Assist](https://www.home-assistant.io/voice_control/) | Strong starting point for local home control and voice. |
| Personal assistant with chat channels | [OpenClaw](https://github.com/openclaw/openclaw) | Broad channel support; review every permission and tool before enabling actions. |
| Custom Python agent | [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) | Tools, handoffs, guardrails, sessions and voice support. |
| Stateful agent workflows | [LangGraph](https://github.com/langchain-ai/langgraph) | Useful when workflows need durable state and resumability. |
| App integrations | [MCP Registry](https://github.com/modelcontextprotocol/registry), [FastMCP](https://github.com/PrefectHQ/fastmcp), [Composio](https://github.com/ComposioHQ/composio) | Inspect the maintainer, source code, scopes and secret handling for each connector. |
| Visual automation | [n8n](https://github.com/n8n-io/n8n) | Connects APIs and apps; it can be self-hosted. |
| Crypto exchange APIs | [CCXT](https://github.com/ccxt/ccxt) | Unified exchange APIs; start read-only or in sandbox/paper mode. |
| Crypto strategy research | [Freqtrade](https://github.com/freqtrade/freqtrade) or [Hummingbot](https://github.com/hummingbot/hummingbot) | Backtest or paper trade before considering live execution. |
| Multi-market research | [LEAN](https://github.com/QuantConnect/Lean) or [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | Check data and brokerage requirements for your market. |
| Equity broker connection | [Alpaca-py](https://github.com/alpacahq/alpaca-py) or [ib_async](https://github.com/ib-api-reloaded/ib_async) | Confirm broker, instruments and API access for your country. |
| Chat bots | [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot), [aiogram](https://github.com/aiogram/aiogram), [discord.py](https://github.com/Rapptz/discord.py) | Use official APIs and least-privilege bot tokens. |

## Suggested rollout

1. Decide which functions run locally on the dedicated computer and which use a hosted API.
2. Build a read-only assistant for market summaries and approved home status.
3. Add one chat channel and one Home Assistant voice path.
4. Add market data and reports; do not connect order execution to the assistant.
5. Validate trading strategies with realistic fees, slippage, out-of-sample periods, drawdown and enough trades.
6. Add paper trading with an explicit kill switch and audit log.
7. Only if separately chosen later, add live execution behind independent risk limits and a human confirmation step.

## Security and trading controls

- Store secrets in the target machine's secret manager or environment configuration, never in Git.
- Use separate credentials per service and minimum required scopes. Disable withdrawals on exchange keys.
- Treat messages, documents and connector output as untrusted input; never let them override system policy or grant new permissions.
- Require confirmation for actions that change devices, send messages or place orders.
- Keep a record of tool calls and who approved consequential actions.
- Backtests and simulated results do not guarantee profit. The current [STATUS.md](../STATUS.md) describes this repository's experiment limits.
