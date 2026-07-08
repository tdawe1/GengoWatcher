# Changelog

All notable changes to GengoWatcher are documented in this file.
This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2.9.3] - 2026-07-08

### Fixed
- `_event_loop` teardown race in `WebAPI` websocket handler: refcount loop
  pointer so concurrent WS connections don't clear each other's broadcast loop
  on disconnect (`src/gengowatcher/web.py`).
- Webhook executor was a module-level ThreadPoolExecutor that survived until
  interpreter shutdown; now registers `atexit.shutdown(wait=False)` so the
  daemon pool is released cleanly (`src/gengowatcher/webhooks.py`).
- `state.py` `_track_job_unlocked` used `setdefault` for the new lookup
  index, leaving stale pointers when a brand-new job shared an identifier
  tuple (e.g. matching `order_id`) with a prior job. Now last-write-wins
  (`src/gengowatcher/state.py`).
- `_calculate_accepted_seconds_left` dropped expire values <= 1e9 (Unix-epoch
  seconds) on the floor. Restored the `> 10_000_000_000` ms-vs-sec cutoff
  only; everything positive is now treated as a Unix epoch second
  (`src/gengowatcher/state.py`).

### Added
- Anti-detection hardening for the Gengo WebSocket handshake:
  - `build_browser_aligned_websocket_headers` no longer emits `Pragma`,
    `Cache-Control: no-cache`, or `Accept-Encoding` (none of which appear on
    a real Chrome WS upgrade); distinct cookie values for `myG_myGSession_`
    and `myG_rdsessID` (`src/gengowatcher/browser_session.py`).
  - Adds `Sec-CH-UA`, `Sec-CH-UA-Mobile`, `Sec-CH-UA-Platform`,
    `Sec-Fetch-Mode`, `Sec-Fetch-Site` Client Hints when the configured UA
    is modern Chrome (`src/gengowatcher/browser_session.py`).
  - Standalone gateway (`websocket_server.py`) now sends auth as
    `{userId, sessionToken, userKey?}` — the same camelCase shape the
    in-process monitor and Gengo's web frontend use.
- Playwright Chromium launches with `--disable-blink-features=AutomationControlled`
  and an init script that overwrites `navigator.webdriver` on every
  navigation, removing `__webdriver_*` internals, and stubbing
  `window.chrome.runtime` (`src/gengowatcher/browser_worker/runtime.py`).
- WebSocket monitor heartbeat is jittered ±5s around the configured interval
  (`src/gengowatcher/websocket_monitor.py`).
- Native Firefox RDP listener poll interval is jittered ±150ms
  (`src/gengowatcher/native_browser_listener.py`).
- WebSocket monitor fails closed with a clear log when `user_key` is missing
  or set to `REPLACE_WITH_YOUR_USER_KEY` (`src/gengowatcher/websocket_monitor.py`).

### Security
- `/api/jobs/discovered` now requires bearer auth; the webhook alias
  `/api/webhooks/jobs/discovered` is forced to `require_signature=True`
  (`src/gengowatcher/web.py`).
- `_read_limited_request_body` is bounded by an `asyncio.timeout(10.0)`
  and a chunk-count cap to prevent slow-loris on the unauthenticated webhook
  path (`src/gengowatcher/web.py`).

### Internal
- Cookie snapshot includes `rd_session_id` separately; BiDi and CDP
  fetchers extract both `myG_myGSession_` and `myG_rdsessID` from the
  browser cookie store (`src/gengowatcher/browser_session.py`).
- Workbench JS scan now measures serialized size and returns
  `{payload: null, oversized: true}` above 768 KB to avoid silent
  truncation through the RDP/BiDi eval channel
  (`src/gengowatcher/native_browser_listener.py`).
- Rebase repair: `_run_browser_worker_event_listener` indentation restored
  to compile cleanly (`src/gengowatcher/watcher.py`).

## [2.9.2] - 2026-07-07

### Added
- API-driven browser job telemetry: webhook-backed API event plumbing,
  audit logging, TUI API controls, native Firefox RDP listener, event bus,
  state projector, workbench payload normalization
  (PR #116, `codex/api-browser-job-telemetry`).
- Countdown tracking and notifications for elapsed, halfway, and low-time
  thresholds.
- New TUI tabs for browser jobs, audit log, and telemetry.
- Prometheus scrape config + alert rules for system / service monitoring
  (`ops/prometheus/`).

### Changed
- User-facing webhook terminology replaced with API/event terminology in
  the TUI, health snapshot, and public routes.
- Public API event routes added at `/api/jobs/discovered` and
  `/api/events/audit`; old webhook routes retained as hidden aliases.
- Dashboard status row fits at 80 columns and shows `API` plus browser
  status first.

## [2.1.5] - 2025-06-22

See git history for changes prior to the API/event rewrite.