import pytest
import logging
from unittest.mock import MagicMock, patch

# Correctly import from the gengowatcher package
from gengowatcher import watcher
from gengowatcher.config import AppConfig
from gengowatcher.state import AppState


# A fixture to create a mocked watcher instance for tests
@pytest.fixture
def watcher_instance():
    logger = logging.getLogger("test")
    # Use MagicMock for dependencies to isolate the watcher for testing
    mock_config = MagicMock(spec=AppConfig)
    mock_state = MagicMock(spec=AppState)

    # Configure the mock to return default values
    mock_config.get.side_effect = (
        lambda section, key, **kwargs: {
            "Watcher": {
                "min_reward": 0.0,
                "use_custom_user_agent": False,
                "feed_url": "https://example.com/feed",
            },
            "Paths": {"browser_path": "", "browser_args": "{url}"},
            "Network": {"user_agent_email": "test@example.com"},
        }
        .get(section, {})
        .get(key)
    )

    # Use the real GengoWatcher class but with mocked dependencies
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
    # The path to the object to patch must now include the package name
    monkeypatch.setattr(watcher.webbrowser, "open", mock_webbrowser_open)

    watcher_instance.open_in_browser("http://example.com")
    mock_webbrowser_open.assert_called_once_with("http://example.com")


def test_handle_exit(watcher_instance):
    """Test that state and config are saved on exit."""
    watcher_instance.handle_exit()

    # Assert that the save methods on the mocked dependencies were called
    watcher_instance.state.save_state.assert_called_once()
    watcher_instance.config.save_config.assert_called_once()


# Use @patch decorator with the corrected path
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
    # Mock the notification method on the instance to avoid side effects
    watcher_instance.show_notification = MagicMock()

    entries = [
        {"title": "Job1 - Reward: $10.00", "link": "link1", "summary": ""},
        {"title": "Job2 - Reward: $5.00", "link": "link2", "summary": ""},
    ]

    # Set the state on the mocked state object
    watcher_instance.state.last_seen_link = "link2"
    watcher_instance.state.total_new_entries_found = 1

    watcher_instance._process_feed_entries(entries)

    # Assert the test outcome
    watcher_instance.show_notification.assert_called_once()
    watcher_instance.state.save_state.assert_called_once()
    assert watcher_instance.state.last_seen_link == "link1"
    assert watcher_instance.state.total_new_entries_found == 2
