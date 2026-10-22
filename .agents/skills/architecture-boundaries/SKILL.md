---
name: architecture-boundaries
description: Use when planning or changing this project, adding a market, broker, chat, voice or home-automation integration, or deciding where code should live.
---

# Architecture boundaries

## Keep the design understandable

- Separate assistant conversation, channel adapters, connectors, domain rules, market research, risk checks, execution and storage.
- Define small interfaces for external services so one vendor can be replaced without rewriting strategy logic.
- Normalize external data at connector boundaries and validate it before domain code uses it.
- Keep credentials and network calls out of strategy calculation modules.
- Make order execution a separately configured service; use read-only or paper mode by default.
- Record consequential actions and their approval in an audit trail.

## Repository changes

- Inspect existing conventions before adding folders, dependencies or workflows.
- Prefer a small, complete change over a broad rewrite or framework collection.
- Document new external services, required configuration and failure behavior.
- Do not add secrets, automatic live-trading workflows or unattended deployments.
- Keep this repository's research lab distinct from the future Jarvis runtime. Link to a separate service rather than coupling the assistant to strategy internals.
