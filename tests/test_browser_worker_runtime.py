from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from gengowatcher.browser_worker.runtime import BrowserRuntime, BrowserRuntimeConfig
from gengowatcher.browser_worker.telemetry import BrowserWorkerTelemetry
from gengowatcher.browser_worker.runtime import BrowserRuntimeConfig


def test_runtime_defaults_to_headed_mode():
    config = BrowserRuntimeConfig(profile_path=Path("/tmp/profile"))

    assert config.headless is False


def test_runtime_uses_default_socket_path_inside_tmp():
    config = BrowserRuntimeConfig(profile_path=Path("/tmp/profile"))

    assert str(config.socket_path).endswith("gengowatcher-browser-worker.sock")


@pytest.mark.asyncio
async def test_runtime_handles_job_url_command_and_prepares_candidate(tmp_path):
    runtime = BrowserRuntime(
        config=BrowserRuntimeConfig(profile_path=tmp_path / "profile"),
        telemetry=BrowserWorkerTelemetry(tmp_path / "worker.jsonl"),
    )
    runtime.prepare_candidate = AsyncMock(
        return_value="https://gengo.com/t/jobs/details/123"
    )

    response = await runtime.handle_command(
        {
            "type": "job_url",
            "url": "https://gengo.com/t/jobs/details/123?src=rss",
            "source": "rss",
            "metadata": {"reward": 25.0},
        }
    )

    assert response == {
        "ok": True,
        "job_id": "123",
        "url": "https://gengo.com/t/jobs/details/123",
    }
    runtime.prepare_candidate.assert_awaited_once()
