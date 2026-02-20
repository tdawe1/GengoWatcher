"""Extended tests for GengoWatcher functionality including new methods."""

import pytest
import asyncio
import logging
import time
import json
from unittest.mock import MagicMock, patch, mock_open
from collections import deque

from gengowatcher.watcher import GengoWatcher
from gengowatcher.config import AppConfig
from gengowatcher.state import AppState


@pytest.fixture
def watcher_with_mocks(mock_config, mock_state, mock_logger):
    """Create a watcher instance with mocked dependencies."""
    watcher = GengoWatcher(mock_config, mock_state, mock_logger)
    return watcher


class TestMonitorStatus:
    """Tests for monitor status tracking."""

    def test_get_monitor_status_all_alive(self, watcher_with_mocks):
        """Test get_monitor_status when all monitors are running."""
        import threading

        # Create mock threads
        watcher_with_mocks._monitor_threads = {
            "rss": threading.Thread(target=lambda: None),
            "websocket": threading.Thread(target=lambda: None),
            "email": threading.Thread(target=lambda: None),
            "website": threading.Thread(target=lambda: None),
        }

        # Start all threads
        for thread in watcher_with_mocks._monitor_threads.values():
            thread.start()

        status = watcher_with_mocks.get_monitor_status()

        # All should report as alive
        assert status["rss"] == "alive"
        assert status["websocket"] == "alive"
        assert status["email"] == "alive"
        assert status["website"] == "alive"

        # Clean up threads
        for thread in watcher_with_mocks._monitor_threads.values():
            thread.join(timeout=1)

    def test_get_monitor_status_disabled(self, watcher_with_mocks):
        """Test get_monitor_status when monitors are disabled."""
        watcher_with_mocks._monitor_threads = {}

        status = watcher_with_mocks.get_monitor_status()

        assert status["rss"] == "disabled"
        assert status["websocket"] == "disabled"
        assert status["email"] == "disabled"
        assert status["website"] == "disabled"

    def test_get_monitor_status_dead_thread(self, watcher_with_mocks):
        """Test get_monitor_status detects dead threads."""
        import threading

        # Create a thread that will immediately finish
        dead_thread = threading.Thread(target=lambda: None)
        dead_thread.start()
        dead_thread.join()  # Wait for it to finish

        watcher_with_mocks._monitor_threads = {"rss": dead_thread}

        status = watcher_with_mocks.get_monitor_status()
        assert status["rss"] == "dead"


class TestMetricsSynchronization:
    """Tests for _sync_monitor_metrics method."""

    def test_sync_email_monitor_metrics(self, watcher_with_mocks):
        """Test syncing metrics from email monitor."""
        mock_email_monitor = MagicMock()
        mock_email_monitor.status = "Connected"
        mock_email_monitor.last_check_time = time.time()
        mock_email_monitor.jobs_found_session = 5

        watcher_with_mocks._email_monitor = mock_email_monitor
        watcher_with_mocks._sync_monitor_metrics()

        assert watcher_with_mocks.email_monitor_status == "Connected"
        assert watcher_with_mocks.email_last_check_time is not None
        assert watcher_with_mocks.email_jobs_found_session == 5

    def test_sync_website_monitor_metrics(self, watcher_with_mocks):
        """Test syncing metrics from website monitor."""
        mock_website_monitor = MagicMock()
        mock_website_monitor.status = "Monitoring"
        mock_website_monitor.last_check_time = time.time()
        mock_website_monitor.jobs_found_session = 3

        watcher_with_mocks._website_monitor = mock_website_monitor
        watcher_with_mocks._sync_monitor_metrics()

        assert watcher_with_mocks.website_monitor_status == "Monitoring"
        assert watcher_with_mocks.website_last_check_time is not None
        assert watcher_with_mocks.website_jobs_found_session == 3

    def test_sync_monitors_no_monitors(self, watcher_with_mocks):
        """Test sync when no monitors are initialized."""
        watcher_with_mocks._sync_monitor_metrics()
        # Should not crash


