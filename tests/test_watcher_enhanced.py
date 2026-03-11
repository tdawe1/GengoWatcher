"""Enhanced tests for GengoWatcher - covering new and enhanced methods."""

import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import collections
import logging

from gengowatcher.watcher import GengoWatcher
from gengowatcher.config import AppConfig
from gengowatcher.state import AppState


@pytest.fixture
def watcher_instance(mock_config, mock_state, mock_logger):
    """Create a GengoWatcher instance for testing."""
    watcher = GengoWatcher(mock_config, mock_state, mock_logger)
    return watcher


class TestWatcherInitialization:
    """Test GengoWatcher initialization."""

    def test_watcher_initializes_with_valid_config(
        self, mock_config, mock_state, mock_logger
    ):
        """Test that watcher initializes with valid configuration."""
        watcher = GengoWatcher(mock_config, mock_state, mock_logger)

        assert watcher.config == mock_config
        assert watcher.state == mock_state
        assert watcher.logger == mock_logger

    def test_watcher_validates_check_interval(
        self, mock_config, mock_state, mock_logger
    ):
        """Test that watcher validates check_interval minimum."""
        # Set check_interval to invalid low value
        mock_config.get.side_effect = lambda s, k, **kw: (
            0
            if (s, k) == ("Watcher", "check_interval")
            else mock_config.config.get(s, {}).get(k, kw.get("fallback"))
        )

        GengoWatcher(mock_config, mock_state, mock_logger)

        # Should have been corrected to minimum
        mock_config.set.assert_called()

    def test_watcher_initializes_cancellation_manager(self, watcher_instance):
        """Test that cancellation manager is initialized."""
        assert hasattr(watcher_instance, "cancellation_manager")
        assert watcher_instance.cancellation_manager is not None

    def test_watcher_initializes_job_acceptance_engine(self, watcher_instance):
        """Test that job acceptance engine is initialized."""
        assert hasattr(watcher_instance, "job_acceptance_engine")
        assert watcher_instance.job_acceptance_engine is not None


class TestMonitorStatus:
    """Test monitor status tracking."""

    def test_get_monitor_status_returns_dict(self, watcher_instance):
        """Test that get_monitor_status returns a dictionary."""
        status = watcher_instance.get_monitor_status()

        assert isinstance(status, dict)
        assert "rss" in status
        assert "websocket" in status
        assert "email" in status
        assert "website" in status

    def test_get_monitor_status_initial_state(self, watcher_instance):
        """Test monitor status before any monitors start."""
        status = watcher_instance.get_monitor_status()

        # All should be disabled initially
        assert status["rss"] == "disabled"
        assert status["websocket"] == "disabled"
        assert status["email"] == "disabled"
        assert status["website"] == "disabled"

    def test_sync_monitor_metrics(self, watcher_instance):
        """Test syncing metrics from monitors."""
        # Create mock monitors
        watcher_instance._email_monitor = MagicMock()
        watcher_instance._email_monitor.status = "Polling"
        watcher_instance._email_monitor.last_check_time = 123456.0
        watcher_instance._email_monitor.jobs_found_session = 5

        watcher_instance._sync_monitor_metrics()

        assert watcher_instance.email_monitor_status == "Polling"
        assert watcher_instance.email_last_check_time == 123456.0
        assert watcher_instance.email_jobs_found_session == 5


class TestRawWSMessages:
    """Test raw WebSocket message capture."""

    def test_capture_raw_ws_message_when_enabled(self, watcher_instance, mock_config):
        """Test capturing raw WS messages when debug is enabled."""
        mock_config.get.side_effect = lambda s, k: True if k == "raw" else None

        watcher_instance._capture_raw_ws_message("test message", "recv")

        messages = watcher_instance.get_raw_ws_messages()
        assert len(messages) > 0

    def test_capture_raw_ws_message_when_disabled(self, watcher_instance, mock_config):
        """Test not capturing when raw debug is disabled."""
        mock_config.get.side_effect = lambda s, k: False if k == "raw" else None

        watcher_instance._capture_raw_ws_message("test message", "recv")

        messages = watcher_instance.get_raw_ws_messages()
        assert len(messages) == 0

    def test_get_raw_ws_messages_returns_list(self, watcher_instance):
        """Test that get_raw_ws_messages returns a list."""
        messages = watcher_instance.get_raw_ws_messages()
        assert isinstance(messages, list)

    def test_clear_raw_ws_messages(self, watcher_instance, mock_config):
        """Test clearing raw WS message buffer."""
        mock_config.get.side_effect = lambda s, k: True if k == "raw" else None

        watcher_instance._capture_raw_ws_message("message 1", "recv")
        watcher_instance._capture_raw_ws_message("message 2", "send")

        watcher_instance.clear_raw_ws_messages()

        messages = watcher_instance.get_raw_ws_messages()
        assert len(messages) == 0


