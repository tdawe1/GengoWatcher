# GengoWatcher Agent Guide

## Purpose
- This repository is a Python 3.11+ application for monitoring Gengo translation jobs.
- It has a Textual TUI, a FastAPI web API, optional browser-worker integration, persistent config/state files, and a large pytest suite.
- Main package: `src/gengowatcher/`
- Primary entrypoint: `src/gengowatcher/main.py`

## Repo Layout
- `src/gengowatcher/`: application code
- `src/gengowatcher/browser_worker/`: long-lived Playwright sidecar and related flows
- `tests/`: pytest suite
- `scripts/`: operational and analysis scripts
- `assets/`: static media such as alert sounds and screenshots
- `config.toml`: primary runtime config file
- `state.json`: persisted app state
- `Makefile`: convenience commands, but see the virtualenv note below

## Agent Rule Sources
- No repository-local Cursor rules were found in `.cursor/rules/`.
- No `.cursorrules` file was found.
- No Copilot instructions were found in `.github/copilot-instructions.md`.
- This `AGENTS.md` is the primary agent instruction file in this repo.

## Python Environment
- Declared in `pyproject.toml`: `requires-python = ">=3.11"`
- Dev dependencies are listed in `requirements-dev.txt`.
- Core runtime dependencies include Textual, FastAPI, aiohttp, websockets, Playwright, Pydantic, and Prometheus client.

## Setup Commands
- Create a virtualenv: `python3 -m venv .venv`
- Activate it: `source .venv/bin/activate`
- Install dev dependencies: `pip install -r requirements-dev.txt`
- Install package editable: `pip install -e .`

## Run Commands
- Run the TUI app: `PYTHONPATH=src python3 -m gengowatcher.main`
- Run TUI + web server: `PYTHONPATH=src python3 -m gengowatcher.main --web`
- Run web server only: `PYTHONPATH=src python3 -m gengowatcher.main --web-only`
- Configure missing runtime settings: `PYTHONPATH=src python3 -m gengowatcher.main --configure`
- Start browser worker directly:
  `PYTHONPATH=src python3 -m gengowatcher.browser_worker.main --profile-path profiles/browser-worker --socket-path /tmp/gengowatcher-browser-worker.sock`

## Build, Lint, Format, Test
- Syntax/build check mirrored from `Makefile`:
  `python3 -m py_compile src/gengowatcher/*.py tests/*.py scripts/*.py`
- Run tests: `python3 -m pytest`
- Run coverage: `python3 -m pytest --cov=.`
- Run lint: `python3 -m flake8 .`
- Auto-format: `python3 -m black .`
- Format check only: `python3 -m black --check .`

## Single-Test Commands
- Run one file: `python3 -m pytest tests/test_browser_worker_profile.py -q`
- Run one test: `python3 -m pytest tests/test_config.py::test_config_creates_default_file -q`
- Run tests by pattern: `python3 -m pytest -k browser_session -q`
- Collect tests without running: `python3 -m pytest --collect-only tests/test_config.py -q`

## Makefile Notes
- `Makefile` defines `build`, `test`, `coverage`, `lint`, `format`, `run`, `run-web`, and `run-web-only`.
- Those targets use `.venv/bin/python -m ...` when available and fall back to `python3`.
- This avoids the stale shebang issue in checked-in console scripts like `.venv/bin/pytest` and `.venv/bin/flake8`.
- `build` is declared `.PHONY`; there is also a `build/` directory in the repo, so avoid target/file name collisions when adding future make targets.

## Current Test Status Notes
- Focused tests do run, for example:
  `python3 -m pytest tests/test_config.py::test_config_creates_default_file -q`
  and `python3 -m pytest tests/test_browser_worker_profile.py -q`
- `python3 -m pytest tests/test_main.py -q` also passes after restoring the metrics startup helper expected by that test file.
- The full suite was not re-run end-to-end after that targeted fix.
- Do not assume unrelated failures are caused by your change; inspect the specific failing area first.

## Formatting Rules
- Black is configured in `pyproject.toml` with line length `88`.
- Flake8 and pycodestyle are configured in `setup.cfg` with line length `88` and `E203` ignored.
- Format with Black before making broad edits.
- Avoid manual alignment or formatting that fights Black.

## Import Style
- Group imports in the usual order: standard library, third-party, then local package imports.
- Separate import groups with a single blank line.
- Use parenthesized multi-line imports when needed, as in `main.py` and `watcher.py`.
- There is no `isort` configuration; do not churn import order unless you are touching the imports anyway.

