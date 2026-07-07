import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gengowatcher.browser_session import (
    BrowserSessionError,
    BrowserSessionSnapshot,
    _choose_browser_activity_action,
    _cdp_call,
    _normalize_debug_url,
    build_browser_aligned_websocket_headers,
    build_websocket_auth_payload,
    describe_browser_activity_action,
    extract_cookie_value,
    fetch_browser_session_snapshot,
    fetch_browser_session_snapshot_sync,
    fetch_browser_session_token,
    fetch_browser_session_token_sync,
    inspect_available_jobs_page,
    open_url_in_browser_debug,
    open_url_in_browser_debug_sync,
    refresh_browser_page_activity,
    refresh_browser_page_activity_sync,
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


class _MockJSONWebSocket:
    def __init__(self, responses):
        self._responses = iter(responses)
        self._sent = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send(self, data):
        self._sent.append(json.loads(data))

    async def recv(self):
        return json.dumps(next(self._responses))

    async def close(self):
        self.closed = True


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
            return_value=_MockJSONWebSocket([cdp_response]),
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
            return_value=_MockJSONWebSocket([cookie_response, runtime_response]),
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
            return_value=_MockJSONWebSocket([cookie_response]),
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


def test_normalize_debug_url_accepts_host_only_values():
    assert _normalize_debug_url("127.0.0.1") == "http://127.0.0.1:9222"
    assert _normalize_debug_url("127.0.0.1:6000") == "http://127.0.0.1:6000"
    assert _normalize_debug_url(":9222") == "http://127.0.0.1:9222"


@pytest.mark.asyncio
async def test_fetch_browser_session_token_reads_cookie_from_firefox_rdp():
    responses = [
        {"from": "root", "applicationType": "browser"},
        {
            "from": "root",
            "tabs": [
                {
                    "actor": "tab-descriptor-1",
                    "url": "https://gengo.com/t/jobs/status/available/realtime",
                    "title": "Realtime Jobs",
                }
            ],
            "selected": 0,
        },
        {
            "from": "tab-descriptor-1",
            "frame": {
                "actor": "tab-target-1",
                "consoleActor": "tab-console-1",
                "innerWindowId": 101,
                "url": "https://gengo.com/t/jobs/status/available/realtime",
                "title": "Realtime Jobs",
            },
        },
        {
            "from": "root",
            "processDescriptor": {
                "actor": "process-descriptor-1",
                "id": 0,
                "isParent": True,
            },
        },
        {
            "from": "process-descriptor-1",
            "process": {
                "actor": "parent-process-target-1",
                "consoleActor": "browser-console-1",
            },
        },
        {
            "from": "browser-console-1",
            "resultID": "cookie-eval-1",
        },
        {
            "from": "browser-console-1",
            "type": "evaluationResult",
            "hasException": False,
            "resultID": "cookie-eval-1",
            "result": json.dumps({"sessionToken": "fresh-token"}),
            "input": "ignored",
            "timestamp": 1,
            "startTime": 1,
        },
    ]
    mock_ws = _MockJSONWebSocket(responses)

    with patch(
        "gengowatcher.browser_session.websockets.connect",
        new=AsyncMock(return_value=mock_ws),
    ) as mock_connect:
        token = await fetch_browser_session_token("ws://127.0.0.1:9222")

    assert token == "fresh-token"
    mock_connect.assert_awaited_once_with(
        "ws://127.0.0.1:9222",
        max_size=5_000_000,
    )
    assert mock_ws.closed is True
    assert [message["type"] for message in mock_ws._sent] == [
        "listTabs",
        "getTarget",
        "getProcess",
        "getTarget",
        "evaluateJSAsync",
    ]


@pytest.mark.asyncio
async def test_open_url_in_browser_debug_uses_firefox_rdp_browser_window():
    responses = [
        {"from": "root", "applicationType": "browser"},
        {
            "from": "root",
            "processDescriptor": {
                "actor": "process-descriptor-1",
                "id": 0,
                "isParent": True,
            },
        },
        {
            "from": "process-descriptor-1",
            "process": {
                "actor": "parent-process-target-1",
                "consoleActor": "browser-console-1",
            },
        },
        {
            "from": "browser-console-1",
            "resultID": "open-tab-eval-1",
        },
        {
            "from": "browser-console-1",
            "type": "evaluationResult",
            "hasException": False,
            "resultID": "open-tab-eval-1",
            "result": json.dumps(
                {
                    "opened": True,
                    "url": "https://gengo.com/t/jobs/details/123",
                }
            ),
            "input": "ignored",
            "timestamp": 1,
            "startTime": 1,
        },
    ]
    mock_ws = _MockJSONWebSocket(responses)

    with patch(
        "gengowatcher.browser_session.websockets.connect",
        new=AsyncMock(return_value=mock_ws),
    ) as mock_connect:
        opened_url = await open_url_in_browser_debug(
            "ws://127.0.0.1:9222",
            "https://gengo.com/t/jobs/details/123",
        )

    assert opened_url == "https://gengo.com/t/jobs/details/123"
    mock_connect.assert_awaited_once_with(
        "ws://127.0.0.1:9222",
        max_size=5_000_000,
    )
    assert mock_ws.closed is True
    assert [message["type"] for message in mock_ws._sent] == [
        "getProcess",
        "getTarget",
        "evaluateJSAsync",
    ]
    assert "openTrustedLinkIn" in mock_ws._sent[2]["text"]
    assert "https://gengo.com/t/jobs/details/123" in mock_ws._sent[2]["text"]


@pytest.mark.asyncio
async def test_fetch_browser_session_snapshot_reads_cookie_and_local_storage_from_firefox_rdp():
    page_state = json.dumps(
        {
            "userKey": "browser-user-key",
            "userAgent": "Mozilla/5.0 Firefox/147.0",
            "acceptLanguage": "en-GB,en-US;q=0.9",
            "origin": "https://gengo.com",
            "url": "https://gengo.com/t/jobs/status/available/realtime",
            "title": "Realtime Jobs",
            "readyState": "complete",
            "jobHref": "",
        }
    )
    responses = [
        {"from": "root", "applicationType": "browser"},
        {
            "from": "root",
            "tabs": [
                {
                    "actor": "tab-descriptor-1",
                    "url": "https://gengo.com/t/jobs/status/available/realtime",
                    "title": "Realtime Jobs",
                }
            ],
            "selected": 0,
        },
        {
            "from": "tab-descriptor-1",
            "frame": {
                "actor": "tab-target-1",
                "consoleActor": "tab-console-1",
                "innerWindowId": 101,
                "url": "https://gengo.com/t/jobs/status/available/realtime",
                "title": "Realtime Jobs",
            },
        },
        {
            "from": "tab-console-1",
            "resultID": "page-state-1",
        },
        {
            "from": "tab-console-1",
            "type": "evaluationResult",
            "hasException": False,
            "resultID": "page-state-1",
            "result": page_state,
            "input": "ignored",
            "timestamp": 1,
            "startTime": 1,
        },
        {
            "from": "root",
            "processDescriptor": {
                "actor": "process-descriptor-1",
                "id": 0,
                "isParent": True,
            },
        },
        {
            "from": "process-descriptor-1",
            "process": {
                "actor": "parent-process-target-1",
                "consoleActor": "browser-console-1",
            },
        },
        {
            "from": "browser-console-1",
            "resultID": "cookie-eval-1",
        },
        {
            "from": "browser-console-1",
            "type": "evaluationResult",
            "hasException": False,
            "resultID": "cookie-eval-1",
            "result": json.dumps({"sessionToken": "fresh-token"}),
            "input": "ignored",
            "timestamp": 1,
            "startTime": 1,
        },
    ]
    mock_ws = _MockJSONWebSocket(responses)

    with patch(
        "gengowatcher.browser_session.websockets.connect",
        new=AsyncMock(return_value=mock_ws),
    ):
        snapshot = await fetch_browser_session_snapshot("ws://127.0.0.1:9222")

    assert snapshot.session_token == "fresh-token"
    assert snapshot.user_key == "browser-user-key"
    assert snapshot.user_agent == "Mozilla/5.0 Firefox/147.0"
    assert snapshot.accept_language == "en-GB,en-US;q=0.9"
    assert snapshot.target_title == "Realtime Jobs"
    assert mock_ws.closed is True
    assert [message["type"] for message in mock_ws._sent] == [
        "listTabs",
        "getTarget",
        "evaluateJSAsync",
        "getProcess",
        "getTarget",
        "evaluateJSAsync",
    ]
    assert mock_ws._sent[2]["innerWindowID"] == 101


@pytest.mark.asyncio
async def test_inspect_available_jobs_page_reads_firefox_rdp_dom_jobs():
    responses = [
        {"from": "root", "applicationType": "browser"},
        {
            "from": "root",
            "tabs": [
                {
                    "actor": "tab-descriptor-1",
                    "url": "https://gengo.com/t/jobs/status/available",
                    "title": "Available Jobs",
                }
            ],
            "selected": 0,
        },
        {
            "from": "tab-descriptor-1",
            "frame": {
                "actor": "tab-target-1",
                "consoleActor": "tab-console-1",
                "innerWindowId": 101,
                "url": "https://gengo.com/t/jobs/status/available",
                "title": "Available Jobs",
            },
        },
        {
            "from": "tab-console-1",
            "resultID": "dom-1",
        },
        {
            "from": "tab-console-1",
            "type": "evaluationResult",
            "hasException": False,
            "resultID": "dom-1",
            "result": json.dumps(
                {
                    "url": "https://gengo.com/t/jobs/status/available",
                    "title": "Available Jobs",
                    "readyState": "complete",
                    "jobs": [
                        {
                            "id": "123456",
                            "title": "Japanese to English",
                            "reward": 12.5,
                            "url": "https://gengo.com/t/jobs/details/123456",
                            "text": "Japanese to English US$12.50",
                        }
                    ],
                    "detectedJobs": [],
                }
            ),
            "input": "ignored",
            "timestamp": 1,
            "startTime": 1,
        },
    ]
    mock_ws = _MockJSONWebSocket(responses)

    with patch(
        "gengowatcher.browser_session.websockets.connect",
        new=AsyncMock(return_value=mock_ws),
    ):
        snapshot = await inspect_available_jobs_page("ws://127.0.0.1:9222")

    assert snapshot.url == "https://gengo.com/t/jobs/status/available"
    assert snapshot.action == "inspect"
    assert len(snapshot.jobs) == 1
    assert snapshot.jobs[0].job_id == 123456
    assert snapshot.jobs[0].reward == 12.5
    assert [message["type"] for message in mock_ws._sent] == [
        "listTabs",
        "getTarget",
        "evaluateJSAsync",
    ]
    assert "MutationObserver" in mock_ws._sent[2]["text"]


@pytest.mark.asyncio
async def test_inspect_available_jobs_page_passive_firefox_rdp_does_not_reclaim_manual_tab():
    responses = [
        {"from": "root", "applicationType": "browser"},
        {
            "from": "root",
            "tabs": [
                {
                    "actor": "tab-descriptor-1",
                    "consoleActor": "tab-console-1",
                    "url": "https://gengo.com/t/dashboard",
                    "title": "Dashboard",
                }
            ],
            "selected": 0,
        },
    ]
    mock_ws = _MockJSONWebSocket(responses)

    with patch(
        "gengowatcher.browser_session.websockets.connect",
        new=AsyncMock(return_value=mock_ws),
    ):
        snapshot = await inspect_available_jobs_page(
            "ws://127.0.0.1:9222",
            allow_navigation=False,
        )

    assert snapshot.action == "manual_browse"
    assert snapshot.jobs == ()
    assert mock_ws.closed is True
    assert [message["type"] for message in mock_ws._sent] == ["listTabs"]


@pytest.mark.asyncio
async def test_inspect_available_jobs_page_passive_cdp_does_not_reclaim_manual_tab():
    with (
        patch(
            "gengowatcher.browser_session._load_cdp_targets",
            return_value=[
                {
                    "id": "target-1",
                    "type": "page",
                    "url": "https://gengo.com/t/dashboard",
                    "title": "Dashboard",
                    "webSocketDebuggerUrl": "ws://target-1",
                }
            ],
        ),
        patch("gengowatcher.browser_session.websockets.connect") as connect,
    ):
        snapshot = await inspect_available_jobs_page(
            "http://127.0.0.1:9222",
            allow_navigation=False,
        )

    assert snapshot.action == "manual_browse"
    assert snapshot.url == "https://gengo.com/t/dashboard"
    assert snapshot.title == "Dashboard"
    assert snapshot.jobs == ()
    connect.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_browser_page_activity_summary_roundtrip_uses_firefox_rdp_navigation():
    responses = [
        {"from": "root", "applicationType": "browser"},
        {
            "from": "root",
            "tabs": [
                {
                    "actor": "tab-descriptor-1",
                    "url": "https://gengo.com/t/jobs/status/available/realtime",
                    "title": "Realtime Jobs",
                }
            ],
            "selected": 0,
        },
        {
            "from": "tab-descriptor-1",
            "frame": {
                "actor": "tab-target-1",
                "consoleActor": "tab-console-1",
                "innerWindowId": 101,
                "url": "https://gengo.com/t/jobs/status/available/realtime",
                "title": "Realtime Jobs",
            },
        },
        {
            "from": "tab-console-1",
            "resultID": "state-1",
        },
        {
            "from": "tab-console-1",
            "type": "evaluationResult",
            "hasException": False,
            "resultID": "state-1",
            "result": json.dumps(
                {
                    "href": "https://gengo.com/t/jobs/status/available/realtime",
                    "readyState": "complete",
                    "activityMarker": "",
                    "jobHref": "",
                }
            ),
            "input": "ignored",
            "timestamp": 1,
            "startTime": 1,
        },
        {
            "from": "tab-console-1",
            "resultID": "nav-1",
        },
        {
            "from": "tab-console-1",
            "type": "evaluationResult",
            "hasException": False,
            "resultID": "nav-1",
            "result": json.dumps(
                {
                    "queued": True,
                    "marker": "marker-1",
                    "url": "https://gengo.com/t/dashboard",
                }
            ),
            "input": "ignored",
            "timestamp": 1,
            "startTime": 1,
        },
        {
            "from": "root",
            "tabs": [
                {
                    "actor": "tab-descriptor-1",
                    "url": "https://gengo.com/t/dashboard",
                    "title": "Summary",
                }
            ],
            "selected": 0,
        },
        {
            "from": "tab-descriptor-1",
            "frame": {
                "actor": "tab-target-1",
                "consoleActor": "tab-console-2",
                "innerWindowId": 102,
                "url": "https://gengo.com/t/dashboard",
                "title": "Summary",
            },
        },
        {
            "from": "tab-console-2",
            "resultID": "state-2",
        },
        {
            "from": "tab-console-2",
            "type": "evaluationResult",
            "hasException": False,
            "resultID": "state-2",
            "result": json.dumps(
                {
                    "href": "https://gengo.com/t/dashboard",
                    "readyState": "complete",
                    "activityMarker": "marker-1",
                    "jobHref": "",
                }
            ),
            "input": "ignored",
            "timestamp": 1,
            "startTime": 1,
        },
        {
            "from": "tab-console-2",
            "resultID": "nav-2",
        },
        {
            "from": "tab-console-2",
            "type": "evaluationResult",
            "hasException": False,
            "resultID": "nav-2",
            "result": json.dumps(
                {
                    "queued": True,
                    "marker": "marker-2",
                    "url": "https://gengo.com/t/jobs/status/available/realtime",
                }
            ),
            "input": "ignored",
            "timestamp": 1,
            "startTime": 1,
        },
        {
            "from": "root",
            "tabs": [
                {
                    "actor": "tab-descriptor-1",
                    "url": "https://gengo.com/t/jobs/status/available/realtime",
                    "title": "Realtime Jobs",
                }
            ],
            "selected": 0,
        },
        {
            "from": "tab-descriptor-1",
            "frame": {
                "actor": "tab-target-1",
                "consoleActor": "tab-console-3",
                "innerWindowId": 103,
                "url": "https://gengo.com/t/jobs/status/available/realtime",
                "title": "Realtime Jobs",
            },
        },
        {
            "from": "tab-console-3",
            "resultID": "state-3",
        },
        {
            "from": "tab-console-3",
            "type": "evaluationResult",
            "hasException": False,
            "resultID": "state-3",
            "result": json.dumps(
                {
                    "href": "https://gengo.com/t/jobs/status/available/realtime",
                    "readyState": "complete",
                    "activityMarker": "marker-2",
                    "jobHref": "",
                }
            ),
            "input": "ignored",
            "timestamp": 1,
            "startTime": 1,
        },
    ]
    mock_ws = _MockJSONWebSocket(responses)

    with (
        patch(
            "gengowatcher.browser_session.websockets.connect",
            new=AsyncMock(return_value=mock_ws),
        ),
        patch(
            "gengowatcher.browser_session._make_firefox_activity_marker",
            side_effect=["marker-1", "marker-2"],
        ),
        patch("gengowatcher.browser_session.asyncio.sleep", new=AsyncMock()),
    ):
        action = await refresh_browser_page_activity(
            "ws://127.0.0.1:9222",
            action="summary_roundtrip",
        )

    assert action == "summary_roundtrip"
    assert mock_ws.closed is True
    assert [message["type"] for message in mock_ws._sent] == [
        "listTabs",
        "getTarget",
        "evaluateJSAsync",
        "evaluateJSAsync",
        "listTabs",
        "getTarget",
        "evaluateJSAsync",
        "evaluateJSAsync",
        "listTabs",
        "getTarget",
        "evaluateJSAsync",
    ]
    assert mock_ws._sent[2]["innerWindowID"] == 101
    assert mock_ws._sent[6]["innerWindowID"] == 102
    assert mock_ws._sent[10]["innerWindowID"] == 103
    assert "location.href = targetUrl" in mock_ws._sent[3]["text"]
    assert "https://gengo.com/t/dashboard" in mock_ws._sent[3]["text"]
    assert "https://gengo.com/t/jobs/status/available" in mock_ws._sent[7]["text"]


@pytest.mark.asyncio
async def test_fetch_browser_session_token_reads_cookie_from_firefox_bidi():
    responses = [
        {
            "id": 1,
            "type": "success",
            "result": {
                "sessionId": "firefox-session",
                "capabilities": {
                    "browserName": "firefox",
                },
            },
        },
        {
            "id": 2,
            "type": "success",
            "result": {
                "contexts": [
                    {
                        "context": "ctx-1",
                        "url": "https://gengo.com/t/jobs/status/available/realtime",
                    }
                ]
            },
        },
        {
            "id": 3,
            "type": "success",
            "result": {
                "cookies": [
                    {
                        "name": "myG_myGSession_",
                        "value": {"type": "string", "value": "fresh-token"},
                    }
                ],
                "partitionKey": {"sourceOrigin": "https://gengo.com"},
            },
        },
        {"id": 4, "type": "success", "result": {}},
    ]
    mock_ws = _MockJSONWebSocket(responses)

    with patch(
        "gengowatcher.browser_session.websockets.connect",
        return_value=mock_ws,
    ) as mock_connect:
        token = await fetch_browser_session_token("ws://127.0.0.1:9222/session")

    assert token == "fresh-token"
    mock_connect.assert_called_once_with(
        "ws://127.0.0.1:9222/session",
        max_size=5_000_000,
    )
    assert [message["method"] for message in mock_ws._sent] == [
        "session.new",
        "browsingContext.getTree",
        "storage.getCookies",
        "session.end",
    ]


@pytest.mark.asyncio
async def test_fetch_browser_session_snapshot_reads_cookie_and_local_storage_from_firefox_bidi():
    responses = [
        {
            "id": 1,
            "type": "success",
            "result": {
                "sessionId": "firefox-session",
                "capabilities": {
                    "browserName": "firefox",
                },
            },
        },
        {
            "id": 2,
            "type": "success",
            "result": {
                "contexts": [
                    {
                        "context": "ctx-1",
                        "url": "https://gengo.com/t/jobs/status/available/realtime",
                    }
                ]
            },
        },
        {
            "id": 3,
            "type": "success",
            "result": {
                "cookies": [
                    {
                        "name": "myG_myGSession_",
                        "value": {"type": "string", "value": "fresh-token"},
                    }
                ],
                "partitionKey": {"sourceOrigin": "https://gengo.com"},
            },
        },
        {
            "id": 4,
            "type": "success",
            "result": {
                "type": "success",
                "result": {
                    "type": "string",
                    "value": json.dumps(
                        {
                            "userKey": "browser-user-key",
                            "userAgent": "Mozilla/5.0 Firefox/147.0",
                            "acceptLanguage": "en-GB,en-US;q=0.9",
                            "origin": "https://gengo.com",
                            "url": "https://gengo.com/t/jobs/status/available/realtime",
                            "title": "Realtime Jobs",
                        }
                    ),
                },
                "realm": "realm-1",
            },
        },
        {"id": 5, "type": "success", "result": {}},
    ]
    mock_ws = _MockJSONWebSocket(responses)

    with patch(
        "gengowatcher.browser_session.websockets.connect",
        return_value=mock_ws,
    ):
        snapshot = await fetch_browser_session_snapshot("ws://127.0.0.1:9222/session")

    assert snapshot.session_token == "fresh-token"
    assert snapshot.user_key == "browser-user-key"
    assert snapshot.user_agent == "Mozilla/5.0 Firefox/147.0"
    assert snapshot.accept_language == "en-GB,en-US;q=0.9"
    assert snapshot.target_title == "Realtime Jobs"
    assert mock_ws._sent[2]["params"] == {
        "partition": {
            "type": "context",
            "context": "ctx-1",
        }
    }


@pytest.mark.asyncio
async def test_refresh_browser_page_activity_summary_roundtrip_uses_firefox_bidi_navigation():
    responses = [
        {
            "id": 1,
            "type": "success",
            "result": {
                "sessionId": "firefox-session",
                "capabilities": {
                    "browserName": "firefox",
                },
            },
        },
        {
            "id": 2,
            "type": "success",
            "result": {
                "contexts": [
                    {
                        "context": "ctx-1",
                        "url": "https://gengo.com/t/jobs/status/available/realtime",
                    }
                ]
            },
        },
        {
            "id": 3,
            "type": "success",
            "result": {
                "type": "success",
                "result": {
                    "type": "string",
                    "value": json.dumps(
                        {
                            "href": "https://gengo.com/t/jobs/status/available/realtime",
                            "jobHref": "",
                        }
                    ),
                },
                "realm": "realm-1",
            },
        },
        {
            "id": 4,
            "type": "success",
            "result": {
                "navigation": "nav-1",
                "url": "https://gengo.com/t/dashboard",
            },
        },
        {
            "id": 5,
            "type": "success",
            "result": {
                "navigation": "nav-2",
                "url": "https://gengo.com/t/jobs/status/available/realtime",
            },
        },
        {"id": 6, "type": "success", "result": {}},
    ]
    mock_ws = _MockJSONWebSocket(responses)

    with patch(
        "gengowatcher.browser_session.websockets.connect",
        return_value=mock_ws,
    ):
        action = await refresh_browser_page_activity(
            "ws://127.0.0.1:9222/session",
            action="summary_roundtrip",
        )

    assert action == "summary_roundtrip"
    assert [message["method"] for message in mock_ws._sent] == [
        "session.new",
        "browsingContext.getTree",
        "script.evaluate",
        "browsingContext.navigate",
        "browsingContext.navigate",
        "session.end",
    ]
    assert mock_ws._sent[3]["params"]["url"].endswith("/t/dashboard")
    assert mock_ws._sent[4]["params"]["url"].endswith("/t/jobs/status/available")


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
    mock_ws = _MockJSONWebSocket(responses)

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
    assert mock_ws._sent[4]["params"]["url"].endswith("/t/jobs/status/available")


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
        == "opening a visible job details page and returning to available jobs"
    )


