import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
