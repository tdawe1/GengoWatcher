import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import aiohttp

from gengowatcher.job_acceptance import AcceptResult, JobAcceptanceEngine


@pytest.mark.asyncio
async def test_accept_job_stops_retries_when_captcha_required():
    """CAPTCHA challenge should terminate acceptance attempts immediately."""
    config = MagicMock()

    def getboolean(section, key, fallback=None):
        if (section, key) == ("AutoAccept", "enabled"):
            return True
        return fallback

    def getint(section, key, fallback=None):
        values = {
            ("RateLimit", "max_acceptances_per_hour"): 30,
            ("AutoAccept", "accept_delay_min"): 0,
            ("AutoAccept", "accept_delay_max"): 0,
        }
        return values.get((section, key), fallback)

    config.getboolean.side_effect = getboolean
    config.getint.side_effect = getint

    engine = JobAcceptanceEngine(config, logging.getLogger("test_job_acceptance"))
    engine.initialize_session = AsyncMock()
    engine._attempt_job_acceptance = AsyncMock(
        return_value=AcceptResult(
            success=False,
            path="http",
            reason="captcha_required",
            timings={},
        )
    )

    with patch("gengowatcher.job_acceptance.asyncio.sleep", new=AsyncMock()):
        accepted = await engine.accept_job({"id": "123", "source": "rss", "reward": 10})

    assert accepted is False
    assert engine._attempt_job_acceptance.await_count == 1


@pytest.mark.asyncio
async def test_initialize_session_uses_browser_like_user_agent():
    config = MagicMock()
    config.config = {"Network": {"browser_user_agent": "Helium Browser"}}
    config.get.side_effect = lambda section, key, fallback=None: {
        ("WebSocket", "user_session"): "session-token",
        ("WebSocket", "user_id"): "12345",
    }.get((section, key), fallback)

    def getboolean(section, key, fallback=None):
        if (section, key) == ("AutoAccept", "enabled"):
            return False
        return fallback

    def getint(section, key, fallback=None):
        if (section, key) == ("RateLimit", "max_acceptances_per_hour"):
            return 30
        return fallback

    config.getboolean.side_effect = getboolean
    config.getint.side_effect = getint

    engine = JobAcceptanceEngine(config, logging.getLogger("test_job_acceptance"))
    await engine.initialize_session()

    try:
        assert engine.session is not None
        assert engine.session.headers["User-Agent"] == "Helium Browser"
        headers = engine._build_request_headers()
        assert headers is not None
        assert headers["User-Agent"] == "Helium Browser"
    finally:
        if engine.session is not None:
            await engine.session.close()