class TestJobProcessing:
    """Test job processing methods."""

    def test_process_new_job_deduplication(self, watcher_instance):
        """Test that duplicate jobs are not processed twice."""
        watcher_instance.show_notification = MagicMock()

        # Process same job twice
        watcher_instance._process_new_job(
            123, "Test Job", 10.0, "http://test.com", "Test"
        )
        watcher_instance._process_new_job(
            123, "Test Job", 10.0, "http://test.com", "Test"
        )

        # Should only show notification once
        assert watcher_instance.show_notification.call_count == 1

    def test_process_new_job_stores_in_state(self, watcher_instance):
        """Test that new jobs are stored in state."""
        watcher_instance.show_notification = MagicMock()
        watcher_instance.state.add_job = MagicMock()

        watcher_instance._process_new_job(
            123, "Test Job", 10.0, "http://test.com", "Test"
        )

        # Should call add_job
        watcher_instance.state.add_job.assert_called_once()

    def test_process_new_job_with_min_reward_filter(
        self, watcher_instance, mock_config
    ):
        """Test job filtering by minimum reward."""
        mock_config.get.side_effect = lambda _s, key: (
            50.0 if key == "min_reward" else None
        )
        watcher_instance.show_notification = MagicMock()

        # Job below minimum
        watcher_instance._process_new_job(
            123, "Low Value Job", 10.0, "http://test.com", "Test"
        )

        # Should not show notification
        assert watcher_instance.show_notification.call_count == 0


class TestCancellationIntegration:
    """Test cancellation manager integration."""

    def test_get_cancellation_stats(self, watcher_instance):
        """Test getting cancellation statistics."""
        mock_stats = {"jobs_cancelled": 5, "current_job_id": None}
        watcher_instance.cancellation_manager.get_stats = MagicMock(
            return_value=mock_stats
        )

        stats = watcher_instance.get_cancellation_stats()

        assert stats == mock_stats

    def test_cancel_current_job_sync(self, watcher_instance):
        """Test synchronous job cancellation."""
        watcher_instance.cancellation_manager.cancel_current_job = AsyncMock(
            return_value=True
        )

        result = watcher_instance.cancel_current_job_sync()

        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_current_job_async(self, watcher_instance):
        """Test asynchronous job cancellation."""
        watcher_instance.cancellation_manager.cancel_current_job = AsyncMock(
            return_value=True
        )

        result = await watcher_instance.cancel_current_job_async()

        assert result is True


class TestConfigManagement:
    """Test configuration management methods."""

    def test_set_config_value(self, watcher_instance):
        """Test setting configuration values."""
        watcher_instance.set_config_value("Watcher", "check_interval", "60")

        watcher_instance.config.set.assert_called_with(
            "Watcher", "check_interval", "60"
        )
        watcher_instance.config.save_config.assert_called()

    def test_get_config_value(self, watcher_instance):
        """Test getting configuration values."""
        watcher_instance.config.get.side_effect = lambda *_args, **_kwargs: "test_value"

        value = watcher_instance.get_config_value("Watcher", "check_interval")

        assert value == "test_value"

    def test_list_config_values(self, watcher_instance):
        """Test listing all configuration values."""
        watcher_instance.config._config_parser = MagicMock()
        watcher_instance.config._config_parser.sections.return_value = ["Watcher"]
        watcher_instance.config._config_parser.items.return_value = [("key", "value")]

        config_dict = watcher_instance.list_config_values()

        assert isinstance(config_dict, dict)


