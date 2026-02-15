# scripts/

# scripts/

## Responsibility
- Host standalone CLI utilities that exercise, validate, and analyze GengoWatcher subsystems without touching the main TUI (e.g., `web_server.py`).
- Aggregate operational telemetry (`import_historical_data.py`, `analyze_logs.py`) and capture safety/quality signals (`monitor_captcha_safety.py`, `validate_captcha_implementation.py`).
- Provide exploratory/test runners for WebSocket interactions, cancellation flows, and critical acceptance scenarios (`test_ws_connection.py`, `websocket_scaler.py`, `demo_cancellation_workflow.py`, `run_critical_tests.py`, etc.).
- Ship investigative tooling for pattern analysis, rate-limit research, and autopilot safety experiments that inform decisions before production changes (`analyze_gengo_patterns.py`, `analyze_logs.py`).

## Design Patterns
- CLI-first scripts: each entry point has a `main()` (or equivalent) that parses args, configures logging, and calls a single well-scoped helper class.
- Data pipelines: `import_historical_data.py` chains CSV/log parsers → deduplication → stats aggregation → JSON output, mirroring ETL stages.
- Observer/monitor loops: `websocket_scaler.py` wraps WebSocket coroutines in `ThreadPoolExecutor`s, while `monitor_captcha_safety.py` maintains time-windowed stats with locking and threshold callbacks.
- Async watchers: `analyze_gengo_patterns.py` and `test_ws_connection*.py` rely on `asyncio`/`websockets` to maintain long-lived feeds, collect events, and then hand data to synchronous analysis routines.
- Validation wrappers: lightweight scripts (`validate_captcha_implementation.py`, various `test_*.py`) reuse config/environment data to assert expected modules, docs, or behavioral contracts.

## Data & Control Flow
- Historical import: iterate CSV files + globbed logs, parse each row/line, normalize timestamps/rewards, dedupe by job ID/link, build aggregates (hourly/daily/language), then emit `stats.json` summary.
- Live analysis: connect to the live dashboard via credentials in `AppConfig`, stream `available_collection` payloads, log job metadata, compute intervals/reward distributions, persist JSON reports, and surface acceptance/captcha recommendations (`analyze_gengo_patterns.py`).
- WebSocket utilities: `websocket_scaler.py` spins up `WebSocketWorker`s in threads, authenticates via cookies, logs job notices, and offers manual scaling/status back to the CLI.
- Safety monitoring: `monitor_captcha_safety.py` logs every CAPTCHA attempt (success/failure, cost, latency), updates hourly/daily buckets under a lock, and fires alerts when thresholds trigger; `run_critical_tests.py`/`test_*.py` mimic high-value jobs or cancellation flows to exercise these thresholds.
- Validation/test scripts coordinate with `AppConfig` or environment variables to hit real endpoints (`web_server.py` for UI, `test_ws_connection_v2.py` for websocket reconnection logic, etc.).

## Integration Points
- `AppConfig`/`AppState` from `src` power the WebSocket analyzers and scaler, so scripts anchor on the same INI-backed settings as the main application.
- Output and logs live under `logs/`, `archives/`, `stats.json`, and `analysis/` directories, meaning scripts serve as both producers and consumers of the same persisted telemetry the core services rely on.
- WebSocket helpers talk to `wss://live-dashboard.gengo.com` using the same cookies/payload shape as `src/gengowatcher/websocket.py`, making them natural playgrounds for manual debugging.
- Validation tooling (`validate_captcha_implementation.py`) and safe automation demos reference docs in `docs/` and modules under `src/gengowatcher/captcha`, linking repository documentation with implementation readiness.
- Test scripts also depend on external services (Gengo API, captcha solvers) and expect credential/config tokens provided through `config.ini` or environment variables, so they sit at the boundary between local experimentation and production readiness.
