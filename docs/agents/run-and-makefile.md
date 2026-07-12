# Run and Makefile

## Run Commands
- TUI app: PYTHONPATH=src python3 -m gengowatcher.main
- TUI + web server: PYTHONPATH=src python3 -m gengowatcher.main --web
- Web server only: PYTHONPATH=src python3 -m gengowatcher.main --web-only
- Configure missing runtime settings: PYTHONPATH=src python3 -m gengowatcher.main --configure
- Print or set a config value: PYTHONPATH=src python3 -m gengowatcher.main --set <Section> <key> <value>
- Start browser worker directly: PYTHONPATH=src python3 -m gengowatcher.browser_worker.main --profile-path profiles/browser-worker --socket-path /tmp/gengowatcher-browser-worker.sock
- Install user-facing launchers: make install-user (symlinks bin/gengowatcher, bin/gengo-watcher, bin/gengowatcher-browser-worker into ~/.local/bin).

## Makefile Targets
- build: python -m compileall -q src/gengowatcher tests scripts.
- test: python -m pytest (uses pytest.ini testpaths = tests).
- coverage: python -m pytest --cov=.
- lint: python -m flake8 .
- format: python -m black .
- run, run-web, run-web-only: as above with PYTHONPATH=src.
- firefox-debug-bootstrap: writes browser-debug settings into config.toml and starts Firefox in remote-debug mode.
- firefox-debug: runs the bootstrap then launches the TUI.
- Tunables: FIREFOX_DEBUG_URL, FIREFOX_DEBUG_BROWSER, FIREFOX_DEBUG_PROFILE, FIREFOX_DEBUG_SEED_PROFILE, FIREFOX_DEBUG_AUTO_LAUNCH.
- All targets resolve PYTHON to .venv/bin/python when present, otherwise python3. Avoid calling .venv/bin/pytest, .venv/bin/black, or .venv/bin/flake8 directly; their shebangs may be stale.
