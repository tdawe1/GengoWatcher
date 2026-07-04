import json

import pytest

import gengowatcher.websocket_server as websocket_server
from gengowatcher.websocket_server import GengoRealtimeGateway


class _FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, section, key, fallback=None):
        return self.values.get((section, key), fallback)


class _FakeGatewayWebSocket:
    def __init__(self, gateway):
        self.gateway = gateway
        self.sent = []
        self._sent_message = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def send(self, payload):
        self.sent.append(payload)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._sent_message:
            self.gateway._shutdown_event.set()
            raise StopAsyncIteration
        self._sent_message = True
        return json.dumps(
            {
                "type": "available_collection",
                "data": [{"id": "123", "reward": 1.0}],
            }
        )


@pytest.mark.asyncio
async def test_gateway_run_offloads_header_build_and_event_emit(
    monkeypatch,
    tmp_path,
):
    gateway = GengoRealtimeGateway(
        _FakeConfig(
            {
                ("WebSocket", "user_id"): "user-1",
                ("WebSocket", "user_session"): "session-token",
                ("WebSocket", "wss_url"): "ws://example.test/socket",
            }
        )
    )
    event_file = tmp_path / "gateway_events.jsonl"
    monkeypatch.setattr(gateway, "_get_event_file", lambda: event_file)

    to_thread_calls = []

    async def fake_to_thread(func, *args, **kwargs):
        to_thread_calls.append(func.__name__)
        return func(*args, **kwargs)

    fake_ws = _FakeGatewayWebSocket(gateway)
    monkeypatch.setattr(websocket_server.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(
        websocket_server.websockets,
        "connect",
        lambda *_args, **_kwargs: fake_ws,
    )

    await gateway.run()

    assert "_build_headers" in to_thread_calls
    assert "_emit" in to_thread_calls
    assert fake_ws.sent == [
        json.dumps({"user_id": "user-1", "user_session": "session-token"})
    ]
    assert event_file.is_file()
    assert json.loads(event_file.read_text().splitlines()[0])["type"] == "job"
