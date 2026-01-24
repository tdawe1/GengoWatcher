# Repository Guidelines

## Project Structure & Module Organization
- Core Python app lives in `src/gengowatcher/` (watcher, UI, job acceptance, CAPTCHA, browser automation). Entry point: `python -m gengowatcher.main`.
- Shared assets and sample configs: `assets/`, `config.ini`, `config_high_value.ini`, `monitoring_config.json`.
- Tests: `tests/` (pytest). Persistent runtime data is in `src/state.json` and `src/logs/`; avoid committing edited state.
- TUI stylesheet: `src/gengowatcher/gengo_watcher.tcss` (Kanagawa Wave theme).

## Build, Test, and Development Commands
- Python app: `python -m gengowatcher.main` (with config set up) to run locally.
- With web API: `python -m gengowatcher.main --web`
- Quality gates: `make lint` (flake8), `make format` (black), `make test` (pytest), `make coverage` (pytest with coverage).

## Coding Style & Naming Conventions
- Python: 4-space indent, prefer type hints for new code, keep functions short and log at info/debug instead of print. Run black + flake8 before pushing.
- Naming: `snake_case` for Python functions/vars, `CamelCase` for classes.
- TUI widgets follow Textual conventions with CSS classes for styling.

## Testing Guidelines
- Python: add/extend pytest cases in `tests/` near the feature (e.g., watcher logic in `test_watcher.py`). Use fixtures in `tests/conftest.py` instead of ad-hoc setup. Aim to cover error paths and backoff logic.
- TUI tests: use `app.run_test()` async context with mocked watcher/config/state.
- Frontend dashboard lives in `frontend/` (Vite/React + TypeScript). Static files are under `static/` and `template-source/`.

## Build, Test, and Development Commands
- Python app: `python -m gengowatcher.main` (with config set up) to run locally.
- Quality gates: `make lint` (flake8), `make format` (black), `make test` (pytest), `make coverage` (pytest with coverage).
- Frontend: `cd frontend && npm install && npm run dev` for local dev; `npm run build` for production bundle; `npm test` or `npm run test:coverage` for Vitest.

## Coding Style & Naming Conventions
- Python: 4-space indent, prefer type hints for new code, keep functions short and log at info/debug instead of print. Run black + flake8 before pushing.
- JavaScript/TypeScript: follow ESLint defaults in `frontend`, keep components small, use named exports when practical, and favor descriptive prop names.
- Naming: `snake_case` for Python functions/vars, `CamelCase` for classes, `kebab-case` for files in frontend routes/components when matching Vite conventions.

## Testing Guidelines
- Python: add/extend pytest cases in `tests/` near the feature (e.g., watcher logic in `test_watcher.py`). Use fixtures in `tests/conftest.py` instead of ad-hoc setup. Aim to cover error paths and backoff logic.
- Frontend: use Vitest + Testing Library; place specs next to components or in `__tests__` folders. Prefer deterministic tests over snapshot churn.
- Run relevant suites before opening a PR; include coverage for new logic where feasible.

## Commit & Pull Request Guidelines
- Commit style aligns with Conventional Commits seen in history (`feat:`, `fix:`, `chore:`, `docs:`, occasional uppercase `FEAT:`). Keep messages imperative and scoped.
- PRs should describe the change, risks, and test evidence (`make test`, `npm test`, screenshots for UI). Link issues when available and call out config/env changes (e.g., new `config.ini` keys).
- Avoid committing secrets or tokens (WebSocket session, API keys); use sample values in docs and configs.

## Security & Configuration Tips
- Never commit real `config.ini` secrets or `monitoring_config.json` with credentials. Use placeholders like `REPLACE_WITH_YOUR_SESSION_TOKEN`.
- If adding new integrations (WebSocket, CAPTCHA, browser automation), document required settings in `README.md` and add safe defaults to configs.
