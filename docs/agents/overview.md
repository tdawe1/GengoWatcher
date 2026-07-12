# Overview

## Purpose
- Python 3.11+ application for monitoring Gengo translation jobs.
- A Textual TUI, a FastAPI web API, optional browser-worker integration, persistent config/state files, and a large pytest suite.
- Main package: src/gengowatcher/ (entrypoint src/gengowatcher/main.py).
- Current version: 2.9.3 (see pyproject.toml).

## Repo Layout
- src/gengowatcher/: application code. watcher.py orchestrates the lifecycle; most heavy logic now lives in watcher_*.py helpers (watcher_io.py, watcher_feed.py, watcher_ws_monitor.py, watcher_ws_logic.py, watcher_ws_debug.py, watcher_job_processor.py, watcher_alerting.py, watcher_browser_jobs.py, watcher_firefox.py, watcher_session_sync.py, watcher_config_io.py, watcher_monitors.py, watcher_worker_events.py, watcher_user_feedback.py, watcher_monitor_status.py, watcher_orchestration_helpers.py, watcher_debug.py).
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
