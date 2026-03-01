# src/

<!-- Explorer: Fill in this section with architectural understanding -->

## Responsibility

- Orchestrates GengoWatcher CLI/TUI (`main.py` + `ui_textual.py`) and background monitors (`watcher.py`) that discover, notify, auto-accept, and cancel Gengo jobs while persisting state and telemetry.
- Manages configuration defaults, validation, and persistence via `config.py`, plus runtime state/metrics through `state.py` and `stats.py` so the UI, web API, and logging layers share a single source of truth.
- Encapsulates job handling helpers (`job_acceptance.py`, `job_cancellation_manager.py`, `notifier.py`) that implement rate-limited HTTP flows, async monitoring, and desktop notifications.
- Exposes a FastAPI-based web layer (`web.py`) that wraps a second watcher instance for API clients, serving REST/WebSocket endpoints and React assets.

## Design Patterns

- **Manager/Engine pattern:** `GengoWatcher` composes monitors (RSS, WebSocket, optional Email/Website) and delegates job acceptance/cancellation decisions to dedicated engines, keeping responsibilities separated.
- **Configuration guardrails:** `AppConfig` lazily bootstraps `config.ini`, ensures every section/option exists, serializes lists as JSON, and enforces invariants like valid AutoAccept ranges and placeholder detection.
- **Persistence via locks:** `AppState` and `StatsManager` use reentrant locks for thread safety, atomic file writes (temp+rename), and in-memory caches that feed the UI/logs while still persisting job/state history.
- **Asynchronous control:** `watcher.py` runs asyncio loops for WebSocket/monitoring, heartbeat/ping coroutines, and wraps async acceptance/cancellation calls with threads so the TUI/main thread stays responsive.
- **Rate limiting + retry:** `JobAcceptanceEngine` embeds a sliding-window `RateLimiter`, jittered delays, exponential backoff, and structured logging (JSONL) to make HTTP job acceptance resilient.

## Flow

- CLI entry (`main.py`) wires `AppConfig`, `AppState`, `StatsManager`, and the UI (`GengoWatcherApp`), then starts the watcher thread and optional FastAPI server before launching Textual.
- `GengoWatcher` spawns monitor threads: RSS poller (feedparser/parsing rewards), WebSocket loop (async session, heartbeat, test commands), and optional Email/Website monitors; every new job funnels into `_process_new_job`.
- `_process_new_job` filters by `min_reward`, updates `AppState`, logs entries, notifies the user, enqueues cancellation checks (`JobCancellationManager`) and auto-accept (`JobAcceptanceEngine`), and saves state/stats.
- Acceptance/cancellation engines perform HTTP workflows (details page fetch, CSRF extraction, form submission) with aiohttp, and track stats/logs so UI and API surface status; rejection/captcha falls through to logging for visibility.
- `StatsManager`, `AppState`, and `JobCancellationManager` expose snapshots consumed by the Textual widgets (`MetricsRow`, `StatusRow`, previews) and FastAPI endpoints, while `TextualLogHandler` mirrors logger output to the UI-rich log.

## Integration Points

- CLI/TUI (`main.py`, `ui_textual.py`) consumes `config`, `state`, `stats`, and `GengoWatcher`, and registers `TextualLogHandler` so all logging flows into the ActivityPreview.
- Watcher interacts with helper modules: `JobAcceptanceEngine` for auto-accept, `JobCancellationManager` for job swaps, `notifier` for desktop alerts, and `AppState`/`StatsManager` to persist jobs/metrics (also used by `web.py`).
- FastAPI layer (`web.py`) creates its own watcher instance but shares `AppConfig`/`AppState`, exposes REST `/api/*` and `/ws/status`, and uses `APIAuthenticator` for token-based security; React static assets are mounted at `/web`.
- Config modifications propagate via `AppConfig.set`, which writes `config.ini` and is surfaced to CLI commands, interactive prompts, and the web API update endpoints.
- Persistent files (`logs/`, `state.json`, `jobs CSV`) capture acceptance attempts (`logs/accept_attempts.log`), cancellation state (`logs/job_cancellation_state.json`), and RSS history, allowing `AppState.load_jobs_from_csv` and the web API CSV reader to rehydrate history.
