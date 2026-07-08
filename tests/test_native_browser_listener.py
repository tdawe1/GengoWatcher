import asyncio
import logging
from unittest.mock import AsyncMock, patch

from gengowatcher.native_browser_listener import NativeBrowserListener


class _FakeWebSocket:
    def __init__(self, loop_ids: list[int]):
        self.loop_ids = loop_ids

    async def close(self):
        self.loop_ids.append(id(asyncio.get_running_loop()))


class _FakeRdpClient:
    def __init__(self, loop_ids: list[int], responses=None):
        self.websocket = _FakeWebSocket(loop_ids)
        self.loop_ids = loop_ids
        self.responses = responses or {}

    async def request(self, actor, packet_type, **_payload):
        self.loop_ids.append(id(asyncio.get_running_loop()))
        return self.responses[(actor, packet_type)]


def test_run_once_uses_one_event_loop_for_single_rdp_connection():
    """A single RDP websocket must not be reused across asyncio.run() loops."""
    loop_ids: list[int] = []
    events = []

    async def open_client(debug_url):
        loop_ids.append(id(asyncio.get_running_loop()))
        return _FakeRdpClient(loop_ids)

    async def list_tabs(client):
        loop_ids.append(id(asyncio.get_running_loop()))
        return {
            "tabs": [
                {
                    "url": "https://gengo.com/t/workbench/123",
                    "consoleActor": "console-actor",
                }
            ]
        }

    async def evaluate_json(client, actor, expression, **_kwargs):
        loop_ids.append(id(asyncio.get_running_loop()))
        if "secondsLeft" in expression:
            return {
                "url": "https://gengo.com/t/workbench/123",
                "collectionId": "123",
                "seconds_left": 42,
            }
        return {"result": None}

    listener = NativeBrowserListener(debug_url="ws://127.0.0.1:6000")

    with (
        patch(
            "gengowatcher.native_browser_listener._open_firefox_rdp_client",
            side_effect=open_client,
        ),
        patch(
            "gengowatcher.native_browser_listener._firefox_rdp_list_tabs",
            side_effect=list_tabs,
        ),
        patch(
            "gengowatcher.native_browser_listener._firefox_rdp_evaluate_json",
            side_effect=evaluate_json,
        ),
        patch(
            "gengowatcher.native_browser_listener.publish_native_event",
            side_effect=events.append,
        ),
    ):
        listener.run_once()

    assert len(set(loop_ids)) == 1
    assert listener._last_collection_id == "123"
    assert events[0].payload["raw"] is None
    assert [event.type for event in events] == [
        "browser.workbench.visible",
        "browser.workbench.status",
    ]


def test_run_once_resolves_descriptor_only_workbench_tab():
    loop_ids: list[int] = []
    events = []
    evaluated_actors: list[str] = []
    inner_window_ids: list[int | None] = []

    async def open_client(debug_url):
        loop_ids.append(id(asyncio.get_running_loop()))
        return _FakeRdpClient(
            loop_ids,
            responses={
                ("tab-descriptor-1", "getTarget"): {
                    "frame": {
                        "actor": "tab-target-1",
                        "consoleActor": "tab-console-1",
                        "innerWindowId": 101,
                        "url": "https://gengo.com/t/workbench/123#!/",
                    }
                }
            },
        )

    async def list_tabs(client):
        loop_ids.append(id(asyncio.get_running_loop()))
        return {
            "tabs": [
                {
                    "actor": "tab-descriptor-1",
                    "url": "https://gengo.com/t/workbench/123#!/",
                    "title": "Workbench",
                }
            ]
        }

    async def evaluate_json(client, actor, expression, **kwargs):
        loop_ids.append(id(asyncio.get_running_loop()))
        evaluated_actors.append(actor)
        inner_window_ids.append(kwargs.get("inner_window_id"))
        if "secondsLeft" in expression:
            return {
                "url": "https://gengo.com/t/workbench/123#!/",
                "collectionId": "123",
                "seconds_left": 42,
            }
        return {"result": None}

    listener = NativeBrowserListener(debug_url="ws://127.0.0.1:6000")

    with (
        patch(
            "gengowatcher.native_browser_listener._open_firefox_rdp_client",
            side_effect=open_client,
        ),
        patch(
            "gengowatcher.native_browser_listener._firefox_rdp_list_tabs",
            side_effect=list_tabs,
        ),
        patch(
            "gengowatcher.native_browser_listener._firefox_rdp_evaluate_json",
            side_effect=evaluate_json,
        ),
        patch(
            "gengowatcher.native_browser_listener.publish_native_event",
            side_effect=events.append,
        ),
    ):
        listener.run_once()

    assert len(set(loop_ids)) == 1
    assert evaluated_actors == ["tab-console-1", "tab-console-1"]
    assert inner_window_ids == [101, 101]
    assert listener._last_collection_id == "123"
    assert events[0].payload["raw"] is None
    assert [event.type for event in events] == [
        "browser.workbench.visible",
        "browser.workbench.status",
    ]