class TestRawWebSocketMessages:
    """Tests for raw WebSocket message capture."""

    def test_capture_raw_ws_message_receive(self, watcher_with_mocks, mock_config):
        """Test capturing received WebSocket messages."""
        mock_config.get.side_effect = lambda s, k, **kw: {
            ("DebugCategories", "raw"): True
        }.get((s, k), kw.get("fallback", False))

        message = '{"type": "test", "data": "sample"}'
        watcher_with_mocks._capture_raw_ws_message(message, direction="recv")

        messages = watcher_with_mocks.get_raw_ws_messages()
        assert len(messages) > 0
        assert "←" in messages[0]  # Receive arrow
        assert "test" in messages[0]

    def test_capture_raw_ws_message_send(self, watcher_with_mocks, mock_config):
        """Test capturing sent WebSocket messages."""
        mock_config.get.side_effect = lambda s, k, **kw: {
            ("DebugCategories", "raw"): True
        }.get((s, k), kw.get("fallback", False))

        message = '{"type": "auth", "user_id": 123}'
        watcher_with_mocks._capture_raw_ws_message(message, direction="send")

        messages = watcher_with_mocks.get_raw_ws_messages()
        assert len(messages) > 0
        assert "→" in messages[0]  # Send arrow

    def test_clear_raw_ws_messages(self, watcher_with_mocks, mock_config):
        """Test clearing raw WebSocket message buffer."""
        mock_config.get.side_effect = lambda s, k, **kw: {
            ("DebugCategories", "raw"): True
        }.get((s, k), kw.get("fallback", False))

        watcher_with_mocks._capture_raw_ws_message("test", direction="recv")
        assert len(watcher_with_mocks.get_raw_ws_messages()) > 0

        watcher_with_mocks.clear_raw_ws_messages()
        assert len(watcher_with_mocks.get_raw_ws_messages()) == 0

    def test_capture_disabled_when_debug_off(self, watcher_with_mocks, mock_config):
        """Test that capture is disabled when raw debug is off."""
        mock_config.get.side_effect = lambda s, k, **kw: {
            ("DebugCategories", "raw"): False
        }.get((s, k), kw.get("fallback", False))

        watcher_with_mocks._capture_raw_ws_message("test", direction="recv")
        messages = watcher_with_mocks.get_raw_ws_messages()
        assert len(messages) == 0


class TestCancellationIntegration:
    """Tests for job cancellation integration."""

    def test_get_cancellation_stats(self, watcher_with_mocks):
        """Test retrieving cancellation statistics."""
        mock_stats = {
            "cancellations_today": 2,
            "total_cancellations": 10,
            "current_job": "12345",
        }
        watcher_with_mocks.cancellation_manager.get_stats = MagicMock(
            return_value=mock_stats
        )

        stats = watcher_with_mocks.get_cancellation_stats()
        assert stats == mock_stats

    def test_get_cancellation_stats_error_handling(self, watcher_with_mocks):
        """Test error handling when getting cancellation stats fails."""
        watcher_with_mocks.cancellation_manager.get_stats = MagicMock(
            side_effect=Exception("Test error")
        )

        stats = watcher_with_mocks.get_cancellation_stats()
        assert stats is None

    @pytest.mark.asyncio
    async def test_cancel_current_job_async(self, watcher_with_mocks):
        """Test async job cancellation."""
        watcher_with_mocks.cancellation_manager.cancel_current_job = MagicMock(
            return_value=asyncio.Future()
        )
        watcher_with_mocks.cancellation_manager.cancel_current_job.return_value.set_result(
            True
        )

        result = await watcher_with_mocks.cancel_current_job_async()
        assert result is True

    def test_cancel_current_job_sync(self, watcher_with_mocks):
        """Test synchronous job cancellation wrapper."""

        async def mock_cancel():
            return True

        watcher_with_mocks.cancellation_manager.cancel_current_job = mock_cancel

        result = watcher_with_mocks.cancel_current_job_sync()
        assert result is True


