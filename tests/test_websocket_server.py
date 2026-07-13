import json

import pytest
from fastapi.testclient import TestClient

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
        websocket_server,
        "connect",
        lambda *_args, **_kwargs: fake_ws,
    )

    await gateway.run()

    assert "_build_headers" in to_thread_calls
    assert "_emit" in to_thread_calls
    # Auth payload now matches the in-process monitor's camelCase shape
    # (userId / sessionToken / userKey); the standalone gateway previously
    # sent snake_case keys that Gengo silently rejected.
    assert fake_ws.sent == [
        json.dumps({"userId": "user-1", "sessionToken": "session-token"})
    ]
    assert event_file.is_file()
    assert json.loads(event_file.read_text().splitlines()[0])["type"] == "job"


def test_latest_event_requires_api_token(monkeypatch):
    gateway = GengoRealtimeGateway(
        _FakeConfig({("WebServer", "auth_token"): "token-123"})
    )
    gateway._last_event = {"type": "job", "data": {"id": "123"}}
    monkeypatch.setattr(websocket_server, "_gateway", gateway)

    client = TestClient(websocket_server.api)

    unauthorized = client.get("/events/latest")
    assert unauthorized.status_code == 404
    assert unauthorized.content == b""

    authorized = client.get(
        "/events/latest",
        headers={"Authorization": "Bearer token-123"},
    )
    assert authorized.status_code == 200
    assert authorized.json() == {"type": "job", "data": {"id": "123"}}


def test_latest_event_rejects_placeholder_api_token(monkeypatch):
    gateway = GengoRealtimeGateway(
        _FakeConfig({("WebServer", "auth_token"): "REPLACE_WITH_YOUR_WEB_API_TOKEN"})
    )
    gateway._last_event = {"type": "job"}
    monkeypatch.setattr(websocket_server, "_gateway", gateway)

    response = TestClient(websocket_server.api).get(
        "/events/latest",
        headers={"Authorization": "Bearer REPLACE_WITH_YOUR_WEB_API_TOKEN"},
    )

    assert response.status_code == 404
    assert response.content == b""


def test_gateway_cors_does_not_allow_arbitrary_origin():
    response = TestClient(websocket_server.api).options(
        "/events/latest",
        headers={
            "Origin": "http://evil.test",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert "access-control-allow-origin" not in response.headers
