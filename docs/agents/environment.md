# Environment

## Python Version
- Declared in pyproject.toml: requires-python = ">=3.11".
- Dev dependencies: requirements-dev.txt (pytest, pytest-cov, pytest-asyncio, black, flake8).
- Runtime deps include Textual, FastAPI, uvicorn, aiohttp, websockets, Pydantic, Playwright, play-stealth, feedparser, rich, prometheus-client, textual-plotext, imapclient, cryptography, requests, python-multipart.

## Setup Commands
- Create a virtualenv: python3 -m venv .venv
- Activate it: source .venv/bin/activate
- Install dev deps: pip install -r requirements-dev.txt
- Install package editable: pip install -e .
