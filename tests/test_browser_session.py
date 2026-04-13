import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from gengowatcher.browser_session import (
    BrowserSessionError,
    _choose_browser_activity_action,
    _cdp_call,
    build_browser_aligned_websocket_headers,
    build_websocket_auth_payload,
    describe_browser_activity_action,
    extract_cookie_value,
    fetch_browser_session_snapshot,
    fetch_browser_session_token,
    refresh_browser_page_activity,
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
    def __init__(self, responses):
        self._responses = iter(responses)
        self._sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send(self, data):
        self._sent.append(json.loads(data))

    async def recv(self):
        return json.dumps(next(self._responses))


class _NeverRespondingWebSocket:
    async def send(self, data):
        return None

    async def recv(self):
        await asyncio.sleep(3600)


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


def test_select_gengo_target_prefers_requested_fragment():
    target = select_gengo_target(
        [
            {
                "type": "page",
                "url": "https://gengo.com/t/dashboard",
                "webSocketDebuggerUrl": "ws://dashboard",
            },
            {
                "type": "page",
                "url": "https://gengo.com/t/jobs/status/available/realtime",
                "webSocketDebuggerUrl": "ws://realtime",
            },
        ],
        preferred_url_fragments=("/t/jobs/status/available/realtime",),
    )

    assert target["webSocketDebuggerUrl"] == "ws://realtime"


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
            return_value=_MockCDPWebSocket([cdp_response]),
        ),
    ):
        token = await fetch_browser_session_token("http://127.0.0.1:9222")

    assert token == "fresh-token"


@pytest.mark.asyncio
async def test_fetch_browser_session_snapshot_reads_cookie_and_local_storage():
    targets = [
        {
            "type": "page",
            "url": "https://gengo.com/t/jobs/status/available/realtime",
            "webSocketDebuggerUrl": "ws://gengo-target",
        }
    ]
    cookie_response = {
        "id": 1,
        "result": {
            "cookies": [
                {"name": "myG_myGSession_", "value": "fresh-token"},
            ]
        },
    }
    runtime_response = {
        "id": 2,
        "result": {
            "result": {
                "type": "object",
                "value": {
                    "userKey": "browser-user-key",
                    "userAgent": "Helium Browser",
                    "acceptLanguage": "en-GB,en-US;q=0.9",
                    "origin": "https://gengo.com",
                    "url": "https://gengo.com/t/jobs/status/available/realtime",
                    "title": "Realtime Jobs",
                },
            }
        },
    }

    with (
        patch(
            "gengowatcher.browser_session.urllib.request.urlopen",
            return_value=_MockUrlResponse(targets),
        ),
        patch(
            "gengowatcher.browser_session.websockets.connect",
            return_value=_MockCDPWebSocket([cookie_response, runtime_response]),
        ),
    ):
        snapshot = await fetch_browser_session_snapshot("http://127.0.0.1:9222")

    assert snapshot.session_token == "fresh-token"
    assert snapshot.user_key == "browser-user-key"
    assert snapshot.user_agent == "Helium Browser"
    assert snapshot.accept_language == "en-GB,en-US;q=0.9"
    assert snapshot.target_title == "Realtime Jobs"


@pytest.mark.asyncio
async def test_fetch_browser_session_snapshot_keeps_cookie_when_runtime_eval_fails():
    targets = [
        {
            "type": "page",
            "url": "https://gengo.com/t/jobs/status/available/realtime",
            "webSocketDebuggerUrl": "ws://gengo-target",
        }
    ]
    cookie_response = {
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
            return_value=_MockCDPWebSocket([cookie_response]),
        ),
        patch(
            "gengowatcher.browser_session._evaluate_expression",
            side_effect=BrowserSessionError("runtime timed out"),
        ),
    ):
        snapshot = await fetch_browser_session_snapshot("http://127.0.0.1:9222")

    assert snapshot.session_token == "fresh-token"
    assert snapshot.user_key == ""
    assert snapshot.user_agent == ""
    assert snapshot.accept_language == ""
    assert snapshot.target_url == "https://gengo.com/t/jobs/status/available/realtime"


@pytest.mark.asyncio
async def test_fetch_browser_session_snapshot_rejects_non_http_debug_url():
    with pytest.raises(ValueError, match="unsupported browser debug URL scheme"):
        await fetch_browser_session_snapshot("ftp://127.0.0.1:9222")


