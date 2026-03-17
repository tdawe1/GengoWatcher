test:
	.venv/bin/pytest

coverage:
	.venv/bin/pytest --cov=.

lint:
	.venv/bin/flake8 .

format:
	.venv/bin/black .

install:
	.venv/bin/pip install -e .

install-user:
	mkdir -p "$(HOME)/.local/bin"
	ln -snf "$(CURDIR)/bin/gengowatcher" "$(HOME)/.local/bin/gengowatcher"

run:
	./bin/gengowatcher

run-web:
	PYTHONPATH=src .venv/bin/python3 -m gengowatcher.main --web

run-web-only:
	PYTHONPATH=src .venv/bin/python3 -m gengowatcher.main --web-only
