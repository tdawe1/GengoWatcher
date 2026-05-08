PYTHON := $(shell if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; else printf '%s' python3; fi)
FIREFOX_DEBUG_URL ?= ws://127.0.0.1:9222
FIREFOX_DEBUG_BROWSER ?= firefox
FIREFOX_DEBUG_PROFILE ?= profiles/firefox-debug
FIREFOX_DEBUG_SEED_PROFILE ?=
FIREFOX_DEBUG_AUTO_LAUNCH ?= true

.PHONY: build test coverage lint format run run-web run-web-only firefox-debug firefox-debug-bootstrap install-user

build:
	@echo "Compiling Python files..."
	$(PYTHON) -m compileall -q src/gengowatcher tests scripts
	@echo "Build successful!"

test:
	$(PYTHON) -m pytest

coverage:
	$(PYTHON) -m pytest --cov=.

lint:
	$(PYTHON) -m flake8 .

format:
	$(PYTHON) -m black .

run:
	PYTHONPATH=src $(PYTHON) -m gengowatcher.main

run-web:
	PYTHONPATH=src $(PYTHON) -m gengowatcher.main --web

run-web-only:
	PYTHONPATH=src $(PYTHON) -m gengowatcher.main --web-only

firefox-debug-bootstrap:
	PYTHONPATH=src $(PYTHON) -m gengowatcher.main --set WebSocket browser_debug_url "$(FIREFOX_DEBUG_URL)"
	PYTHONPATH=src $(PYTHON) -m gengowatcher.main --set Paths browser_debug_browser_path "$(FIREFOX_DEBUG_BROWSER)"
	PYTHONPATH=src $(PYTHON) -m gengowatcher.main --set WebSocket browser_debug_profile_path "$(FIREFOX_DEBUG_PROFILE)"
	if [ -n "$(FIREFOX_DEBUG_SEED_PROFILE)" ]; then PYTHONPATH=src $(PYTHON) -m gengowatcher.main --set WebSocket browser_debug_seed_profile_path "$(FIREFOX_DEBUG_SEED_PROFILE)"; fi
	PYTHONPATH=src $(PYTHON) -m gengowatcher.main --set WebSocket browser_debug_auto_launch "$(FIREFOX_DEBUG_AUTO_LAUNCH)"
	PYTHONPATH=src $(PYTHON) -m gengowatcher.main --start-firefox-debug

firefox-debug: firefox-debug-bootstrap
	PYTHONPATH=src $(PYTHON) -m gengowatcher.main

install-user:
	mkdir -p "$(HOME)/.local/bin"
	ln -sf "$(CURDIR)/bin/gengowatcher" "$(HOME)/.local/bin/gengowatcher"
	ln -sf "$(CURDIR)/bin/gengo-watcher" "$(HOME)/.local/bin/gengo-watcher"
	ln -sf "$(CURDIR)/bin/gengowatcher-browser-worker" "$(HOME)/.local/bin/gengowatcher-browser-worker"
