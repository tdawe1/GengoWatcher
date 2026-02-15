# src/gengowatcher/

## Responsibility

- Drives the core Gengo job watcher experience: loads `AppConfig`, keeps `AppState` and `StatsManager` in sync, and orchestrates job discovery, filtering, notification, auto-acceptance and cancellation logic via `GengoWatcher`.
- Hosts the CLI/TUI entrypoint (`main.py` + `ui_textual.py`), FastAPI-powered web API (`web.py`), and optional setup wizards (`oauth_setup.py`, `website_setup.py`) that keep CLI, GUI and automation helpers in one package.
- Provides adapters for each signal source (`rss`, `websocket`, `email_monitor`, `website_monitor`), the acceptance/cancellation engines, and user-facing notifier helpers so the system can react to new opportunities and keep the user informed.

## Design

- `AppConfig` boots with defaults, repairs missing sections/options, and exposes thread-safe getters/setters plus CLI helpers before the watcher starts.
- `AppState` + `StatsManager` use locks, atomic writes, bounded caches (`deque`), and dataclasses to persist seen job history, sparkline data, session/all-time stats, and provide recent/job-count helpers for the UI/API.
- `GengoWatcher` is the orchestrator: it spawns monitor threads/async loops (RSS polling, WebSocket, optional Email/Website monitors), funnels every new job through `_process_new_job`, and interacts with `JobAcceptanceEngine` (rate limited async HTTP/AcceptResult/AcceptForm pattern) and `JobCancellationManager` (lock-protected state, JSON persistence, HTTP cancellation workflow).
- FastAPI-based `WebAPI` initializes its own watcher thread, wraps shared state with RLocks, and exposes authenticated REST/WebSocket endpoints plus CSV access so external dashboards can piggyback on the same backend.
- Notifier utilities (`notifier.py`) abstract desktop sound/notification playback so the watcher logic stays agnostic of platform tooling.

## Flow

1. `main.py` loads `AppConfig`, handles CLI config commands (set/get/list/configure) or interactive setup wizards, then initializes logging, `AppState`, `StatsManager`, and `GengoWatcher`.
2. `GengoWatcher.run()` launches threads for RSS polling (`feedparser` + `_run_rss_monitor`), WebSocket (`websockets` + `_run_websocket_monitor`), optional `EmailMonitor`/`WebsiteMonitor`, and keeps shared metrics/state updated for the TUI and web API.
3. Each monitor reports new job metadata to `_process_new_job`, which deduplicates via `AppState`, updates counters/stats, logs entries, sends notifications, persists state, and (when enabled) delegates to `JobAcceptanceEngine` to attempt an HTTP acceptance and `JobCancellationManager` to drop weaker engagements.
4. `JobAcceptanceEngine` uses a sliding-window `RateLimiter`, retry/backoff loops, AcceptForm parsing (BeautifulSoup), and captcha detection stubs to perform async HTTP accepts while recording timing data; `JobCancellationManager` checks current job value, posts cancellation forms, and records stats/state JSON under `logs/`.
5. `ui_textual` binds to the running watcher, config and state to render metric cards, status indicators, tables, and command bindings; `web.py` can host the same watcher via FastAPI/uvicorn and serve React assets plus authenticated REST/WebSocket routes.

## Integration

- `main.py` wires everything: CLI args control config commands, web server startup (`web.run_web_server`), or launching the Textual TUI (`GengoWatcherApp`), so this package is both CLI and service-friendly.
- `ui_textual.py` pulls from `GengoWatcher`, `AppState`, `StatsManager`, and CSS (`gengo_watcher.tcss`) to drive the terminal UI and issue commands back to the watcher via bound actions.
- `web.py` provides the cloud/native surface: `WebAPI` creates a second `GengoWatcher`, shares `AppState`, guards endpoints with `APIAuthenticator`, and exposes `/api/status`, `/api/jobs`, `/api/config`, command endpoints, and `/ws/status` for live dashboards.
- `AppConfig` links to `oauth_setup.py` (Gmail OAuth) and `website_setup.py` (Playwright) for optional monitors; those helpers mutate the same config so the watcher picks up new credentials without code changes.
- `notifier.py`, `StatsManager`, `state.py`, `job_acceptance.py`, and `job_cancellation_manager.py` all live under `src/gengowatcher/` so the CLI, TUI, and web layers can share persistence, logging, and monitoring hooks without crossing package boundaries.
