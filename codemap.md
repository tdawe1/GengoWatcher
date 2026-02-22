# Repository Atlas: GengoWatcher

## Project Responsibility
- Monitor Gengo jobs via RSS/WebSocket/email/website sources, surface them in a Textual TUI or FastAPI web API, and optionally auto-accept/cancel while persisting state, logs, and analytics.

## System Entry Points
- `src/gengowatcher/main.py`: CLI command router; launches TUI watcher or web server.
- `src/gengowatcher/ui_textual.py`: Textual UI that binds to watcher state.
- `src/gengowatcher/web.py`: FastAPI web service exposing REST/WS endpoints and static assets.
- `config.ini`: Primary runtime configuration; bootstrapped/validated by `AppConfig`.
- `Makefile`: Developer task shortcuts (lint/test/run utilities).

## Directory Map (Aggregated)

| Directory | Responsibility Summary | Detailed Map |
| --- | --- | --- |
| `src/` | Core implementation for the watcher, config/state/stats, CLI/TUI, acceptance/cancellation engines, and FastAPI layer. | [View Map](src/codemap.md) |
| `src/gengowatcher/` | Primary package: monitors, orchestrator, CLI/TUI/web entry points, config/state/stats, and notifier helpers. | [View Map](src/gengowatcher/codemap.md) |
| `scripts/` | Standalone operational and analysis utilities (import/analyze logs, websocket tools, safety/validation checks). | [View Map](scripts/codemap.md) |
