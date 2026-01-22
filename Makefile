test:
	pytest

coverage:
	pytest --cov=.

lint:
	flake8 .

format:
	black .

run:
	PYTHONPATH=src .venv/bin/python3 -m gengowatcher.main

run-web:
	PYTHONPATH=src .venv/bin/python3 -m gengowatcher.main --web

run-web-only:
	PYTHONPATH=src .venv/bin/python3 -m gengowatcher.main --web-only
