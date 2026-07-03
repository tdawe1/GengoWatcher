import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from gengowatcher.browser_worker.runtime import (
    BrowserRuntime,
    BrowserRuntimeConfig,
    default_browser_worker_socket_dir,
)
from gengowatcher.browser_worker.telemetry import BrowserWorkerTelemetry
from gengowatcher.browser_worker.tabs import TabRoles


def test_runtime_defaults_to_headed_mode():
    config = BrowserRuntimeConfig(profile_path=Path("/tmp/profile"))

    assert config.headless is False


def test_runtime_uses_default_socket_path_inside_tmp():
    config = BrowserRuntimeConfig(profile_path=Path("/tmp/profile"))

    assert config.socket_path.parent == default_browser_worker_socket_dir()
    assert config.socket_path.parent.name.startswith("gengowatcher-browser-worker-")
    assert str(config.socket_path).endswith("gengowatcher-browser-worker.sock")


def test_prepare_socket_path_creates_private_runtime_dir(tmp_path):
    socket_path = tmp_path / "runtime" / "browser-worker.sock"
    runtime = BrowserRuntime(
        config=BrowserRuntimeConfig(
            profile_path=tmp_path / "profile",
            socket_path=socket_path,
        )
    )

    prepared_path = runtime._prepare_socket_path()

    assert prepared_path == socket_path
    assert oct(os.stat(socket_path.parent).st_mode & 0o777) == "0o700"


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


@pytest.mark.asyncio
async def test_runtime_rejects_command_with_invalid_auth_token(tmp_path):
    runtime = BrowserRuntime(
        config=BrowserRuntimeConfig(
            profile_path=tmp_path / "profile",
            auth_token="secret-token",
        ),
        telemetry=BrowserWorkerTelemetry(tmp_path / "worker.jsonl"),
    )

    with pytest.raises(PermissionError):
        await runtime.handle_command(
            {
                "type": "job_url",
                "url": "https://gengo.com/t/jobs/details/123",
                "source": "rss",
                "auth_token": "wrong-token",
            }
        )


@pytest.mark.asyncio
async def test_runtime_accepts_command_with_valid_auth_token(tmp_path):
    runtime = BrowserRuntime(
        config=BrowserRuntimeConfig(
            profile_path=tmp_path / "profile",
            auth_token="secret-token",
        ),
        telemetry=BrowserWorkerTelemetry(tmp_path / "worker.jsonl"),
    )
    runtime.prepare_candidate = AsyncMock(
        return_value="https://gengo.com/t/jobs/details/123"
    )

    response = await runtime.handle_command(
        {
            "type": "job_url",
            "url": "https://gengo.com/t/jobs/details/123",
            "source": "rss",
            "auth_token": "secret-token",
        }
    )

    assert response["ok"] is True


@pytest.mark.asyncio
async def test_runtime_tracks_manual_acceptance_when_requested(tmp_path):
    accepted_payload = {
        "source": "window.__GENGO_WORKBENCH_DATA__",
        "payload": {
            "summary": {
                "order_id": 123,
                "expire_time": 1782760306560,
                "seconds_left": 6344,
            },
            "jobs": [{"id": 98936958}],
        },
    }

    class FakePage:
        url = "https://gengo.com/t/workbench/123"

        async def wait_for_url(self, predicate, timeout):
            assert timeout == 180000
            assert predicate(self.url) is True

        async def evaluate(self, _script):
            return accepted_payload

    runtime = BrowserRuntime(
        config=BrowserRuntimeConfig(profile_path=tmp_path / "profile"),
        telemetry=BrowserWorkerTelemetry(tmp_path / "worker.jsonl"),
    )
    runtime.prepare_candidate = AsyncMock(
        return_value="https://gengo.com/t/jobs/details/123"
    )
    runtime.ensure_tabs = AsyncMock(
        return_value=TabRoles(hold_page=object(), candidate_page=FakePage())
    )

    response = await runtime.handle_command(
        {
            "type": "job_url",
            "url": "https://gengo.com/t/jobs/details/123",
            "source": "rss",
            "track_acceptance": True,
            "acceptance_timeout_ms": 180000,
        }
    )

    assert response["ok"] is True
    assert response["accepted"] is True
    assert response["workbench_url"] == "https://gengo.com/t/workbench/123"
    assert response["accepted_workbench"] == accepted_payload
    assert (tmp_path / "accepted-workbench-123.json").is_file()


@pytest.mark.asyncio
async def test_runtime_page_observer_captures_workbench_payload(tmp_path):
    accepted_payload = {
        "source": "window.__GENGO_WORKBENCH_DATA__",
        "payload": {
            "summary": {
                "order_id": 123,
                "expire_time": 1782760306560,
                "seconds_left": 6344,
            },
            "jobs": [{"id": 98936958}],
        },
    }

    class FakePage:
        url = "https://gengo.com/t/workbench/123"

        async def evaluate(self, _script):
            return accepted_payload

    class FakeContext:
        pages = [FakePage()]

    telemetry = BrowserWorkerTelemetry(tmp_path / "worker.jsonl")
    runtime = BrowserRuntime(
        config=BrowserRuntimeConfig(profile_path=tmp_path / "profile"),
        telemetry=telemetry,
    )
    runtime.context = FakeContext()

    await runtime._observe_browser_pages_once()
    await runtime._observe_browser_pages_once()

    log_text = (tmp_path / "worker.jsonl").read_text(encoding="utf-8")
    assert log_text.count("accepted_workbench_payload") == 1
    assert (tmp_path / "accepted-workbench-123.json").is_file()