def test_run_once_ignores_workbench_tab_without_console_actor(caplog):
    loop_ids: list[int] = []
    evaluate_json = AsyncMock()

    async def open_client(debug_url):
        loop_ids.append(id(asyncio.get_running_loop()))
        return _FakeRdpClient(
            loop_ids,
            responses={
                ("tab-descriptor-1", "getTarget"): {
                    "frame": {
                        "actor": "tab-target-1",
                        "url": "https://gengo.com/t/workbench/123#!/",
                    }
                }
            },
        )

    async def list_tabs(client):
        loop_ids.append(id(asyncio.get_running_loop()))
        return {
            "tabs": [
                {
                    "actor": "tab-descriptor-1",
                    "url": "https://gengo.com/t/workbench/123#!/",
                    "title": "Workbench",
                }
            ]
        }

    listener = NativeBrowserListener(debug_url="ws://127.0.0.1:6000")

    with (
        caplog.at_level(logging.DEBUG),
        patch(
            "gengowatcher.native_browser_listener._open_firefox_rdp_client",
            side_effect=open_client,
        ),
        patch(
            "gengowatcher.native_browser_listener._firefox_rdp_list_tabs",
            side_effect=list_tabs,
        ),
        patch(
            "gengowatcher.native_browser_listener._firefox_rdp_evaluate_json",
            evaluate_json,
        ),
    ):
        listener.run_once()

    evaluate_json.assert_not_awaited()
    assert listener._last_collection_id is None
    assert "Poll iteration failed" not in caplog.text


def test_run_once_ignores_workbench_tab_that_disappears_during_resolve(caplog):
    loop_ids: list[int] = []
    evaluate_json = AsyncMock()

    async def open_client(debug_url):
        loop_ids.append(id(asyncio.get_running_loop()))
        return _FakeRdpClient(loop_ids)

    async def list_tabs(client):
        loop_ids.append(id(asyncio.get_running_loop()))
        return {
            "tabs": [
                {
                    "actor": "tab-descriptor-1",
                    "url": "https://gengo.com/t/workbench/123#!/",
                    "title": "Workbench",
                }
            ]
        }

    listener = NativeBrowserListener(debug_url="ws://127.0.0.1:6000")

    with (
        caplog.at_level(logging.DEBUG),
        patch(
            "gengowatcher.native_browser_listener._open_firefox_rdp_client",
            side_effect=open_client,
        ),
        patch(
            "gengowatcher.native_browser_listener._firefox_rdp_list_tabs",
            side_effect=list_tabs,
        ),
        patch(
            "gengowatcher.native_browser_listener._firefox_rdp_resolve_tab",
            AsyncMock(return_value=None),
        ),
        patch(
            "gengowatcher.native_browser_listener._firefox_rdp_evaluate_json",
            evaluate_json,
        ),
    ):
        listener.run_once()

    evaluate_json.assert_not_awaited()
    assert listener._last_collection_id is None
    assert "Poll iteration failed" not in caplog.text


