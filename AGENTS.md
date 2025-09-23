# Repository Guidelines

## Project Structure & Module Organization
- Backend lives in `src/gengowatcher/`; launch locally with `python -m gengowatcher.main [--web | --web-only]`.
- Tests sit in `tests/` and `src/tests/` for unit and targeted module suites; keep fixtures nearby.
- Frontend code is under `frontend/` (Vite + React + TS); assets and shared examples live in `assets/` and `scripts/` respectively.

## Build, Test, and Development Commands
- `make test` runs the pytest suite; `make coverage` extends it with coverage reporting.
- `make lint` / `make format` wrap flake8 and black so Python style stays consistent.
- Frontend workflow: `cd frontend && npm i` once, then `npm run dev` for local dev, `npm run test[:coverage]` for vitest, and `npm run build && npm run preview` for production smoke tests.

## Coding Style & Naming Conventions
- Python follows Black defaults (line length 88) and flake8 with `E203,W503` ignored; use 4-space indents and type hints on new or edited symbols.
- Naming: modules/functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`; keep modules single-purpose.
- Prefer succinct comments explaining non-obvious logic; avoid committing generated artifacts or large binaries.

## Testing Guidelines
- Use `pytest` and `pytest-cov`; full check: `pytest -v --cov=. --cov-report=term-missing tests/ src/tests/`.
- Name tests `test_<feature>.py`; mark integration cases with `-m integration` to scope runs.
- Maintain ≥80% overall coverage and ≥85% for CAPTCHA components before opening a PR.

## Commit & Pull Request Guidelines
- Follow Conventional Commits (`feat:`, `fix:`, `chore:`, etc.); keep messages scoped to one change set.
- PRs should explain the motivation, link issues, list test evidence, and attach UI before/after media for `frontend/` changes.
- Ensure CI passes; update docs or README when behavior or configuration changes.

## Security & Configuration Tips
- Never commit secrets; `config.ini` is ignored—keep local copies only.
- API keys are stored encrypted by the app; do not log or print them.
- Exclude logs and bulky assets from commits; review dependencies for licensing before adding.
