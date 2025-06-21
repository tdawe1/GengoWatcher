import pytest
import watcher
import logging
from unittest.mock import MagicMock


class DummyConfig:
    def __init__(self, config_dict=None):
        self._config = config_dict or {}

    def get(self, section, key, fallback=None):
        return self._config.get(section, {}).get(key, fallback)

    def save_config(self):
        pass


class DummyState:
    def __init__(self):
        self.last_seen_link = None
        self.total_new_entries_found = 0
        self.save_state_called = False

    def save_state(self):
        self.save_state_called = True


@pytest.fixture
def watcher_instance():
    logger = logging.getLogger("test")
    # Use a more flexible dummy config for different test cases
    return watcher.GengoWatcher(DummyConfig(), DummyState(), logger)


def test_extract_reward(watcher_instance):
    entry = {"title": "Job - Reward: $12.34", "summary": ""}
    assert watcher_instance._extract_reward(entry) == 12.34
    entry = {"title": "Job", "summary": "Reward: US$ 5.50"}
    assert watcher_instance._extract_reward(entry) == 5.50
    entry = {"title": "Job", "summary": "No reward info"}
    assert watcher_instance._extract_reward(entry) == 0.0
    entry = {"title": "Job", "summary": "Reward: $notanumber"}
    assert watcher_instance._extract_reward(entry) == 0.0


def test_open_in_browser_default(monkeypatch):
    """Test that the default system browser is used when no path is configured."""
    logger = logging.getLogger("test")
    config = DummyConfig({"Paths": {"browser_path": "", "browser_args": "{url}"}})
    w = watcher.GengoWatcher(config, DummyState(), logger)

    mock_webbrowser_open = MagicMock()
    monkeypatch.setattr(watcher.webbrowser, "open", mock_webbrowser_open)

    w.open_in_browser("http://example.com")
    mock_webbrowser_open.assert_called_once_with("http://example.com")


def test_handle_exit():
    """Test that state and config are saved on exit."""
    logger = logging.getLogger("test")
    mock_config = MagicMock(spec=DummyConfig)
    mock_state = MagicMock(spec=DummyState)

    w = watcher.GengoWatcher(mock_config, mock_state, logger)
    w.handle_exit()

    mock_state.save_state.assert_called_once()
    mock_config.save_config.assert_called_once()


def test_fetch_rss(monkeypatch):
    """Test the RSS fetching logic."""
    logger = logging.getLogger("test")
    config = DummyConfig(
        {
            "Watcher": {
                "use_custom_user_agent": False,
                "feed_url": "https://example.com/feed",
            }
        }
    )
    w = watcher.GengoWatcher(config, DummyState(), logger)

    class DummyFeed:
        bozo = False
        entries = []

    mock_parse = MagicMock(return_value=DummyFeed())
    monkeypatch.setattr(watcher.feedparser, "parse", mock_parse)

    feed = w.fetch_rss()

    assert isinstance(feed, DummyFeed)
    mock_parse.assert_called_once_with("https://example.com/feed", request_headers={})


def test_process_feed_entries():
    """Test the logic for processing new entries from the feed."""
    logger = logging.getLogger("test")
    config = DummyConfig({"Watcher": {"min_reward": 0.0}})
    state = DummyState()
    w = watcher.GengoWatcher(config, state, logger)

    # Mock the notification to avoid side effects
    w.show_notification = MagicMock()

    entries = [
        {"title": "Job1 - Reward: $10.00", "link": "link1", "summary": ""},
        {"title": "Job2 - Reward: $5.00", "link": "link2", "summary": ""},
    ]

    w.state.last_seen_link = "link2"  # Pretend we've seen the second job
    w._process_feed_entries(entries)

    w.show_notification.assert_called_once()  # Only one new job should trigger a notification
    assert state.save_state_called is True
    assert state.last_seen_link == "link1"
    assert state.total_new_entries_found == 1