class TestConfigurationManagement:
    """Tests for configuration management methods."""

    def test_set_config_value(self, watcher_with_mocks):
        """Test setting configuration values."""
        watcher_with_mocks.set_config_value("Watcher", "min_reward", "10.0")

        watcher_with_mocks.config.set.assert_called_with("Watcher", "min_reward", "10.0")
        watcher_with_mocks.config.save_config.assert_called_once()

    def test_get_config_value(self, watcher_with_mocks):
        """Test getting configuration values."""
        watcher_with_mocks.config.get.return_value = 60

        value = watcher_with_mocks.get_config_value("Watcher", "check_interval")
        assert value == 60

    def test_list_config_values(self, watcher_with_mocks):
        """Test listing all configuration values."""
        mock_parser = MagicMock()
        mock_parser.sections.return_value = ["Watcher", "WebSocket"]
        mock_parser.items.side_effect = lambda s: {
            "Watcher": [("check_interval", "60")],
            "WebSocket": [("enable_websocket", "True")],
        }.get(s, [])

        watcher_with_mocks.config._config_parser = mock_parser

        config_dict = watcher_with_mocks.list_config_values()
        assert "Watcher" in config_dict
        assert "WebSocket" in config_dict

    def test_configure_cancellation_manager(self, watcher_with_mocks, mock_config):
        """Test configuring cancellation manager settings."""
        mock_config.getboolean.return_value = True
        mock_config.getfloat.side_effect = lambda s, k, **kw: {
            ("Cancellation", "min_improvement_ratio"): 2.0,
            ("Cancellation", "extreme_threshold"): 1000.0,
        }.get((s, k), kw.get("fallback", 0.0))

        watcher_with_mocks._configure_cancellation_manager()

        watcher_with_mocks.cancellation_manager.update_settings.assert_called_once()


class TestJobAcceptance:
    """Tests for job acceptance functionality."""

    def test_get_job_acceptance_stats(self, watcher_with_mocks):
        """Test retrieving job acceptance statistics."""
        mock_stats = {
            "accepted_jobs": 5,
            "failed_acceptances": 2,
            "rate_limited": 1,
            "current_rate": 0.5,
            "enabled": True,
        }
        watcher_with_mocks.job_acceptance_engine.get_stats = MagicMock(
            return_value=mock_stats
        )

        stats = watcher_with_mocks.get_job_acceptance_stats()
        assert stats == mock_stats

    def test_get_job_acceptance_stats_no_engine(self):
        """Test stats when job acceptance engine is missing."""
        mock_config = MagicMock()
        mock_state = MagicMock()
        mock_state.seen_job_ids = deque()
        mock_logger = logging.getLogger("test")

        watcher = GengoWatcher(mock_config, mock_state, mock_logger)
        delattr(watcher, "job_acceptance_engine")

        stats = watcher.get_job_acceptance_stats()
        assert stats["accepted_jobs"] == 0
        assert stats["enabled"] is False


class TestNotificationSimulation:
    """Tests for notification simulation."""

    def test_simulate_new_job_notification(self, watcher_with_mocks):
        """Test simulating a new job notification."""
        watcher_with_mocks._process_new_job = MagicMock()

        watcher_with_mocks._simulate_new_job_notification()

        watcher_with_mocks._process_new_job.assert_called_once()
        call_args = watcher_with_mocks._process_new_job.call_args[0]
        assert call_args[1] == "TEST JOB: English > Japanese"
        assert call_args[2] == 12.34
        assert "Test Simulation" in call_args[4]


class TestPromptForConfigValues:
    """Tests for interactive config prompting."""

    def test_prompt_for_config_values_auto_detect(self, watcher_with_mocks):
        """Test auto-detecting missing config values."""
        mock_parser = MagicMock()
        mock_parser.sections.return_value = ["WebSocket"]
        mock_parser.options.return_value = ["user_session"]

        watcher_with_mocks.config._config_parser = mock_parser
        watcher_with_mocks.config.get.return_value = "REPLACE_WITH_YOUR_SESSION_TOKEN"

        with patch("builtins.input", return_value="test_value"):
            watcher_with_mocks.prompt_for_config_values()

    def test_prompt_for_config_values_no_missing(
        self, watcher_with_mocks, capsys, monkeypatch
    ):
        """Test when no config values are missing."""
        mock_parser = MagicMock()
        mock_parser.sections.return_value = []

        watcher_with_mocks.config._config_parser = mock_parser

        # Mock print to capture output
        watcher_with_mocks.prompt_for_config_values()
        captured = capsys.readouterr()
        assert "All configuration values are set" in captured.out

    def test_prompt_sensitive_fields_hidden(self, watcher_with_mocks):
        """Test that sensitive fields use hidden input."""
        import getpass

        mock_parser = MagicMock()
        mock_parser.sections.return_value = ["WebSocket"]
        mock_parser.options.return_value = ["user_session"]

        watcher_with_mocks.config._config_parser = mock_parser
        watcher_with_mocks.config.get.return_value = "REPLACE_WITH_YOUR_SESSION_TOKEN"

        with patch("getpass.getpass", return_value="secret_value"):
            watcher_with_mocks.prompt_for_config_values([("WebSocket", "user_session")])


