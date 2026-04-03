PYTHON := $(shell if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; else printf '%s' python3; fi)

.PHONY: build test coverage lint format run run-web run-web-only

build:
	@echo "Compiling Python files..."
	$(PYTHON) -m py_compile src/gengowatcher/*.py
	$(PYTHON) -m py_compile tests/*.py
	$(PYTHON) -m py_compile scripts/*.py
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
