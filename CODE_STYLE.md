# GengoWatcher Code Style

## Naming Conventions
- **Python files**: `snake_case.py` (examples: `job_acceptance.py`, `captcha_manager.py`).
- **Python classes**: `CamelCase` (examples: `GengoWatcher`, `AppConfig`, `JobAcceptanceEngine`).
- **Python functions/vars**: `snake_case` (examples: `fetch_rss`, `session_new_entries`).
- **Constants**: `UPPER_SNAKE_CASE` (examples: `DEFAULT_CONFIG`, `PLACEHOLDER_CONFIG_VALUES`).
- **CSS classes**: `kebab-case` in `.tcss` files (examples: `.metric-card`, `.status-indicator`).

## File Organization
- Core runtime logic lives under `src/gengowatcher/` with modules grouped by domain:
  - Config/state: `src/gengowatcher/config.py`, `src/gengowatcher/state.py`, `src/gengowatcher/stats.py`
  - Watcher + monitors: `src/gengowatcher/watcher.py`, `src/gengowatcher/email_monitor.py`, `src/gengowatcher/website_monitor.py`
  - Automation/acceptance: `src/gengowatcher/job_acceptance.py`, `src/gengowatcher/captcha_manager.py`
  - Web API: `src/gengowatcher/web.py`
  - TUI: `src/gengowatcher/ui_textual.py`, `src/gengowatcher/main.py`, `src/gengowatcher/gengo_watcher.tcss`
- Tests are under `tests/` (pytest).

## Import Style
- Standard library imports first, then third-party, then local module imports.
- Local imports use relative package imports inside `src/gengowatcher/` (example: `from .config import AppConfig` in `src/gengowatcher/main.py`).

## Code Patterns
- **Config access**: Use `AppConfig.get*` helpers for typed access (see `src/gengowatcher/config.py`).
- **Threading + async**: Monitors are threads, async tasks are wrapped in new event loops (see `src/gengowatcher/watcher.py`).
- **State persistence**: Write JSON atomically via temp file + `os.replace` (see `src/gengowatcher/state.py`).
- **Logging**: Prefer `logger.info/debug/warning/error` over `print` in core runtime (see `src/gengowatcher/watcher.py`).
- **TUI widgets**: Inherit from Textual base classes, use `compose()` for layout, CSS classes for styling.

## Error Handling
- Guard external IO with try/except and log errors without crashing loops (examples: `fetch_rss`, `_websocket_logic` in `src/gengowatcher/watcher.py`).
- Web API endpoints return HTTP errors via `HTTPException` (see `src/gengowatcher/web.py`).
- Config parsing errors exit early with clear messaging (see `src/gengowatcher/config.py`).

## Logging
- Logging categories and filters in `src/gengowatcher/main.py` (`CategoryFilter`, `UILoggingHandler`).
- Log redaction: WebSocket headers mask sensitive tokens (see `src/gengowatcher/watcher.py`).
- CSV logging is optional and guarded by config (see `src/gengowatcher/watcher.py`).
- TUI debug tab shows color-coded logs via `TextualLogHandler`.

## Testing
- **pytest**: fixtures + mocks, parametric tests for parsing logic (see `tests/test_watcher.py`).
- **TUI tests**: use mocked watcher/config/state with `app.run_test()` async context (`tests/test_ui_tabs.py`).
- **Config tests**: use temp directories and patched `sys.exit` (`tests/test_config.py`).

## Linters & Formatters
- **Python**: Black + Flake8 (see `Makefile`, `.flake8`).
- Max line length: 88 for Python (`.flake8`).

## Do's and Don'ts
- **Do** use `AppConfig` getters for typed values (`src/gengowatcher/config.py`).
- **Do** log errors instead of swallowing exceptions silently.
- **Do** keep state writes atomic (`src/gengowatcher/state.py`).
- **Do** use Textual CSS classes for TUI styling instead of inline styles.
- **Don't** commit live secrets in `config.ini` or `monitoring_config.json` (see `AGENTS.md`).
- **Don't** edit `state.json`, `stats.json`, or `src/logs/` in commits (runtime data).
