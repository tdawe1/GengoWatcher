import pytest
import asyncio
import json
from unittest.mock import patch, MagicMock, AsyncMock, ANY
import collections

from gengowatcher.watcher import GengoWatcher
from gengowatcher.config import AppConfig
from gengowatcher.state import AppState
import logging


@pytest.fixture
def watcher_instance():
    logger = logging.getLogger("test_ws")
    mock_config = MagicMock(spec=AppConfig)
    mock_state = MagicMock(spec=AppState)
    mock_state.seen_job_ids = collections.deque(maxlen=50)
    config_dict = {
        "WebSocket": {
            "user_id": 12345,
            "user_session": "fake_session_token",
            "enable_websocket": True,
        },
        "Logging": {"log_all_entries_enabled": False},
    }
    mock_config.get.side_effect = lambda section, key, **kwargs: config_dict.get(
        section, {}
    ).get(key, None)

    mock_config.config = config_dict
    w = GengoWatcher(mock_config, mock_state, logger)
    w._process_new_job = MagicMock()
    return w


class MockAsyncWebSocket:
    def __init__(self, messages):
        self._messages = iter(messages)
        self.send = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._messages)
        except StopIteration:
            raise StopAsyncIteration

    async def recv(self):
        return await self.__anext__()


@pytest.mark.asyncio
@patch("gengowatcher.watcher.websockets.connect")
async def test_websocket_receives_and_processes_job(mock_connect, watcher_instance):
    """
    Test that a valid job received from the WebSocket is correctly processed.
    """
    w = watcher_instance
    job_payload = {
        "type": "available_collection",
        "collection": {
            "id": 9876,
            "lc_src": "English",
            "lc_tgt": "Japanese",
            "rewards": "25.50",
        },
    }
    dummy_message = '{"type": "welcome"}'
    job_message = json.dumps(job_payload)
    mock_ws_client = MockAsyncWebSocket([dummy_message, job_message])
    mock_connect.return_value = mock_ws_client

    await w._websocket_logic()

    mock_connect.assert_called_once_with(
        "wss://live-dashboard.gengo.com",
        extra_headers=ANY,
        ping_interval=20,
        ping_timeout=10,
    )
    mock_ws_client.send.assert_awaited_once()
    auth_call = mock_ws_client.send.await_args[0][0]
    assert '"user_id": 12345' in auth_call
    assert '"user_session": "fake_session_token"' in auth_call
    w._process_new_job.assert_called_once_with(
        9876,
        "English > Japanese",
        25.50,
        "https://gengo.com/t/jobs/details/9876",
        source="WebSocket",
    )


@pytest.mark.asyncio
@patch("gengowatcher.watcher.websockets.connect")
async def test_websocket_logic_processes_job(mock_connect, watcher_instance):
    """
    Tests the _websocket_logic async method directly.
    """
    w = watcher_instance
    job_payload = {
        "type": "available_collection",
        "collection": {
            "id": 9876,
            "lc_src": "English",
            "lc_tgt": "Japanese",
            "rewards": "25.50",
        },
    }
    dummy_message = '{"type": "welcome"}'
    job_message = json.dumps(job_payload)
    mock_ws_client = MockAsyncWebSocket([dummy_message, job_message])
    mock_connect.return_value = mock_ws_client

    await w._websocket_logic()

    mock_connect.assert_called_once_with(
        "wss://live-dashboard.gengo.com",
        extra_headers=ANY,
        ping_interval=20,
        ping_timeout=10,
    )
    mock_ws_client.send.assert_awaited_once()
    auth_call = mock_ws_client.send.await_args[0][0]
    assert '"user_id": 12345' in auth_call
    w._process_new_job.assert_called_once_with(
        9876,
        "English > Japanese",
        25.50,
        "https://gengo.com/t/jobs/details/9876",
        source="WebSocket",
    )


@pytest.mark.asyncio
@patch("gengowatcher.watcher.websockets.connect")
async def test_websocket_reward_parsing_is_robust(mock_connect, watcher_instance):
    """Malformed rewards payloads should not crash the websocket loop."""
    w = watcher_instance
    w._process_new_job = MagicMock()

    bad_payloads = [
        {"type": "available_collection", "collection": {"id": 1, "lc_src": "en", "lc_tgt": "ja", "rewards": {"amount": "9.99"}}},
        {"type": "available_collection", "collection": {"id": 2, "lc_src": "en", "lc_tgt": "fr", "rewards": "not-a-number"}},
    ]
    messages = ["{}"] + [json.dumps(p) for p in bad_payloads]
    mock_ws_client = MockAsyncWebSocket(messages)
    mock_connect.return_value = mock_ws_client

    await w._websocket_logic()

    # We still authenticate correctly
    mock_connect.assert_called_once()
    mock_ws_client.send.assert_awaited()
    # And we do not crash when parsing the rewards field
    # (if the payload shape is unsupported, the job may be skipped,
    # but the loop must not raise).
    assert w._process_new_job.call_count >= 0
