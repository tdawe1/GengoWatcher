import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gengowatcher.config import AppConfig
from gengowatcher.state import AppState
from gengowatcher.watcher import GengoWatcher


@pytest.mark.asyncio
async def test_browser_worker_client_emits_job_url_command(tmp_path):
    from gengowatcher.browser_worker.client import BrowserWorkerClient

    socket_path = tmp_path / "browser-worker.sock"
    received: dict[str, object] = {}

    async def handle_client(reader, writer):
        received.update(json.loads((await reader.readline()).decode("utf-8")))
        writer.write(b'{"ok": true}\n')
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(handle_client, path=str(socket_path))
    try:
        client = BrowserWorkerClient(socket_path=socket_path)
        payload = client.build_job_url_command(
            "https://gengo.com/t/jobs/details/123?src=rss",
            "rss",
        )

        assert payload["type"] == "job_url"
        assert payload["source"] == "rss"

        response = await client.send_command(payload)

        assert response["ok"] is True
        assert received["url"] == "https://gengo.com/t/jobs/details/123"
    finally:
        server.close()
        await server.wait_closed()


def test_browser_worker_client_includes_auth_token_in_command(tmp_path):
    from gengowatcher.browser_worker.client import BrowserWorkerClient

    client = BrowserWorkerClient(
        socket_path=tmp_path / "browser-worker.sock",
        auth_token="secret-token",
    )

    payload = client.build_job_url_command(
        "https://gengo.com/t/jobs/details/123",
        "rss",
    )

    assert payload["auth_token"] == "secret-token"


@pytest.fixture
def watcher_deps():
    config = MagicMock(spec=AppConfig)
    state = MagicMock(spec=AppState)
    state.seen_job_ids = []
    state.total_new_entries_found = 0
    state.add_job = MagicMock()
    state.save_state = MagicMock()

    config_data = {
        "Watcher": {"min_reward": 0.0},
        "Logging": {"log_all_entries_enabled": False},
        "AutoAccept": {
            "enabled": True,
            "job_sources": "rss,websocket",
            "min_reward": 0.0,
            "max_reward": 999999.0,
        },
        "BrowserWorker": {
            "enabled": True,
            "socket_path": "/tmp/gengowatcher.sock",
        },
        "Cancellation": {
            "enabled": True,
            "min_improvement_ratio": 2.0,
            "extreme_threshold": 1000.0,
            "auto_cancel_extreme_value": True,
        },
        "RateLimit": {"max_acceptances_per_hour": 30},
        "WebSocket": {
            "user_session": "session",
            "user_id": "123",
            "user_key": "key",
        },
        "Network": {},
    }

    def get_value(section, key, fallback=None):
        return config_data.get(section, {}).get(key, fallback)

    config.get.side_effect = get_value
    config.getboolean.side_effect = lambda section, key, fallback=None: bool(
        get_value(section, key, fallback)
    )
    config.getfloat.side_effect = lambda section, key, fallback=None: float(
        get_value(section, key, fallback)
    )
    config.getint.side_effect = lambda section, key, fallback=None: int(
        get_value(section, key, fallback)
    )
    config.config = config_data
    config.list_all.return_value = config_data
    return config, state


@pytest.mark.asyncio
async def test_browser_worker_client_times_out_waiting_for_response(tmp_path):
    from gengowatcher.browser_worker.client import BrowserWorkerClient

    socket_path = tmp_path / "browser-worker.sock"

    async def handle_client(reader, writer):
        await reader.readline()
        await asyncio.sleep(0.05)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(handle_client, path=str(socket_path))
    try:
        client = BrowserWorkerClient(socket_path=socket_path, response_timeout=0.01)
        with pytest.raises(RuntimeError, match="timed out"):
            await client.send_command({"type": "job_url"})
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_submit_job_works_inside_running_event_loop(tmp_path):
    from gengowatcher.browser_worker.client import BrowserWorkerClient

    client = BrowserWorkerClient(socket_path=tmp_path / "browser-worker.sock")
    received: dict[str, object] = {}

    async def fake_send_command(payload):
        received.update(payload)
        return {"ok": True}

    client.send_command = fake_send_command

    response = client.submit_job("https://gengo.com/t/jobs/details/123", "rss")

    assert response == {"ok": True}
    assert received["url"] == "https://gengo.com/t/jobs/details/123"