def test_build_browser_aligned_websocket_headers_uses_browser_profile():
    headers = build_browser_aligned_websocket_headers(
        session_token="fresh-token",
        user_agent="Helium Browser",
        origin="https://gengo.com",
        accept_language="en-GB,en-US;q=0.9",
    )

    assert headers == {
        "Host": "live-dashboard.gengo.com",
        "User-Agent": "Helium Browser",
        "Accept": "*/*",
        "Accept-Language": "en-GB,en-US;q=0.9",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Sec-WebSocket-Version": "13",
        "Origin": "https://gengo.com",
        "Sec-WebSocket-Extensions": "permessage-deflate",
        "Sec-GPC": "1",
        "Connection": "Upgrade",
        "Upgrade": "websocket",
        "Cookie": "myG_myGSession_=fresh-token; myG_rdsessID=fresh-token",
    }


def test_build_websocket_auth_payload_uses_session_only():
    payload = build_websocket_auth_payload(
        user_id=12345,
        session_token="fresh-token",
    )

    assert payload == {
        "user_id": 12345,
        "user_session": "fresh-token",
    }


def test_build_websocket_auth_payload_omits_user_key():
    payload = build_websocket_auth_payload(
        user_id=12345,
        session_token="fresh-token",
    )

    assert payload == {
        "user_id": 12345,
        "user_session": "fresh-token",
    }


