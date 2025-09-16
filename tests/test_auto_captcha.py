import asyncio
import time
import logging
import pytest

from typing import Optional, Dict

from gengowatcher.job_acceptance import JobAcceptanceEngine
from gengowatcher.captcha_solver import CaptchaSolution
from gengowatcher.captcha_manager import CaptchaSolverManager


class DummyConfig:
    """Minimal config stub for JobAcceptanceEngine."""

    def __init__(self, enabled: bool = True):
        self._enabled = enabled

    def get(self, section: str, key: str):
        if section == "AutoAccept" and key == "enabled":
            return self._enabled
        # Defaults used by JobAcceptanceEngine where needed
        if section == "AutoAccept" and key == "accept_delay_min":
            return 0
        if section == "AutoAccept" and key == "accept_delay_max":
            return 0
        if section == "AutoAccept" and key == "job_sources":
            return "rss,websocket"
        if section == "AutoAccept" and key in ("min_reward", "max_reward"):
            return 0 if key == "min_reward" else 999999
        if section == "Captcha" and key == "skip_on_v3_extraction_failure":
            return False
        if section == "Captcha" and key == "recaptcha_v3_fallback_site_key":
            return "6Lc6BAAAAAAAAAChqR2QwNcAAAAA"
        if section == "Captcha" and key == "recaptcha_v3_default_action":
            return "job_acceptance"
        return None

    def getboolean(self, section: str, key: str):
        """Get boolean config value."""
        value = self.get(section, key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)


class FakeResponse:
    def __init__(self, status: int = 200, body: str = "accepted"):
        self.status = status
        self._body = body

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self, status: int = 200, body: str = "accepted"):
        self.status = status
        self.body = body
        self.closed = False

    async def close(self):
        self.closed = True

    # Only post is used by _handle_captcha_challenge
    def post(self, url: str, headers: Optional[Dict] = None, data: Optional[Dict] = None, timeout: int = 30):
        return FakeResponse(status=self.status, body=self.body)


class FakeCaptchaSolverManager:
    def __init__(self):
        self.calls = []

    def is_configured(self) -> bool:
        return True

    def solve_recaptcha_v2(self, site_key: str, page_url: str, **kwargs) -> Optional[CaptchaSolution]:
        self.calls.append(("recaptcha_v2", site_key, page_url))
        return CaptchaSolution(captcha_id="1", solution="TOKEN_V2", solved_at=time.time())

    def solve_hcaptcha(self, site_key: str, page_url: str, **kwargs) -> Optional[CaptchaSolution]:
        self.calls.append(("hcaptcha", site_key, page_url))
        return CaptchaSolution(captcha_id="2", solution="TOKEN_H", solved_at=time.time())

    def solve_recaptcha_v3(self, site_key: str, page_url: str, action: str = "verify", **kwargs) -> Optional[CaptchaSolution]:
        self.calls.append(("recaptcha_v3", site_key, page_url, action))
        return CaptchaSolution(captcha_id="3", solution="TOKEN_V3", solved_at=time.time())


@pytest.mark.asyncio
async def test_handle_captcha_recaptcha_v2_success():
    logger = logging.getLogger("test")
    engine = JobAcceptanceEngine(config=DummyConfig(True), logger=logger, captcha_solver=FakeCaptchaSolverManager())
    engine.session = FakeSession(status=200, body="accepted")

    html = "<html><body><div class='g-recaptcha' data-sitekey='SITEKEY123'></div></body></html>"

    ok = await engine._handle_captcha_challenge("job123", html, headers={})
    assert ok is True

    # Verify correct call was made
    assert engine.captcha_solver.calls and engine.captcha_solver.calls[0][0] == "recaptcha_v2"
    assert engine.captcha_solver.calls[0][1] == "SITEKEY123"


@pytest.mark.asyncio
async def test_handle_captcha_hcaptcha_success():
    logger = logging.getLogger("test")
    engine = JobAcceptanceEngine(config=DummyConfig(True), logger=logger, captcha_solver=FakeCaptchaSolverManager())
    engine.session = FakeSession(status=200, body="accepted")

    html = "<html><body><div class='h-captcha' data-sitekey='HSITEKEY456'></div></body></html>"

    ok = await engine._handle_captcha_challenge("job456", html, headers={})
    assert ok is True
    assert engine.captcha_solver.calls and engine.captcha_solver.calls[0][0] == "hcaptcha"
    assert engine.captcha_solver.calls[0][1] == "HSITEKEY456"


