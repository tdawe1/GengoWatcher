import asyncio
import json
import logging
from unittest.mock import MagicMock

import pytest

from gengowatcher.websocket_monitor import GengoWebSocketMonitor


class _FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, section, key, fallback=None):
        return self.values.get((section, key), fallback)

    def getint(self, section, key, fallback=None):
        return int(self.values.get((section, key), fallback))

    def set(self, section, key, value):
        self.values[(section, key)] = value


class _FakeWebSocket:
    close_code = 1000
    close_reason = "done"

    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def send(self, payload):
        self.sent.append(payload)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)

    async def ping(self):
        future = asyncio.get_running_loop().create_future()
        future.set_result(None)
        return future


class _SlowClosingWebSocket(_FakeWebSocket):
    def __init__(self, messages):
        super().__init__(messages)
        self.close_event = asyncio.Event()

    async def __anext__(self):
        await self.close_event.wait()
        raise StopAsyncIteration


def test_session_rotation_replaces_stale_browser_cookies(monkeypatch):
    config = _FakeConfig(
        {
            ("WebSocket", "browser_debug_url"): "ws://127.0.0.1:6000",
            ("WebSocket", "user_session"): "old-token",
            ("WebSocket", "rd_session_id"): "old-rd",
        }
    )
    monitor = GengoWebSocketMonitor(
        config,
        MagicMock(),
        logging.getLogger("test.websocket_monitor.cookies"),
    )
    monitor._browser_cookies = [{"name": "old", "value": "cookie"}]
    snapshot = MagicMock(
        session_token="new-token",
        rd_session_id="new-rd",
        user_agent="",
        accept_language="",
        cookies=[{"name": "new", "value": "cookie"}],
    )
    monkeypatch.setattr(
        "gengowatcher.websocket_monitor.fetch_browser_session_snapshot_sync",
        lambda _url: snapshot,
    )

    assert monitor._sync_session_from_browser() is True
    assert monitor._browser_cookies == [{"name": "new", "value": "cookie"}]


def test_session_rotation_clears_stale_cookies_without_replacement(monkeypatch):
    config = _FakeConfig(
        {
            ("WebSocket", "browser_debug_url"): "ws://127.0.0.1:6000",
            ("WebSocket", "user_session"): "old-token",
            ("WebSocket", "rd_session_id"): "old-rd",
        }
    )
    monitor = GengoWebSocketMonitor(
        config,
        MagicMock(),
        logging.getLogger("test.websocket_monitor.cookies"),
    )
    monitor._browser_cookies = [{"name": "old", "value": "cookie"}]
    snapshot = MagicMock(
        session_token="new-token",
        rd_session_id="new-rd",
        user_agent="",
        accept_language="",
        cookies=[],
    )
    monkeypatch.setattr(
        "gengowatcher.websocket_monitor.fetch_browser_session_snapshot_sync",
        lambda _url: snapshot,
    )

    assert monitor._sync_session_from_browser() is True
    assert monitor._browser_cookies == []


@pytest.mark.asyncio
async def test_websocket_monitor_receives_messages_and_dispatches_job():
    job_events = []
    all_events = []
    websocket = _FakeWebSocket(
        [
            json.dumps(
                {
                    "type": "available_collection",
                    "collection": {
                        "id": "123",
                        "lc_src": "ja",
                        "lc_tgt": "en",
                        "rewards": 8.5,
                    },
                }
            )
        ]
    )
    monitor = GengoWebSocketMonitor(
        _FakeConfig(
            {
                ("WebSocket", "wss_url"): "ws://example.test/socket",
                ("WebSocket", "user_id"): "user-1",
                ("WebSocket", "user_session"): "session-token",
                ("WebSocket", "user_key"): "key-1",
            }
        ),
        MagicMock(),
        logging.getLogger("test.websocket_monitor"),
        on_job_received=job_events.append,
        on_event=all_events.append,
    )
    monitor._connect = lambda *_args, **_kwargs: websocket

    await monitor._websocket_session()

    assert websocket.sent == [
        json.dumps(
            {"userId": "user-1", "sessionToken": "session-token", "userKey": "key-1"}
        )
    ]
    assert job_events == [{"id": "123", "lc_src": "ja", "lc_tgt": "en", "rewards": 8.5}]
    assert all_events[0]["type"] == "available_collection"
    assert monitor.metrics.last_message_ts is not None


@pytest.mark.asyncio
async def test_websocket_monitor_noop_session_sync_is_not_failure():
    websocket = _SlowClosingWebSocket([])
    monitor = GengoWebSocketMonitor(
        _FakeConfig(
            {
                ("WebSocket", "wss_url"): "ws://example.test/socket",
                ("WebSocket", "user_id"): "user-1",
                ("WebSocket", "user_session"): "session-token",
                ("WebSocket", "user_key"): "real-user-key",
            }
        ),
        MagicMock(),
        logging.getLogger("test.websocket_monitor"),
    )
    monitor.HEARTBEAT_INTERVAL = 0
    monitor._connect = lambda *_args, **_kwargs: websocket
    sync_attempted = asyncio.Event()
    loop = asyncio.get_running_loop()

    def noop_sync():
        loop.call_soon_threadsafe(sync_attempted.set)
        return False

    monitor._sync_session_from_browser = noop_sync

    session_task = asyncio.create_task(monitor._websocket_session())
    await asyncio.wait_for(sync_attempted.wait(), timeout=1)
    websocket.close_event.set()
    await session_task

    assert monitor._websocket_sync_failed is False


@pytest.mark.asyncio
async def test_websocket_monitor_failed_session_sync_sets_hard_failure(monkeypatch):
    websocket = _SlowClosingWebSocket([])
    monitor = GengoWebSocketMonitor(
        _FakeConfig(
            {
                ("WebSocket", "wss_url"): "ws://example.test/socket",
                ("WebSocket", "user_id"): "user-1",
                ("WebSocket", "user_session"): "session-token",
                ("WebSocket", "user_key"): "real-user-key",
                ("WebSocket", "browser_debug_url"): "ws://127.0.0.1:6000",
                ("WebSocket", "session_sync_fail_hard"): True,
            }
        ),
        MagicMock(),
        logging.getLogger("test.websocket_monitor"),
    )
    monitor.HEARTBEAT_INTERVAL = 0
    monitor._connect = lambda *_args, **_kwargs: websocket
    sync_attempted = asyncio.Event()
    loop = asyncio.get_running_loop()

    def fail_snapshot(_debug_url):
        raise RuntimeError("browser unavailable")

    monkeypatch.setattr(
        "gengowatcher.websocket_monitor.fetch_browser_session_snapshot_sync",
        fail_snapshot,
    )
    original_sync = monitor._sync_session_from_browser

    def sync_and_signal():
        result = original_sync()
        loop.call_soon_threadsafe(sync_attempted.set)
        return result

    monitor._sync_session_from_browser = sync_and_signal

    session_task = asyncio.create_task(monitor._websocket_session())
    await asyncio.wait_for(sync_attempted.wait(), timeout=1)
    await session_task

    assert monitor._websocket_sync_failed is True
    assert monitor._websocket_sync_failure_reason == "browser unavailable"
