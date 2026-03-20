from unittest.mock import AsyncMock

import pytest

from gengowatcher.browser_worker.runtime import BrowserRuntime, BrowserRuntimeConfig
from gengowatcher.browser_worker.telemetry import BrowserWorkerTelemetry
from gengowatcher.browser_worker.protocol import decode_message


def test_runtime_defaults_to_headed_mode(tmp_path):
    config = BrowserRuntimeConfig(profile_path=tmp_path / "profile")

    assert config.headless is False


def test_runtime_uses_default_socket_path_inside_tmp(tmp_path):
    config = BrowserRuntimeConfig(profile_path=tmp_path / "profile")

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


class _DummyReader:
    def __init__(self, payload: bytes):
        self._payload = payload

    async def readline(self) -> bytes:
        return self._payload


class _DummyWriter:
    def __init__(self):
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, payload: bytes) -> None:
        self.writes.append(payload)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_runtime_handle_client_returns_error_and_closes_writer(tmp_path):
    runtime = BrowserRuntime(
        config=BrowserRuntimeConfig(profile_path=tmp_path / "profile")
    )
    runtime.handle_command = AsyncMock(side_effect=RuntimeError("boom"))
    reader = _DummyReader(
        b'{"type":"job_url","url":"https://gengo.com/t/jobs/details/123","source":"rss"}\n'
    )
    writer = _DummyWriter()

    await runtime.handle_client(reader, writer)

    assert writer.closed is True
    response = decode_message(writer.writes[0])
    assert response["ok"] is False
    assert response["error"] == "boom"


def test_decode_message_reports_invalid_json_payload():
    with pytest.raises(ValueError, match="invalid browser worker message payload"):
        decode_message(b"{not json}\n")