class TestNotificationTest:
    """Test notification testing functionality."""

    def test_run_notify_test(self, watcher_instance):
        """Test running notification test."""
        watcher_instance.show_notification = MagicMock()

        watcher_instance.run_notify_test()

        # Should call show_notification
        watcher_instance.show_notification.assert_called_once()

    def test_simulate_new_job_notification(self, watcher_instance):
        """Test simulating a new job notification."""
        watcher_instance._process_new_job = MagicMock()

        watcher_instance._simulate_new_job_notification()

        # Should call _process_new_job with fake data
        watcher_instance._process_new_job.assert_called_once()


class TestShutdownHandling:
    """Test shutdown and cleanup."""

    def test_handle_exit_saves_state(self, watcher_instance):
        """Test that handle_exit saves state."""
        watcher_instance.handle_exit()

        watcher_instance.state.save_state.assert_called()

    def test_handle_exit_sets_shutdown_event(self, watcher_instance):
        """Test that handle_exit sets shutdown event."""
        watcher_instance.handle_exit()

        assert watcher_instance.shutdown_event.is_set()

    def test_handle_exit_idempotent(self, watcher_instance):
        """Test that handle_exit can be called multiple times safely."""
        watcher_instance.handle_exit()
        watcher_instance.handle_exit()

        # Should not crash
        assert True


class TestJobAcceptanceIntegration:
    """Test job acceptance engine integration."""

    def test_get_job_acceptance_stats(self, watcher_instance):
        """Test getting job acceptance statistics."""
        mock_stats = {
            "accepted_jobs": 10,
            "failed_acceptances": 2,
            "rate_limited": 1,
            "current_rate": 0.5,
            "enabled": True,
        }
        watcher_instance.job_acceptance_engine.get_stats = MagicMock(
            return_value=mock_stats
        )

        stats = watcher_instance.get_job_acceptance_stats()

        assert stats == mock_stats

    def test_get_job_acceptance_stats_no_engine(self, watcher_instance):
        """Test getting stats when engine doesn't exist."""
        del watcher_instance.job_acceptance_engine

        stats = watcher_instance.get_job_acceptance_stats()

        # Should return default stats
        assert stats["accepted_jobs"] == 0
        assert stats["enabled"] is False


