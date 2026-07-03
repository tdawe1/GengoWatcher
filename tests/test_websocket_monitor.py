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
