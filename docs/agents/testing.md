# Testing

## Runner
- Runner: pytest with pytest.ini (testpaths = tests, python_files = test_*.py).
- Async tests use pytest.mark.asyncio.
- Heavy use of unittest.mock (MagicMock, AsyncMock, patch).
- Standard fixtures: tmp_path, monkeypatch, and patch-based isolation. Shared fixtures in tests/conftest.py inject src onto sys.path.
- Keep new tests targeted; prefer one focused file or test during iteration.

## Single-Test Commands
- One file: python3 -m pytest tests/test_browser_worker_profile.py -q
- One test: python3 -m pytest tests/test_config.py::test_config_creates_default_file -q
- By pattern: python3 -m pytest -k browser_session -q
- Collect only: python3 -m pytest --collect-only tests/test_config.py -q

## Validation After Changes
- For config: python3 -m pytest tests/test_config.py -q
- For browser worker profile: python3 -m pytest tests/test_browser_worker_profile.py -q
- For browser session: python3 -m pytest tests/test_browser_session.py -q
- Broad syntax check after edits: python3 -m py_compile $(git ls-files '*.py')
