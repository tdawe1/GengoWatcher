import pytest
import logging
from unittest.mock import MagicMock, patch
import collections

from gengowatcher import watcher
from gengowatcher.config import AppConfig
from gengowatcher.state import AppState


@pytest.fixture
def watcher_instance():
    logger = logging.getLogger("test")
    mock_config = MagicMock(spec=AppConfig)
    mock_state = MagicMock(spec=AppState)
    mock_state.seen_job_ids = collections.deque(maxlen=50)

    config_data = {
        "Watcher": {
            "min_reward": 0.0,
            "use_custom_user_agent": False,
            "feed_url": "https://example.com/feed",
        },
        "Paths": {"browser_path": "", "browser_args": "{url}"},
        "Network": {"user_agent_email": "test@example.com"},
        "Logging": {"log_all_entries_enabled": False},
        "AutoAccept": {
            "enabled": False,
            "job_sources": "rss,websocket",
            "min_reward": 0.0,
            "max_reward": 999999.0,
        },
    }
    mock_config.get.side_effect = lambda section, key, **kwargs: config_data.get(
        section, {}
    ).get(key)
    mock_config.config = config_data
    w = watcher.GengoWatcher(mock_config, mock_state, logger)
    return w


@pytest.mark.parametrize(
    "entry, expected_reward",
    [
        ({"title": "Job - Reward: $12.34", "summary": ""}, 12.34),
        ({"title": "Job", "summary": "Reward: US$ 5.50"}, 5.50),
        ({"title": "Job", "summary": "No reward info"}, 0.0),
        ({"title": "Job", "summary": "Reward: $notanumber"}, 0.0),
    ],
)
def test_extract_reward(watcher_instance, entry, expected_reward):
    assert watcher_instance._extract_reward(entry) == expected_reward


def test_open_in_browser_default(monkeypatch, watcher_instance):
    """Test that the default system browser is used when no path is configured."""
    mock_webbrowser_open = MagicMock()
    monkeypatch.setattr(watcher.webbrowser, "open", mock_webbrowser_open)

    watcher_instance.open_in_browser("http://example.com")
    mock_webbrowser_open.assert_called_once_with("http://example.com")


def test_handle_exit(watcher_instance):
    """Test that state is saved on exit.

    Note: The actual implementation only calls save_state(), not save_config().
    The config is typically not modified during runtime.
    """
    watcher_instance.handle_exit()

    watcher_instance.state.save_state.assert_called_once()
    # Note: save_config is not called in handle_exit - config changes are saved elsewhere


@patch("gengowatcher.watcher.feedparser.parse")
def test_fetch_rss(mock_parse, watcher_instance):
    """Test the RSS fetching logic."""

    class DummyFeed:
        bozo = False
        entries = []

    mock_parse.return_value = DummyFeed()
    feed = watcher_instance.fetch_rss()

    assert isinstance(feed, DummyFeed)
    mock_parse.assert_called_once_with("https://example.com/feed", request_headers={})


def test_process_feed_entries(watcher_instance):
    """Test the logic for processing new entries from the feed."""
    watcher_instance._process_new_job = MagicMock()

    entries = [
        {"title": "Job1", "link": "https://gengo.com/t/jobs/details/101/"},
        {"title": "Job2", "link": "https://gengo.com/t/jobs/details/102/"},
    ]

    watcher_instance.state.last_seen_rss_link = "https://gengo.com/t/jobs/details/102/"

    watcher_instance._process_feed_entries(entries)

    watcher_instance._process_new_job.assert_called_once()


