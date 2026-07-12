# Formatting and Style

## Formatting and Lint
- Black: configured in pyproject.toml (line-length = 88, excludes .worktrees/). setup.cfg no longer exists, so flake8/pycodestyle are not project-configured here.
- Format with Black before broad edits. Avoid manual alignment that fights Black.
- Imports: stdlib, third-party, then local gengowatcher.*; one blank line between groups; parenthesized multi-line imports are normal in main.py and watcher.py. There is no isort config; do not churn import order unless you are touching imports anyway.

## Typing Conventions
- Type hints are expected on public functions and common in helpers.
- The codebase is mixed: newer modules use from __future__ import annotations, built-in generics, and X | None; older modules still use typing.Optional, Dict, List.
- Prefer modern syntax in new code; match local style when editing older files.
- Use lightweight dataclasses where the code already does (browser_worker/models.py).
- Pydantic v2 @field_validator style is used in web.py/web_models.py.

## Naming Conventions
- Classes: PascalCase. Functions/methods/variables: snake_case. Constants: UPPER_SNAKE_CASE. Private helpers: leading underscore (e.g. _start_web_server_if_requested).
- Test names follow test_<behavior> and read like sentences in snake_case.