class TestConfigValidation:
    """Test configuration validation."""

    def test_is_config_complete_with_valid_config(self, watcher_instance):
        """Test config completeness check with valid config."""
        watcher_instance.config.config = {"Watcher": {"check_interval": 60}}
        watcher_instance.config.get.side_effect = lambda s, k, **kw: (
            60 if (s, k) == ("Watcher", "check_interval") else kw.get("fallback")
        )

        result = watcher_instance.is_config_complete()

        assert result is True

    def test_is_config_complete_with_placeholder(self, watcher_instance):
        """Test config completeness check with placeholder values."""
        watcher_instance.config.config = {
            "Watcher": {"feed_url": "REPLACE_WITH_YOUR_SESSION_TOKEN"}
        }
        watcher_instance.config.get.side_effect = lambda s, k, **kw: (
            "REPLACE_WITH_YOUR_SESSION_TOKEN"
            if (s, k) == ("Watcher", "feed_url")
            else kw.get("fallback")
        )

        result = watcher_instance.is_config_complete([("Watcher", "feed_url")])

        assert result is False

    def test_prompt_for_config_values(self, watcher_instance, monkeypatch, tmp_path):
        """Test prompting for configuration values."""
        # Mock input
        inputs = iter(["test_value"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        monkeypatch.setattr("getpass.getpass", lambda _prompt: "test_value")
        config_path = tmp_path / "config.ini"
        config_path.write_text("[Watcher]\ntest_key=REPLACE_WITH_YOUR_SESSION_TOKEN\n")
        watcher_instance.config.CONFIG_FILE = str(config_path)

        watcher_instance.prompt_for_config_values([("Watcher", "test_key")])

        # Should call set_config_value
        watcher_instance.config.set.assert_called()

    def test_is_config_complete_ignores_disabled_optional_fields(
        self, watcher_instance
    ):
        """Disabled feature placeholders should not make core config incomplete."""
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("Watcher", "feed_url"): "https://gengo.com/rss/test",
            ("Watcher", "check_interval"): 45,
            ("WebSocket", "enable_websocket"): True,
            ("WebSocket", "user_id"): 789487,
            ("WebSocket", "user_session"): "live-session-token",
            ("WebSocket", "user_key"): "REPLACE_WITH_YOUR_USER_KEY",
            ("WebsiteMonitor", "enabled"): False,
            ("AutoAccept", "enabled"): False,
            ("BrowserWorker", "enabled"): False,
        }.get((s, k), kw.get("fallback"))

        result = watcher_instance.is_config_complete()

        assert result is True


class TestFeedProcessing:
    """Test RSS feed processing."""

    def test_process_feed_entries_empty(self, watcher_instance):
        """Test processing empty feed entries."""
        watcher_instance._process_feed_entries([])

        # Should not crash
        assert True

    def test_process_feed_entries_with_jobs(self, watcher_instance):
        """Test processing feed entries with actual jobs."""
        watcher_instance._process_new_job = MagicMock()
        watcher_instance._log_all_entries = MagicMock()

        entries = [
            {"title": "Job1", "link": "https://gengo.com/t/jobs/details/101/"},
            {"title": "Job2", "link": "https://gengo.com/t/jobs/details/102/"},
        ]

        watcher_instance.state.last_seen_rss_link = None

        watcher_instance._process_feed_entries(entries)

        # Should process both jobs
        assert watcher_instance._process_new_job.call_count == 2

    def test_extract_reward_from_entry(self, watcher_instance):
        """Test extracting reward from RSS entry."""
        entry = {"title": "Job - Reward: $25.50", "summary": ""}

        reward = watcher_instance._extract_reward(entry)

        assert reward == 25.50

    def test_extract_reward_no_match(self, watcher_instance):
        """Test extracting reward when no match found."""
        entry = {"title": "Job", "summary": "No reward info"}

        reward = watcher_instance._extract_reward(entry)

        assert reward == 0.0


class TestBrowserIntegration:
    """Test browser opening functionality."""

    def test_open_in_browser_default(self, watcher_instance, monkeypatch):
        """Test opening URL with default browser."""
        import webbrowser

        mock_open = MagicMock()
        monkeypatch.setattr(webbrowser, "open", mock_open)

        watcher_instance.open_in_browser("http://example.com")

        mock_open.assert_called_once_with("http://example.com")

    def test_open_in_browser_with_error(self, watcher_instance, monkeypatch):
        """Test opening URL when exception occurs."""
        import webbrowser

        mock_open = MagicMock(side_effect=Exception("Browser error"))
        monkeypatch.setattr(webbrowser, "open", mock_open)

        # Should not crash
        watcher_instance.open_in_browser("http://example.com")
        assert True


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_process_new_job_with_invalid_url(self, watcher_instance):
        """Test processing job with invalid URL."""
        watcher_instance.show_notification = MagicMock()

        watcher_instance._process_new_job(123, "Test", 10.0, "not a url", "Test")

        # Should handle gracefully
        assert True

    def test_fetch_rss_with_network_error(self, watcher_instance):
        """Test RSS fetching with network error."""
        with patch("gengowatcher.watcher.feedparser.parse") as mock_parse:
            mock_parse.side_effect = Exception("Network error")

            feed = watcher_instance.fetch_rss()

            assert feed is None

    def test_show_notification_with_all_options(self, watcher_instance, mock_config):
        """Test notification with all options enabled."""
        mock_config.get.side_effect = lambda s, k, **kw: {
            ("Watcher", "enable_notifications"): True,
            ("Watcher", "enable_sound"): True,
            ("Paths", "notification_icon_path"): "",
            ("Paths", "sound_file"): "assets/alert.wav",
            ("Paths", "browser_path"): "",
            ("Paths", "browser_args"): "{url}",
        }.get((s, k), kw.get("fallback", ""))

        watcher_instance.show_notification(
            message="Test",
            title="Title",
            play_sound=True,
            open_link=True,
            url="http://example.com",
        )

        # Should complete without error
        assert True
