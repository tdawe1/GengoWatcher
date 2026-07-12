# Overview

## Purpose
- Python 3.11+ application for monitoring Gengo translation jobs.
- A Textual TUI, a FastAPI web API, optional browser-worker integration, persistent config/state files, and a large pytest suite.
- Main package: src/gengowatcher/ (entrypoint src/gengowatcher/main.py).
- Current version: 2.9.3 (see pyproject.toml).

## Repo Layout
- `src/gengowatcher/`: stable package entrypoints and shared application services.
- `src/gengowatcher/orchestration/`: internal watcher lifecycle, monitor, feed, session-sync, and job-processing components used by `watcher.py`.
- src/gengowatcher/browser_worker/: long-lived Playwright sidecar (main.py, client.py, coordinator.py, flows/, models.py, profile.py, protocol.py, registry.py, runtime.py, tabs.py, telemetry.py).
- tests/: pytest suite (~62 files). Shared fixtures in tests/conftest.py; binary fixtures in tests/fixtures/; helpers in tests/helpers/.
- scripts/: operational and analysis scripts (not part of the installed package).
- assets/: static media (alert sounds, icons, screenshots, UI SVGs).
- docs/: design docs (websocket-contract.md, prometheus-setup.md, SECURITY_REMEDIATION.md, browser-worker-black-box-test-procedure.md, plans/). Agent topic files live in docs/agents/.
- profiles/: local browser profile directories (gitignored; do not commit contents).
- config.toml: primary runtime config. config.toml.example is the template. config.ini is legacy and migrated by AppConfig if present. state.json holds persisted app state. config.toml.lock is a runtime artifact.
- Makefile: convenience commands. bin/: launcher shell scripts symlinked by make install-user.
- data/, logs/, ops/, server-files/: runtime/output directories.

## Agent Rule Sources
- No repository-local Cursor rules (.cursor/rules/) or .cursorrules were found.
- No .github/copilot-instructions.md was found.
- AGENTS.md is the primary agent instruction file in this repo; topic files in docs/agents/ hold the detail.