def test_run_once_normalizes_inner_workbench_payload():
    loop_ids: list[int] = []
    events = []

    async def open_client(debug_url):
        loop_ids.append(id(asyncio.get_running_loop()))
        return _FakeRdpClient(loop_ids)

    async def list_tabs(client):
        loop_ids.append(id(asyncio.get_running_loop()))
        return {
            "tabs": [
                {
                    "url": "https://gengo.com/t/workbench/123#!/",
                    "consoleActor": "console-actor",
                }
            ]
        }

    async def evaluate_json(client, actor, expression, **_kwargs):
        loop_ids.append(id(asyncio.get_running_loop()))
        if "secondsLeft" in expression:
            return {
                "url": "https://gengo.com/t/workbench/123#!/",
                "collectionId": "123",
                "seconds_left": 3600,
            }
        return {
            "result": {
                "source": "window.__INITIAL_STATE__",
                "payload": {
                    "summary": {
                        "order_id": 98765,
                        "lc_src": "ja",
                        "lc_tgt": "en",
                        "rewards_total": 8.13,
                        "unit_count": 263,
                        "allotted_seconds": 7200,
                        "seconds_left": 3600,
                    },
                    "jobs": [
                        {
                            "id": 111,
                            "segments": [
                                {"source_content": "Source text", "target_content": ""}
                            ],
                        }
                    ],
                },
            }
        }

    listener = NativeBrowserListener(debug_url="ws://127.0.0.1:6000")

    with (
        patch(
            "gengowatcher.native_browser_listener._open_firefox_rdp_client",
            side_effect=open_client,
        ),
        patch(
            "gengowatcher.native_browser_listener._firefox_rdp_list_tabs",
            side_effect=list_tabs,
        ),
        patch(
            "gengowatcher.native_browser_listener._firefox_rdp_evaluate_json",
            side_effect=evaluate_json,
        ),
        patch(
            "gengowatcher.native_browser_listener.publish_native_event",
            side_effect=events.append,
        ),
    ):
        listener.run_once()

    assert [event.type for event in events] == [
        "browser.workbench.visible",
        "browser.workbench.details",
        "browser.workbench.status",
    ]
    details = events[1].payload["normalized"]
    assert details["collection_id"] == "123"
    assert details["order_id"] == 98765
    assert details["reward"] == 8.13
    assert details["unit_count"] == 263
    assert details["source_text"] == "Source text"


def test_run_once_clears_visibility_and_status_cache_when_tab_missing():
    loop_ids: list[int] = []

    async def open_client(debug_url):
        loop_ids.append(id(asyncio.get_running_loop()))
        return _FakeRdpClient(loop_ids)

    async def list_tabs(client):
        loop_ids.append(id(asyncio.get_running_loop()))
        return {"tabs": []}

    listener = NativeBrowserListener(debug_url="ws://127.0.0.1:6000")
    listener._last_collection_id = "123"
    listener.detected_collection_id = "123"
    listener.last_workbench_url = "https://gengo.com/t/workbench/123"
    listener._last_visible_payload = {"collection_id": "123"}
    listener._last_status_collection_id = "123"
    listener._last_status_seconds = 42

    with (
        patch(
            "gengowatcher.native_browser_listener._open_firefox_rdp_client",
            side_effect=open_client,
        ),
        patch(
            "gengowatcher.native_browser_listener._firefox_rdp_list_tabs",
            side_effect=list_tabs,
        ),
    ):
        listener.run_once()

    assert listener._last_collection_id is None
    assert listener.detected_collection_id is None
    assert listener.last_workbench_url == ""
    assert listener._last_visible_payload is None
    assert listener._last_status_collection_id is None
    assert listener._last_status_seconds is None
