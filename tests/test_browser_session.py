import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from gengowatcher.browser_session import (
    BrowserSessionError,
    extract_cookie_value,
    fetch_browser_session_token,
    select_gengo_target,
)
from gengowatcher.main import handle_cli_config_commands


class _MockUrlResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class _MockCDPWebSocket:
    def __init__(self, response):
        self._response = response
        self._sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send(self, data):
        self._sent.append(json.loads(data))

    async def recv(self):
        return json.dumps(self._response)


def test_select_gengo_target_returns_first_page_with_cdp_url():
    target = select_gengo_target(
        [
            {
                "type": "page",
                "url": "https://example.com",
                "webSocketDebuggerUrl": "ws://example",
            },
            {
                "type": "page",
                "url": "https://gengo.com/t/jobs/",
                "webSocketDebuggerUrl": "ws://gengo",
            },
        ]
    )

    assert target["webSocketDebuggerUrl"] == "ws://gengo"


def test_extract_cookie_value_returns_gengo_session_cookie():
    value = extract_cookie_value(
        [
            {"name": "other", "value": "ignore"},
            {"name": "myG_myGSession_", "value": "fresh-token"},
        ]
    )

    assert value == "fresh-token"


def test_extract_cookie_value_prefers_primary_cookie_name():
    value = extract_cookie_value(
        [
            {"name": "myG_rdsessID", "value": "secondary-token"},
            {"name": "myG_myGSession_", "value": "primary-token"},
        ]
    )

    assert value == "primary-token"


def test_extract_cookie_value_raises_when_missing():
    with pytest.raises(BrowserSessionError, match="session cookies"):
        extract_cookie_value([])


@pytest.mark.asyncio
async def test_fetch_browser_session_token_reads_cookie_from_cdp():
    targets = [
        {
            "type": "page",
            "url": "https://gengo.com/t/jobs/status/available/realtime",
            "webSocketDebuggerUrl": "ws://gengo-target",
        }
    ]
    cdp_response = {
        "id": 1,
        "result": {
            "cookies": [
                {"name": "myG_myGSession_", "value": "fresh-token"},
            ]
        },
    }

    with (
        patch(
            "gengowatcher.browser_session.urllib.request.urlopen",
            return_value=_MockUrlResponse(targets),
        ),
        patch(
            "gengowatcher.browser_session.websockets.connect",
            return_value=_MockCDPWebSocket(cdp_response),
        ),
    ):
        token = await fetch_browser_session_token("http://127.0.0.1:9222")

    assert token == "fresh-token"


def test_handle_cli_sync_session_updates_config_and_debug_url(capsys):
    args = SimpleNamespace(
        set=None,
        get=None,
        list=False,
        configure=False,
        sync_session_from_browser=True,
        check_session_from_browser=False,
        browser_debug_url="http://127.0.0.1:9222",
    )
    config = MagicMock()
    config.get.side_effect = lambda section, key: {
        ("WebSocket", "browser_debug_url"): "",
    }.get((section, key), None)

    with patch(
        "gengowatcher.main.fetch_browser_session_token_sync",
        return_value="fresh-token",
    ):
        handled = handle_cli_config_commands(args, config, console=MagicMock())

    assert handled is True
    assert config.set.call_args_list == [
        (("WebSocket", "user_session", "fresh-token"),),
        (("WebSocket", "browser_debug_url", "http://127.0.0.1:9222"),),
    ]
    config.save_config.assert_called_once()
    assert "Updated [WebSocket] user_session" in capsys.readouterr().out


def test_handle_cli_check_session_reports_mismatch(capsys):
    args = SimpleNamespace(
        set=None,
        get=None,
        list=False,
        configure=False,
        sync_session_from_browser=False,
        check_session_from_browser=True,
        browser_debug_url="http://127.0.0.1:9222",
    )
    config = MagicMock()
    config.get.side_effect = lambda section, key: {
        ("WebSocket", "browser_debug_url"): "http://127.0.0.1:9222",
        ("WebSocket", "user_session"): "stale-token",
    }.get((section, key), None)

    with patch(
        "gengowatcher.main.fetch_browser_session_token_sync",
        return_value="fresh-token",
    ):
        handled = handle_cli_config_commands(args, config, console=MagicMock())

    assert handled is True
    config.save_config.assert_not_called()
    assert "differs" in capsys.readouterr().out