@pytest.mark.asyncio
async def test_submit_job_async_works_inside_running_event_loop(tmp_path):
    from gengowatcher.browser_worker.client import BrowserWorkerClient

    client = BrowserWorkerClient(socket_path=tmp_path / "browser-worker.sock")
    client.send_command = AsyncMock(return_value={"ok": True})

    response = await client.submit_job_async(
        "https://gengo.com/t/jobs/details/123",
        "rss",
    )

    assert response == {"ok": True}
    client.send_command.assert_awaited_once()


def test_watcher_routes_eligible_job_to_browser_worker(watcher_deps):
    logger = logging.getLogger("test_browser_worker_client")
    config, state = watcher_deps

    watcher = GengoWatcher(config=config, state=state, logger=logger)
    watcher.show_notification = MagicMock()
    watcher.browser_worker_client = MagicMock()
    watcher.browser_worker_client.submit_job = MagicMock(return_value={"ok": True})
    watcher.job_acceptance_engine.is_job_eligible = MagicMock(return_value=True)
    watcher.cancellation_manager.should_cancel_for_job = MagicMock(return_value=True)

    with patch("gengowatcher.watcher.threading.Thread") as thread_cls:
        watcher._process_new_job(
            123,
            "Test Job",
            25.0,
            "https://gengo.com/t/jobs/details/123",
            "rss",
        )

    watcher.browser_worker_client.submit_job.assert_called_once()
    thread_cls.assert_not_called()


def test_watcher_falls_back_to_standard_acceptance_when_browser_worker_submit_fails():
    logger = logging.getLogger("test_browser_worker_client_fallback")
    config = MagicMock(spec=AppConfig)
    state = MagicMock(spec=AppState)
    state.seen_job_ids = []
    state.total_new_entries_found = 0
    state.add_job = MagicMock()
    state.save_state = MagicMock()

    config_data = {
        "Watcher": {"min_reward": 0.0},
        "Logging": {"log_all_entries_enabled": False},
        "AutoAccept": {
            "enabled": True,
            "job_sources": "rss,websocket",
            "min_reward": 0.0,
            "max_reward": 999999.0,
        },
        "BrowserWorker": {
            "enabled": True,
            "socket_path": "/tmp/gengowatcher.sock",
        },
        "Cancellation": {
            "enabled": True,
            "min_improvement_ratio": 2.0,
            "extreme_threshold": 1000.0,
            "auto_cancel_extreme_value": True,
        },
        "RateLimit": {"max_acceptances_per_hour": 30},
        "WebSocket": {
            "user_session": "session",
            "user_id": "123",
            "user_key": "key",
        },
        "Network": {},
    }

    def get_value(section, key, fallback=None):
        return config_data.get(section, {}).get(key, fallback)

    config.get.side_effect = get_value
    config.getboolean.side_effect = lambda section, key, fallback=None: bool(
        get_value(section, key, fallback)
    )
    config.getfloat.side_effect = lambda section, key, fallback=None: float(
        get_value(section, key, fallback)
    )
    config.getint.side_effect = lambda section, key, fallback=None: int(
        get_value(section, key, fallback)
    )
    config.config = config_data
    config.list_all.return_value = config_data

    watcher = GengoWatcher(config=config, state=state, logger=logger)
    watcher.show_notification = MagicMock()
    watcher.browser_worker_client = MagicMock()
    watcher.browser_worker_client.submit_job = MagicMock(
        side_effect=RuntimeError("boom")
    )
    watcher.job_acceptance_engine.is_job_eligible = MagicMock(return_value=True)
    watcher.cancellation_manager.should_cancel_for_job = MagicMock(return_value=False)

    with patch("gengowatcher.watcher.threading.Thread") as thread_cls:
        watcher._process_new_job(
            123,
            "Test Job",
            25.0,
            "https://gengo.com/t/jobs/details/123",
            "rss",
        )

    watcher.browser_worker_client.submit_job.assert_called_once()
    thread_cls.assert_called_once()
