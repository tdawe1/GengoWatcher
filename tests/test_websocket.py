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
    """
    Create and return a GengoWatcher instance preconfigured with mocked AppConfig and AppState for tests.

    The returned watcher uses a test logger, a mocked configuration exposing WebSocket credentials (user_id, user_session, user_key) and logging settings, and a mocked state whose seen_job_ids is a bounded deque. Its _process_new_job method is replaced with a MagicMock to observe invocations during tests.

    Returns:
        GengoWatcher: A watcher instance ready for unit tests with config/state mocks applied.
    """
    logger = logging.getLogger("test_ws")
    mock_config = MagicMock(spec=AppConfig)
    mock_state = MagicMock(spec=AppState)
    mock_state.seen_job_ids = collections.deque(maxlen=50)
    config_dict = {
        "WebSocket": {
            "user_id": 12345,
            "user_session": "fake_session_token",
            "user_key": "fake_browser_user_key",
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

    The websocket auth payload should mirror the browser-aligned credentials
    available in config, including user_key when present.
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

    kwargs = mock_connect.call_args.kwargs
    assert mock_connect.call_args.args[0] == "wss://live-dashboard.gengo.com"
    header_key = (
        "additional_headers"
        if kwargs.get("additional_headers") is not None
        else "extra_headers"
    )
    assert kwargs[header_key] is not None
    assert kwargs[header_key]["Accept-Language"] == "en-GB,en-US;q=0.9,en;q=0.8"
    assert kwargs["ping_interval"] == 20
    assert kwargs["ping_timeout"] == 10
    mock_ws_client.send.assert_awaited_once()
    auth_call = mock_ws_client.send.await_args[0][0]
    assert '"user_id": 12345' in auth_call
    assert '"user_session": "fake_session_token"' in auth_call
    assert '"user_key": "fake_browser_user_key"' in auth_call
    w._process_new_job.assert_called_once_with(
        9876,
        "English > Japanese",
        25.50,
        "https://gengo.com/t/jobs/details/9876",
        source="WebSocket",
        source_meta=job_payload["collection"],
    )


@pytest.mark.asyncio
@patch("gengowatcher.watcher.websockets.connect")
async def test_websocket_logic_processes_job(mock_connect, watcher_instance):
    """
    Verify that the watcher's WebSocket logic authenticates, receives a job message and invokes job processing.

    This test connects the watcher to a mocked WebSocket, ensures the client is opened with the live-dashboard URL and the expected ping parameters, accepts either `additional_headers` or `extra_headers`, sends a single authentication payload containing the configured `user_id`, and processes an incoming `available_collection` message by calling `_process_new_job` with the job id, a "Source > Target" translation label, the numeric reward, the job detail URL and `source="WebSocket"`.
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

    kwargs = mock_connect.call_args.kwargs
    assert mock_connect.call_args.args[0] == "wss://live-dashboard.gengo.com"
    header_key = (
        "additional_headers"
        if kwargs.get("additional_headers") is not None
        else "extra_headers"
    )
    assert kwargs[header_key] is not None
    assert kwargs[header_key]["Accept-Language"] == "en-GB,en-US;q=0.9,en;q=0.8"
    assert kwargs["ping_interval"] == 20
    assert kwargs["ping_timeout"] == 10
    mock_ws_client.send.assert_awaited_once()
    auth_call = mock_ws_client.send.await_args[0][0]
    assert '"user_id": 12345' in auth_call
    assert '"user_key": "fake_browser_user_key"' in auth_call
    w._process_new_job.assert_called_once_with(
        9876,
        "English > Japanese",
        25.50,
        "https://gengo.com/t/jobs/details/9876",
        source="WebSocket",
        source_meta=job_payload["collection"],
    )
