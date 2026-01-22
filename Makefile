test:
	.venv/bin/pytest

coverage:
	.venv/bin/pytest --cov=.

lint:
	.venv/bin/flake8 .

format:
	.venv/bin/black .

run:
	PYTHONPATH=src .venv/bin/python3 -m gengowatcher.main

run-web:
	PYTHONPATH=src .venv/bin/python3 -m gengowatcher.main --web

run-web-only:
	PYTHONPATH=src .venv/bin/python3 -m gengowatcher.main --web-only