@pytest.mark.asyncio
async def test_sync_browser_session_wrappers_work_inside_running_event_loop():
    async def fake_snapshot(*, debug_url=None, cookie_name=None):
        return BrowserSessionSnapshot(session_token=f"{debug_url}:{cookie_name}")

    async def fake_token(*, debug_url=None, cookie_name=None):
        return f"{debug_url}:{cookie_name}"

    async def fake_open(debug_url, url):
        return f"{debug_url} -> {url}"

    async def fake_refresh(*, debug_url=None, action="auto", previous_action=None):
        return f"{debug_url}:{action}:{previous_action}"

    with (
        patch(
            "gengowatcher.browser_session.fetch_browser_session_snapshot",
            side_effect=fake_snapshot,
        ),
        patch(
            "gengowatcher.browser_session.fetch_browser_session_token",
            side_effect=fake_token,
        ),
        patch(
            "gengowatcher.browser_session.open_url_in_browser_debug",
            side_effect=fake_open,
        ),
        patch(
            "gengowatcher.browser_session.refresh_browser_page_activity",
            side_effect=fake_refresh,
        ),
    ):
        snapshot = fetch_browser_session_snapshot_sync(
            "ws://127.0.0.1:9222", cookie_name="session"
        )
        token = fetch_browser_session_token_sync(
            "ws://127.0.0.1:9222", cookie_name="session"
        )
        opened = open_url_in_browser_debug_sync(
            "ws://127.0.0.1:9222", "https://gengo.com/t/jobs/1"
        )
        refreshed = refresh_browser_page_activity_sync(
            "ws://127.0.0.1:9222",
            action="reload",
            previous_action="summary_roundtrip",
        )

    assert snapshot.session_token == "ws://127.0.0.1:9222:session"
    assert token == "ws://127.0.0.1:9222:session"
    assert opened == "ws://127.0.0.1:9222 -> https://gengo.com/t/jobs/1"
    assert refreshed == "ws://127.0.0.1:9222:reload:summary_roundtrip"


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
        "gengowatcher.main.fetch_browser_session_snapshot_sync",
        return_value=BrowserSessionSnapshot(
            session_token="fresh-token",
            user_key="browser-user-key",
            user_agent="Helium Browser",
            accept_language="en-GB,en-US;q=0.9",
        ),
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


