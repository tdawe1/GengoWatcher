test:
	pytest

coverage:
	pytest --cov=.

lint:
	flake8 .

format:
	black .
