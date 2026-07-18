# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment and commands

GengoWatcher requires Python 3.11+. The default TUI is the Rust/Ratatui client, so normal full-app development also requires Rust/Cargo.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
```

The Makefile uses `.venv/bin/python` when available and otherwise `python3`:

```bash
make build              # compileall over src/gengowatcher, tests, and scripts
make test               # full pytest suite
make coverage           # pytest --cov=.
make lint               # flake8
make format             # black (line length 88)
python -m black --check .
python -m build         # wheel and sdist

make build-ratatui      # release build
make test-ratatui       # cargo test, then clippy with warnings denied
```

Run focused Python tests during iteration:

```bash
python -m pytest tests/test_state.py -q
python -m pytest tests/test_state.py::test_save_and_load_state -q
python -m pytest -k browser_session -q
```

`pytest.ini` discovers `tests/test_*.py`. Real-browser E2E tests are opt-in:

```bash
GENGOWATCHER_RUN_BROWSER_E2E=1 \
GENGOWATCHER_BROWSER_EXECUTABLE=/usr/bin/chromium \
PYTHONPATH=src python -m pytest tests/e2e/test_gengo_sandbox_browser.py -q
```

Run the application and its major components:

```bash
make run                # Ratatui when available, else Textual
make run-textual        # legacy in-process Textual TUI
make run-web-only       # FastAPI and watcher, no TUI
make run-web            # TUI plus web API

PYTHONPATH=src python -m gengowatcher.gengo_sandbox.main
PYTHONPATH=src python -m gengowatcher.browser_worker.main \
  --profile-path profiles/browser-worker \
  --socket-path /tmp/gengowatcher-browser-worker.sock

cargo run --manifest-path prototypes/garden-ratatui/Cargo.toml -- --demo
```

For direct live Ratatui development, start Python with `--web-only`, read `[WebServer].auth_token` from `config.toml`, and provide it as `GENGOWATCHER_API_TOKEN` to `cargo run`. Do not pass the token as a CLI argument.

There is no configured semantic type checker. `make build`/`py_compile` are syntax checks, not type checking. The repository has no Cursor rules or Copilot instruction file; `AGENTS.md` contains additional style guidance, but prefer current Makefile and configuration behavior if it conflicts.

## Architecture

### Runtime topology

`main.py` is deliberately thin: it parses CLI/config-only commands and delegates full startup to `runtime.py`. `runtime.run_application()` creates the shared `AppConfig`, `AppState`, and `GengoWatcher`, optionally starts Prometheus and FastAPI, starts `watcher.run()` in a daemon thread, then runs Textual in-process or Ratatui as a subprocess. Installed console entrypoints call `main.run()`, which changes to the repository root so runtime-relative paths resolve consistently.

`GengoWatcher` in `watcher.py` is the central coordinator. It owns shutdown/check events and launches independent monitor threads for RSS, WebSocket, optional email, native-browser observation, browser-job inspection, and browser-worker telemetry. All discovery sources converge on `_process_new_job()`, which performs deduplication and reward filtering, inserts state, emits notifications/API/webhook events, evaluates cancellation, selects browser-worker or HTTP acceptance, and persists results. Preserve locking and thread/async boundaries when changing this path.

### State and events

`AppState` is the durable shared read model. It maintains bounded job/seen-ID collections and indexes collection, order, and sub-job identifiers. Browser observations may create or enrich a row before RSS/WebSocket discovery, so merging must preserve known non-empty metadata.

Native-browser data follows this pipeline:

```text
NativeBrowserListener -> bounded native-event queue -> StateProjector
                      -> AppState mutation -> canonical job.* event bus
```

The critical acceptance invariant is that visibility or workbench details do **not** prove acceptance. Only `browser.workbench.start_response` may mark and emit `job.accepted` in `state_projector.py`.

`event_bus.py` isolates hot monitoring paths from consumers with bounded queues, nonblocking publication, short bounded waits for critical events, and status-event coalescing. Slow TUI/API consumers should drop events rather than stall browser or watcher threads. `TuiStore` is a compact event-derived read model for the Textual render loop, not the source of truth.

### UI and API boundaries

The Textual UI receives direct watcher/config/state/stats references and runs inside the Python process. The Ratatui client under `prototypes/garden-ratatui/` is intentionally out of process: Python retains watcher, browser, and persistence logic, while Rust consumes the authenticated loopback FastAPI API. It is selected automatically when available; packaged Python-only installs fall back to Textual. Ratatui startup requires the API even when `--web` was not explicitly supplied.

`WebAPI` wraps the same watcher/state in combined mode; in web-only mode it starts the watcher itself. Do not introduce a second watcher in combined TUI/API execution. Watcher callbacks feed bounded API event history and thread-safe WebSocket broadcasts. REST endpoints use bearer auth; `/ws/status` uses its configured API-key handshake.

### Browser boundaries

The native Firefox listener and the Playwright browser worker are separate integrations. Native mode is the default; Playwright browser-worker operation in native mode requires explicit `Browser.allow_playwright=true`. The deprecated `WebsiteMonitor` is disabled with the native backend.

The browser worker is a separate asyncio process using a persistent Chromium profile and a newline-delimited JSON Unix socket. `BrowserWorkerClient` sends job intents; accepted workbench data returns through append-only `worker.jsonl` telemetry that the watcher tails. URL canonicalization restricts navigation to trusted Gengo origins or an explicitly configured loopback sandbox origin. Preserve socket authorization, origin checks, profile locking, and single-accept coordination.

`gengo_sandbox/` is a loopback-only reconstructed Gengo service for deterministic RSS, WebSocket, browser acceptance, and workbench testing. Its production-facing escape hatch requires both sides to opt into the exact sandbox origin; do not weaken that boundary.

### Persistence and privacy

`config.toml` is canonical; `config.ini` is legacy migration input. Config and state use locks and atomic replacement. Preserve file permission handling and placeholder-secret detection.

`state.json` intentionally strips raw workbench payloads, source text, accepted source text, and segments during persistence while keeping them in memory for active workflows. Outbound webhooks similarly omit customer content unless explicitly configured. Other durable stores include `stats.json`, cancellation state, CSV history, webhook JSONL audit, browser-worker artifacts, and uploaded-file metadata; preserve path-containment and atomic-write checks around them.