@pytest.mark.asyncio
async def test_handle_captcha_recaptcha_v3_success():
    logger = logging.getLogger("test")
    engine = JobAcceptanceEngine(config=DummyConfig(True), logger=logger, captcha_solver=FakeCaptchaSolverManager())
    engine.session = FakeSession(status=200, body="accepted")

    # Presence of recaptcha script should trigger v3 path
    html = """<html><head>
        <script src='https://www.google.com/recaptcha/api.js'></script>
        <script>
            grecaptcha.execute('6Lc6BAAAAAAAAAChqR2QwNcAAAAA', {action: 'job_acceptance'});
        </script>
    </head><body></body></html>"""

    ok = await engine._handle_captcha_challenge("job789", html, headers={})
    assert ok is True
    assert engine.captcha_solver.calls and engine.captcha_solver.calls[0][0] == "recaptcha_v3"
    # Placeholder site key is used in implementation; just ensure it was invoked


@pytest.mark.asyncio
async def test_handle_captcha_solver_not_configured_returns_false():
    logger = logging.getLogger("test")
    engine = JobAcceptanceEngine(config=DummyConfig(True), logger=logger, captcha_solver=None)
    engine.session = FakeSession(status=200, body="accepted")
    html = "<html><body><div class='g-recaptcha' data-sitekey='SITEKEY123'></div></body></html>"

    ok = await engine._handle_captcha_challenge("job000", html, headers={})
    assert ok is False


@pytest.mark.asyncio
async def test_handle_captcha_solver_failure_returns_false():
    logger = logging.getLogger("test")

    class FailingSolver(FakeCaptchaSolverManager):
        def solve_recaptcha_v2(self, site_key: str, page_url: str, **kwargs):
            self.calls.append(("recaptcha_v2", site_key, page_url))
            return None

    engine = JobAcceptanceEngine(config=DummyConfig(True), logger=logger, captcha_solver=FailingSolver())
    engine.session = FakeSession(status=200, body="accepted")
    html = "<html><body><div class='g-recaptcha' data-sitekey='SITEKEY123'></div></body></html>"

    ok = await engine._handle_captcha_challenge("job001", html, headers={})
    assert ok is False


def test_captcha_manager_handle_job_rejection_success(monkeypatch):
    # Prepare config and logger
    config = {"Captcha": {"service": "2captcha", "max_retries": 1, "retry_delay": 0}}
    logger = logging.getLogger("test")

    # Patch SecureKeyStorage to avoid real storage
    class FakeStorage:
        def __init__(self, logger=None, storage_file=None):
            pass

        def retrieve_api_key(self, service: str):
            return "FAKE-KEY"

    monkeypatch.setattr("gengowatcher.captcha_manager.SecureKeyStorage", FakeStorage)

    manager = CaptchaSolverManager(config, logger)

    # Replace underlying solver with a stub
    class StubSolver:
        def get_balance(self):
            return 1.0

        def close(self):
            pass

        def solve_recaptcha_v2(self, site_key, page_url, **kwargs):
            return CaptchaSolution(captcha_id="t", solution="TOKEN", solved_at=time.time())

        def solve_recaptcha_v3(self, site_key, page_url, action, **kwargs):
            return CaptchaSolution(captcha_id="t3", solution="TOKEN3", solved_at=time.time())

        def solve_hcaptcha(self, site_key, page_url, **kwargs):
            return CaptchaSolution(captcha_id="h", solution="HTOKEN", solved_at=time.time())

    manager.solver = StubSolver()

    submitted = {}

    def fake_submit(job_data, solution):
        submitted["job"] = job_data
        submitted["solution"] = solution.solution

    monkeypatch.setattr(manager, "_submit_captcha_solution", fake_submit)

    job = {
        "id": "jobX",
        "rejection_reason": "captcha required",
        "captcha_type": "recaptcha_v2",
        "site_key": "SITE",
        "page_url": "https://example.com"
    }

    assert manager.handle_job_rejection(job) is True
    assert submitted["job"]["id"] == "jobX"
    assert submitted["solution"] == "TOKEN"
