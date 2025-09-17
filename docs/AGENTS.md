# Repository Guidelines

## Project Structure & Module Organization
- `src/gengowatcher/` — main Python package (TUI, watcher, CAPTCHA, WebSocket, browser automation).
- `tests/` — primary pytest suite; a few legacy tests exist at repo root and `src/tests/`.
- `assets/` — images and static assets; `logs/` — runtime logs (gitignored by default).
- `docs/` — design notes and feature summaries; `scripts/` — utility/validation scripts.
- Entry point to run locally: `python -m gengowatcher.main`.

## Build, Test, and Development Commands
- `make test` — run pytest.
- `make coverage` — run pytest with coverage.
- `make lint` — run flake8.
- `make format` — run black.
- Example: `pytest -s -v tests/` to focus on repo test suite.

## Coding Style & Naming Conventions
- Python 3.10+; auto-format with `black` (line length 88). Lint with `flake8` (ignores `E203,W503`).
- Use type hints for new/modified code. Keep functions small and cohesive.
- Naming: modules/files `snake_case.py`, variables/functions `snake_case`, classes `CapWords`, constants `UPPER_CASE`.
- Logging: prefer structured, informative messages; avoid logging secrets.

## Testing Guidelines
- Framework: `pytest` (+ `pytest-asyncio` where needed).
- Location: place new tests under `tests/` using `test_*.py` naming.
- Aim to cover new logic and edge cases; keep tests deterministic and fast.
- Run locally with `make test` and `make coverage` before pushing.

## Commit & Pull Request Guidelines
- Follow Conventional Commits: `feat:`, `fix:`, `chore:`, `perf:`, `docs:` …
- Commits should be scoped and descriptive; include rationale when non-obvious.
- PRs should include: summary, linked issues, test evidence (output or coverage), and screenshots for TUI changes.
- Update `README.md`/`CHANGELOG.md` when user-facing behavior changes. Ensure CI passes.

## Security & Configuration Tips
- Do not commit secrets or real tokens. `config.ini` is gitignored; use placeholders in examples.
- Sensitive keys are managed via secure storage; never hardcode or print them.
- Keep logs sanitized; avoid writing PII/API keys to `logs/`.

## Agent-Specific Notes
- Make minimal, focused diffs; avoid unrelated refactors.
- Prefer `make` targets for consistency; keep style checks green.
- Reflect existing patterns in `src/gengowatcher/*` and add tests alongside changes.
