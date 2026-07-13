# Editing Guidelines and Gotchas

## When Editing Code
- Make the smallest correct change.
- Match the surrounding file's style before introducing newer patterns.
- Do not modernize unrelated legacy typing or formatting in the same diff.
- Preserve thread-safety and async boundaries.
- Be careful around watcher lifecycle, web server startup, and browser-worker coordination.
- If you touch CLI/runtime wiring, run at least one focused test plus a syntax check.

## Known Agent Gotchas
- Avoid calling .venv/bin/pytest, .venv/bin/black, or .venv/bin/flake8 directly; their shebangs may be stale even when .venv/bin/python works.
- The repo mixes TUI, web, threads, asyncio, and optional browser automation; assume shared state is touched whenever you change watcher, state, or browser-worker modules.
- Optional dependencies and runtime integrations are sometimes guarded with try/except ImportError; preserve those guards.
- The Makefile build target is .PHONY, but a build/ directory also exists in the repo; do not collide with it when adding future make targets.
- config.toml.lock and state.json are runtime artifacts; do not edit them by hand.
