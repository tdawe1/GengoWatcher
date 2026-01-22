# GengoWatcher Code Style

## Naming Conventions
- **Python files**: `snake_case.py` (examples: `job_acceptance.py`, `captcha_manager.py`).
- **Python classes**: `CamelCase` (examples: `GengoWatcher`, `AppConfig`, `JobAcceptanceEngine`).
- **Python functions/vars**: `snake_case` (examples: `fetch_rss`, `session_new_entries`).
- **Constants**: `UPPER_SNAKE_CASE` (examples: `DEFAULT_CONFIG`, `PLACEHOLDER_CONFIG_VALUES`).
- **Frontend**: React component files use `PascalCase.tsx` or `camelCase` per Vite defaults (see `frontend/src/`).

## File Organization
- Core runtime logic lives under `src/gengowatcher/` with modules grouped by domain:
  - Config/state: `src/gengowatcher/config.py`, `src/gengowatcher/state.py`
  - Watcher + monitors: `src/gengowatcher/watcher.py`, `src/gengowatcher/websocket_monitor.py` (if present)
  - Automation/acceptance: `src/gengowatcher/job_acceptance.py`, `src/gengowatcher/captcha_manager.py`
  - Web API: `src/gengowatcher/web.py`
  - TUI: `src/gengowatcher/ui_textual.py`, `src/gengowatcher/main.py`
- Frontend lives under `frontend/` and builds to `static/web/` via `frontend/vite.config.ts`.
- Tests are under `tests/` (pytest) and `frontend/src/**.test.tsx` (Vitest).

## Import Style
- Standard library imports first, then third-party, then local module imports.
- Local imports use relative package imports inside `src/gengowatcher/` (example: `from .config import AppConfig` in `src/gengowatcher/main.py`).
- Frontend uses ES module imports and named exports (see `frontend/eslint.config.js`).

## Code Patterns
- **Config access**: Use `AppConfig.get*` helpers for typed access (see `src/gengowatcher/config.py`).
- **Threading + async**: Monitors are threads, async tasks are wrapped in new event loops (see `src/gengowatcher/watcher.py`).
- **State persistence**: Write JSON atomically via temp file + `os.replace` (see `src/gengowatcher/state.py`).
- **Logging**: Prefer `logger.info/debug/warning/error` over `print` in core runtime (see `src/gengowatcher/watcher.py`).

## Error Handling
- Guard external IO with try/except and log errors without crashing loops (examples: `fetch_rss`, `_websocket_logic` in `src/gengowatcher/watcher.py`).
- Web API endpoints return HTTP errors via `HTTPException` (see `src/gengowatcher/web.py`).
- Config parsing errors exit early with clear messaging (see `src/gengowatcher/config.py`).

## Logging
- Logging categories and filters in `src/gengowatcher/main.py` (`CategoryFilter`, `UILoggingHandler`).
- Log redaction: WebSocket headers mask sensitive tokens (see `src/gengowatcher/watcher.py`).
- CSV logging is optional and guarded by config (see `src/gengowatcher/watcher.py`).

## Testing
- **pytest**: fixtures + mocks, parametric tests for parsing logic (see `tests/test_watcher.py`).
- **TUI tests**: use mocked watcher/config/state (`tests/test_ui.py`).
- **Config tests**: use temp directories and patched `sys.exit` (`tests/test_config.py`).
- **Frontend**: Vitest + Testing Library, setup file `frontend/src/test/setup.ts`.

## Linters & Formatters
- **Python**: Black + Flake8 (see `Makefile`, `.flake8`).
- **Frontend**: ESLint (see `frontend/eslint.config.js`).
- Max line length: 88 for Python (`.flake8`).

## Do's and Don'ts
- **Do** use `AppConfig` getters for typed values (`src/gengowatcher/config.py`).
- **Do** log errors instead of swallowing exceptions silently.
- **Do** keep state writes atomic (`src/gengowatcher/state.py`).
- **Don't** commit live secrets in `config.ini` or `monitoring_config.json` (see `AGENTS.md`).
- **Don't** edit `state.json` or `src/logs/` in commits (runtime data).
