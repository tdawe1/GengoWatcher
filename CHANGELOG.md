# Changelog

All notable changes to GengoWatcher are documented in this file.
This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [3.0.0] - 2026-07-18

### Added
- A native Ratatui interface covering live watcher status, available jobs,
  workflow, history, analytics, service health, and API events.
- Authenticated loopback API polling with reconnect and backoff handling.
- Ratatui actions for immediate checks, pause/resume, accepting or ignoring a
  selected job, and cancelling active work. Destructive actions require
  confirmation.
- Keyboard and mouse workspace navigation, compact terminal layouts, and a
  Kanagawa Dragon-inspired colour scheme.
- Deterministic demo/render modes and SVG previews for interface development.
- Cargo build, test, run, and install commands in the Makefile.
- A loopback-only Gengo sandbox with captured job, RSS, WebSocket, acceptance,
  workbench, CAT-service, and versioned persistence primitives for deterministic
  testing.
- Opt-in real-browser coverage that exercises the production browser-worker
  acceptance flow against the local sandbox.
- Repository guidance in `CLAUDE.md` covering development commands, runtime
  topology, state/event flow, browser boundaries, and persistence invariants.

### Changed
- Ratatui is now the preferred terminal interface when a `gengowatcher-tui`
  binary is available. The Python runtime starts the authenticated loopback API
  and launches it automatically; Python-only installs fall back to Textual.
  `gengowatcher --tui ratatui` may compile through Cargo when no binary exists.
- The existing Textual interface remains available through `--tui textual`.
- API status responses now expose the watcher's paused state.
- Browser-worker command validation now supports an explicitly configured,
  exact-match loopback sandbox origin while preserving production Gengo URL
  restrictions.
- Browser-worker acceptance tracking captures and normalizes accepted workbench
  payloads for the watcher telemetry path.
- Python dependencies are locked in `uv.lock` for reproducible environments.
- `make coverage` sets `PYTHONPATH=src`. `make lint` and `make format`
  include `prototypes/`.

### Fixed
- Web-only mode now starts the shared watcher thread. Combined TUI/API
  execution still avoids a second monitor loop.
- API startup no longer crashes with `UnboundLocalError` when generating a
  missing `[WebServer] auth_token` for a shared-watcher runtime.
- The repo `bin/gengowatcher` launcher sets `PYTHONPATH` to `src` when using
  `.venv`, so the package is importable without an editable install.
- RSS jobs that leave the live feed are marked `gone` instead of remaining
  available forever. The Ratatui client no longer treats `gone`,
  `unavailable`, or `missed` jobs as open listings.
- Manual accept through `/api/jobs/{id}/accept` now inspects
  `AcceptResult.success` instead of treating the result object as success.
  Gone or otherwise unavailable jobs are rejected with a 409 and a reason
  the TUI can display.
- The watcher now forwards `[BrowserWorker].sandbox_origin` into
  `BrowserWorkerClient`, so sandbox job URLs are canonicalized by the
  coordinator instead of rejected as unsupported hosts.
- Ratatui accept/cancel requests use a 20s timeout so they can outlive the
  default 12s acceptance attempt. Snapshot GETs stay on the 4s timeout.
- A dropped API connection clears a pending accept/cancel lock so `a`/`x`
  can be retried after reconnect.
- Dismissing the overview alert no longer suppresses banners for later
  newly available jobs.
- Automatic Ratatui selection no longer treats a source `Cargo.toml` plus
  `cargo` on PATH as “available”; that path is reserved for `--tui ratatui`.
- Sandbox `GET /t/workbench/{id}` no longer serves
  `__GENGO_WORKBENCH_DATA__` for still-available collections.

### Removed
### Security
- The Python launcher passes the API token through
  `GENGOWATCHER_API_TOKEN`, not through process arguments.
- The native client accepts plain HTTP API connections only on loopback
  addresses.
- Sandbox servers reject non-loopback binding unless explicitly acknowledged;
  browser connections enforce a matching loopback Origin.
- `BrowserRuntimeConfig.sandbox_origin` is validated and canonicalized at
  construction: only HTTP(S) loopback origins without credentials, path,
  query, or fragment are accepted.
- Sandbox `AtomicJSONStore` serializes load and write with an instance lock
  and suppresses `OSError` during temp-file cleanup so the original write
  failure is re-raised.

### Tests
- Added Python coverage for backend selection, Ratatui process lifecycle,
  loopback API startup, token forwarding, failures, and paused status.
- Added Rust coverage for API parsing, live-state updates, input handling,
  rendering, confirmation flows, and terminal-size variants.
- Added sandbox route, lifecycle, CAT-service, persistence, origin-validation,
  browser-worker protocol, and opt-in Chromium acceptance coverage.
- Added RSS feed-reconcile coverage, accept-result and gone-job API tests,
  sandbox-origin construction tests, and notify-send error-path tests.

## [2.9.4] - 2026-07-08

### Changed
- **BrowserJobs monitor is now event-driven** (`src/gengowatcher/watcher.py`).
  The old 1.5s fixed polling loop and the random `GENGO_BROWSER_BROWSE_URLS`
  navigation have been removed. The monitor now wakes from
  `_browser_jobs_refresh_event` on:
  - `job.visible` / `job.details` / `job.discovered` API events
    (emitted by the native browser listener and the WS / RSS / webhook paths);
  - explicit `trigger_browser_jobs_refresh()` calls from TUI commands or
    the WS monitor's sync-fallback path;
  - a long idle-cap keepalive (default 30 min, configurable via
    `[BrowserJobs].idle_cap_sec`) that runs a passive eval only — no
    navigation, no interaction.
- `config.toml.example` adds a `[BrowserJobs]` block with
  `allow_navigation = false` and `idle_cap_sec = 1800`. The random browse
  feature is still reachable for operators who explicitly set
  `allow_navigation = true`, but they no longer get unsolicited
  navigation of the live Firefox tab.
- New public API: `GengoWatcher.trigger_browser_jobs_refresh(reason=...)`
  for external producers that want to request a refresh.

### Tests
- `tests/test_browser_jobs_event_driven.py` — 4 new regression tests:
  no scrape without trigger inside idle_cap window, scrape after explicit
  trigger, keepalive scrape is passive (no browse_url, no force_refresh),
  triggered refresh respects `allow_navigation=false`.

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