## Typing Conventions
- Type hints are expected for public functions and are common in internal helpers too.
- The codebase is in a mixed state:
  newer modules use `from __future__ import annotations`, built-in generics, and `X | None`;
  older modules still use `typing.Optional`, `Dict`, and `List`.
- Prefer modern built-in generics and union syntax in new code.
- When editing an older file, keep style locally consistent unless you are already refactoring that area.
- Use lightweight dataclasses where the code already does so, e.g. `browser_worker/models.py`.
- Pydantic models use v2-style `@field_validator` in `web.py`.

## Naming Conventions
- Classes: `PascalCase`
- Functions and methods: `snake_case`
- Variables and module-level helpers: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private/internal helpers: leading underscore, e.g. `_start_web_server_if_requested`
- Test names follow `test_<behavior>` and are usually explicit, sentence-like snake_case.

## Code Organization
- Prefer small helper functions for parsing, coercion, or lifecycle boundaries.
- Keep CLI concerns in `cli.py` and startup/runtime orchestration in `runtime.py` and `main.py`.
- Shared mutable state is usually protected with `threading.Lock` or `threading.RLock`.
- Async workflows often bridge blocking code with `asyncio.to_thread()`.
- State and config persistence prefer atomic write patterns over in-place mutation of files.

## Error Handling
- Catch specific exceptions where the failure mode is known.
- Broad `except Exception` blocks exist at application boundaries, startup paths, UI loops, and optional integrations.
- If you catch broadly, either log with context or convert to a user-facing error with a clear fallback.
- Use `logger.exception(...)` when preserving traceback matters.
- Use `logger.warning(...)` or `logger.error(...)` for recoverable operational issues.
- Avoid silent exception swallowing unless the code intentionally degrades gracefully.

## Logging Conventions
- Most modules receive or create a `logging.Logger` and log through it.
- Logging is important in this project; operational visibility matters.
- Prefer concise, actionable log messages with enough context to debug failures.
- User-facing terminal messaging may also use `rich.console.Console` in CLI/runtime paths.
- Avoid adding noisy logs in hot paths unless they are gated by existing debug categories.

## Config and State Conventions
- `config.toml` is the canonical config file.
- `config.ini` is legacy and is migrated by `AppConfig` if present.
- Placeholder secrets are explicitly tracked in config handling; do not treat them as real values.
- Use `pathlib.Path` for filesystem paths where practical.
- Preserve atomic write behavior when touching config or state persistence code.

## Testing Conventions
- Test runner: `pytest`
- Async tests use `pytest.mark.asyncio`.
- Tests heavily use `unittest.mock`, especially `MagicMock`, `AsyncMock`, and `patch`.
- Common fixtures live in `tests/conftest.py`.
- `tmp_path`, `monkeypatch`, and patch-based isolation are standard patterns.
- Keep new tests targeted; prefer one focused file or one focused test during iteration.
- Many tests assume `src` is importable via `tests/conftest.py` path injection.

## When Editing Code
- Make the smallest correct change.
- Match the surrounding file's style before introducing newer patterns.
- Do not modernize unrelated legacy typing or formatting in the same diff unless needed.
- Preserve thread-safety and async boundaries.
- Be careful around watcher lifecycle, web server startup, and browser-worker coordination.
- If you touch CLI/runtime wiring, run at least one focused test plus a syntax check.

## Suggested Validation After Changes
- For config changes: `python3 -m pytest tests/test_config.py -q`
- For browser worker profile changes: `python3 -m pytest tests/test_browser_worker_profile.py -q`
- For browser session changes: `python3 -m pytest tests/test_browser_session.py -q`
- For runtime/main changes: run the targeted file or test first, then inspect for existing collection failures.
- For broad Python edits: `python3 -m py_compile src/gengowatcher/*.py tests/*.py scripts/*.py`

## Known Agent Gotchas
- Avoid calling `.venv/bin/pytest`, `.venv/bin/black`, or `.venv/bin/flake8` directly in this workspace; their shebangs may be stale even when `.venv/bin/python` itself works.
- This repo mixes TUI, web, threads, asyncio, and optional browser automation; avoid assuming a change is isolated if it touches shared watcher state.
- Optional dependencies and runtime-only integrations are sometimes guarded with `try/except ImportError`; preserve those guards when editing related modules.