@pytest.mark.asyncio
async def test_cdp_call_times_out_when_browser_never_replies():
    websocket = _NeverRespondingWebSocket()

    with pytest.raises(BrowserSessionError, match="CDP call timed out"):
        await _cdp_call(
            websocket,
            "Runtime.evaluate",
            {"expression": "1"},
            receive_timeout_sec=0.01,
        )


@pytest.mark.asyncio
async def test_refresh_browser_page_activity_summary_roundtrip_uses_cdp_navigation():
    targets = [
        {
            "type": "page",
            "url": "https://gengo.com/t/jobs/status/available/realtime",
            "webSocketDebuggerUrl": "ws://gengo-target",
        }
    ]
    responses = [
        {"id": 1, "result": {}},
        {
            "id": 2,
            "result": {
                "result": {
                    "type": "object",
                    "value": {
                        "href": "https://gengo.com/t/jobs/status/available/realtime",
                        "jobHref": "",
                    },
                }
            },
        },
        {"id": 3, "result": {}},
        {
            "id": 4,
            "result": {
                "result": {
                    "type": "string",
                    "value": "https://gengo.com/t/dashboard",
                }
            },
        },
        {"id": 5, "result": {}},
        {
            "id": 6,
            "result": {
                "result": {
                    "type": "string",
                    "value": "https://gengo.com/t/jobs/status/available/realtime",
                }
            },
        },
    ]
    mock_ws = _MockCDPWebSocket(responses)

    with (
        patch(
            "gengowatcher.browser_session.urllib.request.urlopen",
            return_value=_MockUrlResponse(targets),
        ),
        patch(
            "gengowatcher.browser_session.websockets.connect",
            return_value=mock_ws,
        ),
    ):
        action = await refresh_browser_page_activity(
            "http://127.0.0.1:9222",
            action="summary_roundtrip",
        )

    assert action == "summary_roundtrip"
    assert mock_ws._sent[0]["method"] == "Page.enable"
    assert mock_ws._sent[2]["method"] == "Page.navigate"
    assert mock_ws._sent[2]["params"]["url"].endswith("/t/dashboard")
    assert mock_ws._sent[4]["method"] == "Page.navigate"
    assert mock_ws._sent[4]["params"]["url"].endswith(
        "/t/jobs/status/available/realtime"
    )


def test_choose_browser_activity_action_avoids_repeating_previous_action():
    with patch(
        "gengowatcher.browser_session.random.choices",
        return_value=["job_roundtrip"],
    ) as mock_choices:
        action = _choose_browser_activity_action(
            job_href="https://gengo.com/t/jobs/details/123",
            previous_action="summary_roundtrip",
        )

    assert action == "job_roundtrip"
    args, kwargs = mock_choices.call_args
    assert "summary_roundtrip" not in args[0]
    assert kwargs["k"] == 1


def test_describe_browser_activity_action_returns_human_readable_text():
    assert (
        describe_browser_activity_action("job_roundtrip")
        == "opening a visible job details page and returning to realtime"
    )


def test_build_browser_aligned_websocket_headers_uses_browser_profile():
    headers = build_browser_aligned_websocket_headers(
        session_token="fresh-token",
        user_agent="Helium Browser",
        origin="https://gengo.com",
        accept_language="en-GB,en-US;q=0.9",
    )

    assert headers == {
        "Origin": "https://gengo.com",
        "Cookie": "myG_myGSession_=fresh-token; myG_rdsessID=fresh-token",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "User-Agent": "Helium Browser",
        "Accept-Language": "en-GB,en-US;q=0.9",
        "Accept-Encoding": "gzip, deflate, br, zstd",
    }


def test_build_websocket_auth_payload_uses_session_only():
    payload = build_websocket_auth_payload(
        user_id=12345,
        session_token="fresh-token",
        user_key="browser-user-key",
    )

    assert payload == {
        "user_id": 12345,
        "user_session": "fresh-token",
    }


def test_build_websocket_auth_payload_omits_placeholder_user_key():
    payload = build_websocket_auth_payload(
        user_id=12345,
        session_token="fresh-token",
        user_key="REPLACE_WITH_YOUR_USER_KEY",
    )

    assert payload == {
        "user_id": 12345,
        "user_session": "fresh-token",
    }


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
        (("WebSocket", "user_key", "browser-user-key"),),
        (("Network", "browser_user_agent", "Helium Browser"),),
        (("Network", "browser_accept_language", "en-GB,en-US;q=0.9"),),
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
