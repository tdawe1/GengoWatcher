PYTHON := $(shell if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; else printf '%s' python3; fi)

.PHONY: build test coverage lint format run run-web run-web-only install-user

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

install-user:
	mkdir -p "$(HOME)/.local/bin"
	ln -sf "$(CURDIR)/bin/gengowatcher" "$(HOME)/.local/bin/gengowatcher"
	ln -sf "$(CURDIR)/bin/gengo-watcher" "$(HOME)/.local/bin/gengo-watcher"
	ln -sf "$(CURDIR)/bin/gengowatcher-browser-worker" "$(HOME)/.local/bin/gengowatcher-browser-worker"