class TestConfigCompleteness:
    """Tests for is_config_complete method."""

    def test_config_is_complete(self, watcher_with_mocks):
        """Test detecting complete configuration."""
        watcher_with_mocks.config.config = {
            "Watcher": {"feed_url": "https://gengo.com/rss/test"}
        }
        watcher_with_mocks.config.get.return_value = "https://gengo.com/rss/test"

        result = watcher_with_mocks.is_config_complete()
        assert result is True

    def test_config_is_incomplete_placeholder(self, watcher_with_mocks):
        """Test detecting incomplete configuration with placeholder."""
        watcher_with_mocks.config.config = {
            "WebSocket": {"user_session": "REPLACE_WITH_YOUR_SESSION_TOKEN"}
        }
        watcher_with_mocks.config.get.return_value = "REPLACE_WITH_YOUR_SESSION_TOKEN"

        result = watcher_with_mocks.is_config_complete()
        assert result is False

    def test_config_missing_section(self, watcher_with_mocks):
        """Test detecting missing configuration section."""
        watcher_with_mocks.config.config = {}
        watcher_with_mocks.config.get.side_effect = KeyError("Section not found")

        result = watcher_with_mocks.is_config_complete([("Missing", "option")])
        assert result is False


class TestRSSFeedHandling:
    """Tests for RSS feed handling edge cases."""

    def test_fetch_rss_rate_limit_429(self, watcher_with_mocks):
        """Test handling HTTP 429 rate limit response."""
        with patch("gengowatcher.watcher.feedparser.parse") as mock_parse:
            mock_feed = MagicMock()
            mock_feed.status = 429
            mock_feed.bozo = False
            mock_parse.return_value = mock_feed

            result = watcher_with_mocks.fetch_rss()
            assert result is None

    def test_fetch_rss_http_error(self, watcher_with_mocks):
        """Test handling generic HTTP errors."""
        with patch("gengowatcher.watcher.feedparser.parse") as mock_parse:
            mock_feed = MagicMock()
            mock_feed.status = 500
            mock_feed.bozo = False
            mock_parse.return_value = mock_feed

            result = watcher_with_mocks.fetch_rss()
            assert result is None

    def test_fetch_rss_malformed_xml(self, watcher_with_mocks):
        """Test handling malformed XML/HTML response."""
        with patch("gengowatcher.watcher.feedparser.parse") as mock_parse:
            mock_feed = MagicMock()
            mock_feed.bozo = True
            mock_feed.bozo_exception = Exception("mismatched tag")
            mock_parse.return_value = mock_feed

            result = watcher_with_mocks.fetch_rss()
            assert result is None


class TestAsyncJobAcceptance:
    """Tests for async job acceptance wrapper."""

    def test_async_job_acceptance_wrapper_success(self, watcher_with_mocks):
        """Test successful job acceptance via wrapper."""

        async def mock_accept(job_data):
            return True

        watcher_with_mocks.job_acceptance_engine.accept_job = mock_accept
        watcher_with_mocks._on_job_accepted = MagicMock()

        job_data = {"id": "12345", "reward": 25.0, "title": "Test Job"}
        watcher_with_mocks._async_job_acceptance_wrapper(job_data)

        watcher_with_mocks._on_job_accepted.assert_called_once_with(job_data)

    def test_async_job_acceptance_wrapper_failure(self, watcher_with_mocks):
        """Test failed job acceptance via wrapper."""

        async def mock_accept(job_data):
            return False

        watcher_with_mocks.job_acceptance_engine.accept_job = mock_accept
        watcher_with_mocks._on_job_accepted = MagicMock()

        job_data = {"id": "12345", "reward": 25.0, "title": "Test Job"}
        watcher_with_mocks._async_job_acceptance_wrapper(job_data)

        watcher_with_mocks._on_job_accepted.assert_not_called()