def test_handle_cli_sync_session_token_fallback_preserves_browser_metadata(capsys):
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
        ("WebSocket", "user_key"): "real-browser-user-key",
        ("Network", "browser_user_agent"): "Real Browser",
        ("Network", "browser_accept_language"): "ja,en-US;q=0.9",
    }.get((section, key), None)

    with (
        patch(
            "gengowatcher.main.fetch_browser_session_snapshot_sync",
            side_effect=RuntimeError("snapshot unavailable"),
        ),
        patch(
            "gengowatcher.cli.maybe_launch_managed_firefox_debug",
            return_value=False,
        ),
        patch(
            "gengowatcher.main.fetch_browser_session_token_sync",
            return_value="fresh-token",
        ),
    ):
        handled = handle_cli_config_commands(args, config, console=MagicMock())

    assert handled is True
    assert config.set.call_args_list == [
        (("WebSocket", "user_session", "fresh-token"),),
        (("WebSocket", "browser_debug_url", "http://127.0.0.1:9222"),),
    ]
    config.save_config.assert_called_once()
    assert "Updated [WebSocket] user_session" in capsys.readouterr().out


def test_handle_cli_start_firefox_debug_reuses_running_server(capsys):
    args = SimpleNamespace(
        set=None,
        get=None,
        list=False,
        configure=False,
        sync_session_from_browser=False,
        check_session_from_browser=False,
        start_firefox_debug=True,
        browser_debug_url="ws://127.0.0.1:9222",
    )
    config = MagicMock()
    config.get.side_effect = lambda section, key, fallback=None: {
        ("Paths", "browser_debug_browser_path"): "firefox",
        ("WebSocket", "browser_debug_profile_path"): "profiles/firefox-debug",
        (
            "WebSocket",
            "browser_debug_start_url",
        ): "https://gengo.com/t/jobs/status/available/realtime",
    }.get((section, key), fallback)

    with (
        patch(
            "gengowatcher.cli.can_connect_to_firefox_debug_server",
            return_value=True,
        ),
        patch("gengowatcher.cli.launch_managed_firefox_debug") as mock_launch,
        patch("gengowatcher.cli.wait_for_firefox_debug_server") as mock_wait,
    ):
        handled = handle_cli_config_commands(args, config, console=MagicMock())

    assert handled is True
    mock_launch.assert_not_called()
    mock_wait.assert_not_called()
    config.save_config.assert_not_called()
    assert "already available" in capsys.readouterr().out


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
