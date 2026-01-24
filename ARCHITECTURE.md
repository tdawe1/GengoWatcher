# GengoWatcher Architecture

## Overview
- GengoWatcher is a Python TUI application that monitors Gengo jobs via RSS + WebSocket, alerts users, and can auto-accept jobs with CAPTCHA solving and browser automation fallback.
- An optional FastAPI web server exposes status/jobs/config endpoints and serves a React dashboard build.

## Tech Stack
| Area | Tech | Notes | Key Paths |
| --- | --- | --- | --- |
| Core app | Python 3.8+ | TUI, watcher, job acceptance, CAPTCHA | `src/gengowatcher/` |
| TUI | Textual + Rich | Terminal UI and logging | `src/gengowatcher/ui_textual.py`, `src/gengowatcher/main.py` |
| Web API | FastAPI + Uvicorn | REST + WebSocket status | `src/gengowatcher/web.py` |
| Frontend | Vite + React + TS | Builds to static web UI | `frontend/` -> `static/web/` |
| Tests | pytest + Vitest | Python and frontend tests | `tests/`, `frontend/src/` |

## Directory Structure
```
src/
  gengowatcher/
    main.py                # CLI entry; wires config/state/watcher/TUI
    watcher.py             # RSS/WebSocket monitoring + job processing
    web.py                 # FastAPI web API + WS status
    config.py              # config.ini defaults + load/save/validation
    state.py               # state.json persistence + job history
    job_acceptance.py      # auto-accept orchestration + CAPTCHA
    captcha_manager.py     # CAPTCHA solver plugins + monitoring
    job_cancellation_manager.py # cancel current job for higher value
frontend/
  src/                     # React app (login/dashboard)
  vite.config.ts           # Vite build config -> static/web
static/web/                # Built frontend assets
template-source/           # Legacy template dashboard source
tests/                     # pytest coverage for watcher/config/TUI
assets/                    # screenshots and shared assets
config.ini                 # runtime configuration (user-specific)
monitoring_config.json     # monitoring config example
```

## Core Components
- **CLI boot + TUI** (`src/gengowatcher/main.py`): parses flags, loads config/state, starts watcher + Textual UI, optionally spawns web server thread.
- **Watcher** (`src/gengowatcher/watcher.py`): central orchestrator; spawns RSS/WebSocket/email/website monitors, dedupes jobs, triggers notifications, auto-accept, cancellation, and state persistence.
- **Configuration** (`src/gengowatcher/config.py`): default config template, type-coerced getters, config repair, auto-accept validation, and persistence.
- **State** (`src/gengowatcher/state.py`): persists `state.json`, stores job history, and caps in-memory job lists.
- **Auto-Accept** (`src/gengowatcher/job_acceptance.py`): eligibility checks, rate limiting, retry flow, HTTP + Selenium attempts, CAPTCHA solving.
- **CAPTCHA** (`src/gengowatcher/captcha_manager.py`): service initialization, retries, stats, monitoring/alerts.
- **Web API** (`src/gengowatcher/web.py`): FastAPI endpoints for status/jobs/config/commands + WebSocket status stream; also serves `static/web`.
- **Frontend** (`frontend/src/`): React UI using API endpoints; compiled assets in `static/web/`.

## Data Flow
- **Startup**: `main.py` -> `AppConfig` -> `AppState` -> `GengoWatcher` -> TUI loop + watcher thread.
- **RSS**: `watcher._run_rss_monitor()` -> `fetch_rss()` -> `_process_feed_entries()` -> `_process_new_job()` -> `state.add_job()` -> `state.save_state()`.
- **WebSocket**: `watcher._run_websocket_monitor()` -> `_websocket_logic()` -> message parsing -> `_process_new_job()`.
- **Auto-accept**: `_process_new_job()` -> `job_acceptance_engine.is_job_eligible()` -> async acceptance -> CAPTCHA solver + HTTP/Selenium attempts -> acceptance logs.
- **Cancellation**: `_process_new_job()` -> `JobCancellationManager.should_cancel_for_job()` -> cancellation flow + persisted stats.
- **Web API**: `web.py` creates separate watcher instance -> endpoints read `AppState` and watcher status -> `/ws/status` pushes updates.

## External Integrations
- **Gengo RSS + WebSocket**: RSS feed parsing via `feedparser`, WebSocket via `websockets`.
- **CAPTCHA providers**: 2Captcha, Anti-Captcha, local solver (see `src/gengowatcher/captcha_manager.py`).
- **Desktop notifications/sounds**: `notify-send`, `paplay`/`aplay` via `src/gengowatcher/notifier.py`.
- **Browser automation**: Selenium/Playwright fallback for acceptance (see `src/gengowatcher/browser_automation.py`).

## Configuration
- Primary config file: `config.ini` (created/updated by `AppConfig` in `src/gengowatcher/config.py`).
- Example configs: `config_high_value.ini`, `monitoring_config.json`, `docs/example_config_with_autoaccept.ini`.
- Web API auth token stored under `[WebServer] auth_token` in `config.ini` (auto-generated if placeholder).

## Build & Deploy
- **Python**:
  - Run: `make run` or `PYTHONPATH=src .venv/bin/python3 -m gengowatcher.main`
  - Tests: `make test` or `pytest`
  - Lint/format: `make lint`, `make format`
- **Frontend**:
  - Dev: `cd frontend && npm install && npm run dev`
  - Build: `cd frontend && npm run build` (outputs to `static/web`)
  - Tests: `cd frontend && npm test`