class TestOnJobAccepted:
    """Tests for _on_job_accepted callback."""

    def test_on_job_accepted_records_job(self, watcher_with_mocks):
        """Test that accepted jobs are recorded for cancellation tracking."""
        job_data = {"id": "12345", "reward": 50.0}

        watcher_with_mocks._on_job_accepted(job_data)

        watcher_with_mocks.cancellation_manager.set_current_job.assert_called_once_with(
            "12345", 50.0
        )

    def test_on_job_accepted_error_handling(self, watcher_with_mocks):
        """Test error handling when recording accepted job fails."""
        watcher_with_mocks.cancellation_manager.set_current_job = MagicMock(
            side_effect=Exception("Test error")
        )

        job_data = {"id": "12345", "reward": 50.0}
        watcher_with_mocks._on_job_accepted(job_data)  # Should not raise


class TestAsyncCancelCurrentJob:
    """Tests for async job cancellation wrapper."""

    def test_async_cancel_wrapper_success(self, watcher_with_mocks):
        """Test successful job cancellation via wrapper."""
        watcher_with_mocks.cancellation_manager.current_job_id = "12345"
        watcher_with_mocks.cancel_current_job_sync = MagicMock(return_value=True)

        upcoming_job = {"id": "67890", "reward": 100.0}
        watcher_with_mocks._async_cancel_current_job_wrapper(upcoming_job)

        watcher_with_mocks.cancel_current_job_sync.assert_called_once()

    def test_async_cancel_wrapper_failure(self, watcher_with_mocks):
        """Test failed job cancellation via wrapper."""
        watcher_with_mocks.cancel_current_job_sync = MagicMock(return_value=False)

        upcoming_job = {"id": "67890", "reward": 100.0}
        watcher_with_mocks._async_cancel_current_job_wrapper(upcoming_job)

        watcher_with_mocks.cancel_current_job_sync.assert_called_once()


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_watcher_initialization_low_check_interval(self, mock_config, mock_state, mock_logger):
        """Test that very low check_interval is validated."""
        mock_config.get.side_effect = lambda s, k, **kw: {
            ("Watcher", "check_interval"): 0
        }.get((s, k), kw.get("fallback", 60))

        GengoWatcher(mock_config, mock_state, mock_logger)

        # Should have been corrected to minimum
        assert mock_config.set.called

    def test_extract_reward_with_various_formats(self, watcher_with_mocks):
        """Test reward extraction with various currency formats."""
        # Test with US$ prefix
        entry = {"title": "Job - Reward: US$12.50", "summary": ""}
        assert watcher_with_mocks._extract_reward(entry) == 12.5

        # Test with $ prefix
        entry = {"title": "Job", "summary": "Reward: $25"}
        assert watcher_with_mocks._extract_reward(entry) == 25.0

        # Test with no currency symbol
        entry = {"title": "Job", "summary": "Reward: 10.75"}
        assert watcher_with_mocks._extract_reward(entry) == 10.75

    def test_process_new_job_below_min_reward(self, watcher_with_mocks, mock_config):
        """Test that jobs below min_reward are filtered out."""
        mock_config.get.side_effect = lambda s, k, **kw: {
            ("Watcher", "min_reward"): 10.0
        }.get((s, k), kw.get("fallback", 0.0))

        watcher_with_mocks.show_notification = MagicMock()

        # Job below minimum reward
        watcher_with_mocks._process_new_job(
            123, "Low Reward Job", 5.0, "http://example.com", "RSS"
        )

        # Should not show notification for filtered job
        watcher_with_mocks.show_notification.assert_not_called()

    def test_process_feed_entries_empty_list(self, watcher_with_mocks):
        """Test processing empty feed entries list."""
        watcher_with_mocks._process_feed_entries([])
        # Should handle empty list gracefully

    def test_process_feed_entries_no_link(self, watcher_with_mocks):
        """Test processing feed entries with missing links."""
        entries = [
            {"title": "Job 1"},  # No link field
            {"title": "Job 2", "link": None},  # Null link
        ]

        watcher_with_mocks._process_feed_entries(entries)
        # Should skip entries without valid links

    def test_handle_exit_double_call(self, watcher_with_mocks):
        """Test that handle_exit is idempotent."""
        watcher_with_mocks._shutdown_initiated = False

        watcher_with_mocks.handle_exit()
        first_save_count = watcher_with_mocks.state.save_state.call_count

        # Call again - should not execute again
        watcher_with_mocks.handle_exit()
        second_save_count = watcher_with_mocks.state.save_state.call_count

        assert first_save_count == second_save_count