def test_process_new_job_deduplication(watcher_instance):
    """Test that the same job is not processed twice."""
    w = watcher_instance
    w.show_notification = MagicMock()
    mock_state = w.state

    mock_state.total_new_entries_found = 0
    mock_state.seen_job_ids = collections.deque(maxlen=50)

    w._process_new_job(123, "New Job", 10.0, "http://example.com/123", "Test")
    assert w.show_notification.call_count == 1
    mock_state.save_state.assert_called_once()
    assert 123 in mock_state.seen_job_ids
    assert mock_state.total_new_entries_found == 1

    w._process_new_job(123, "New Job", 10.0, "http://example.com/123", "Test")
    assert w.show_notification.call_count == 1
    assert mock_state.save_state.call_count == 1
    assert mock_state.total_new_entries_found == 1

    w._process_new_job(456, "Another Job", 5.0, "http://example.com/456", "Test")
    assert w.show_notification.call_count == 2
    assert mock_state.save_state.call_count == 2
    assert 456 in mock_state.seen_job_ids
    assert mock_state.total_new_entries_found == 2


def test_process_new_job_callback(watcher_instance):
    """Test that on_job_added_callback is invoked correctly with job_data."""
    w = watcher_instance
    w.show_notification = MagicMock()
    mock_callback = MagicMock()
    w.on_job_added_callback = mock_callback
    w.job_acceptance_engine.is_job_eligible = MagicMock(return_value=False)
    mock_state = w.state

    mock_state.total_new_entries_found = 0
    mock_state.seen_job_ids = collections.deque(maxlen=50)

    # Process a new job
    w._process_new_job(123, "New Job", 10.0, "http://example.com/123", "RSS")

    # Verify callback was called with correct job_data
    assert mock_callback.call_count == 1
    call_args = mock_callback.call_args[0][0]
    assert call_args["id"] == "123"
    assert call_args["title"] == "New Job"
    assert call_args["reward"] == 10.0
    assert call_args["url"] == "http://example.com/123"
    assert call_args["source"] == "RSS"
    assert "timestamp" in call_args

    # Process a duplicate job - callback should not be called again
    w._process_new_job(123, "New Job", 10.0, "http://example.com/123", "RSS")
    assert mock_callback.call_count == 1

    # Process another new job - callback should be called again
    w._process_new_job(456, "Another Job", 5.0, "http://example.com/456", "WebSocket")
    assert mock_callback.call_count == 2
    call_args = mock_callback.call_args[0][0]
    assert call_args["id"] == "456"
    assert call_args["source"] == "WebSocket"


def test_process_new_job_callback_order(watcher_instance):
    """Ensure the job callback runs after the job is added to state."""
    w = watcher_instance
    w.show_notification = MagicMock()
    events = []
    recorded_job_data = []

    def record_job_add(job_data):
        events.append("add")
        recorded_job_data.append(job_data)

    callback = MagicMock(side_effect=lambda job_data: events.append("callback"))
    w.state.add_job = MagicMock(side_effect=record_job_add)
    w.on_job_added_callback = callback
    w.job_acceptance_engine.is_job_eligible = MagicMock(return_value=False)
    w.state.total_new_entries_found = 0
    w.state.seen_job_ids = collections.deque(maxlen=50)

    w._process_new_job(123, "Ordered Job", 8.0, "http://example.com/123", "RSS")

    assert events == ["add", "callback"]
    assert recorded_job_data
    callback.assert_called_once()
    assert recorded_job_data[0] is callback.call_args[0][0]


def test_process_new_job_callback_exception_handling(watcher_instance):
    """Test that exceptions in callback are caught and logged."""
    w = watcher_instance
    w.show_notification = MagicMock()
    mock_callback = MagicMock(side_effect=Exception("Callback error"))
    w.on_job_added_callback = mock_callback
    w.job_acceptance_engine.is_job_eligible = MagicMock(return_value=False)
    mock_state = w.state

    mock_state.total_new_entries_found = 0
    mock_state.seen_job_ids = collections.deque(maxlen=50)

    # Process a new job - should not raise exception despite callback error
    w._process_new_job(123, "New Job", 10.0, "http://example.com/123", "RSS")

    # Verify callback was called
    assert mock_callback.call_count == 1
    # Verify job was still processed successfully
    assert 123 in mock_state.seen_job_ids
    assert mock_state.total_new_entries_found == 1
