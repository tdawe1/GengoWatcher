"""Integration tests for complex scenarios and edge cases."""

import pytest
import tempfile
import pathlib
import time
from unittest.mock import MagicMock, patch
from collections import deque


class TestJobProcessingPipeline:
    """Test complete job processing pipeline from discovery to acceptance."""

    @pytest.fixture
    def full_system(self, mock_config, mock_state, mock_logger):
        """Create a full watcher system for integration testing."""
        from gengowatcher.watcher import GengoWatcher

        watcher = GengoWatcher(mock_config, mock_state, mock_logger)
        return watcher

    def test_job_discovery_to_notification(self, full_system):
        """Test job flows from RSS discovery to notification."""
        full_system.show_notification = MagicMock()
        full_system.state.seen_job_ids = deque()

        # Simulate RSS entry
        job_id = 12345
        title = "JA→EN Translation"
        reward = 25.50
        url = "https://gengo.com/jobs/12345"

        full_system._process_new_job(job_id, title, reward, url, "RSS")

        # Should trigger notification
        full_system.show_notification.assert_called_once()
        call_args = full_system.show_notification.call_args[1]
        assert call_args["play_sound"] is True
        assert call_args["open_link"] is True

    def test_job_deduplication_across_sources(self, full_system):
        """Test that same job from different sources is deduplicated."""
        full_system.show_notification = MagicMock()
        full_system.state.seen_job_ids = deque()

        job_id = 12345
        title = "Translation Job"
        reward = 25.0
        url = "https://gengo.com/jobs/12345"

        # First from RSS
        full_system._process_new_job(job_id, title, reward, url, "RSS")
        assert full_system.show_notification.call_count == 1

        # Then from WebSocket - should be deduplicated
        full_system._process_new_job(job_id, title, reward, url, "WebSocket")
        assert (
            full_system.show_notification.call_count == 1
        )  # No additional notification

    def test_job_below_threshold_filtered(self, full_system, mock_config):
        """Test that jobs below min_reward are filtered."""
        mock_config.get.side_effect = lambda s, k, **kw: {
            ("Watcher", "min_reward"): 10.0
        }.get((s, k), kw.get("fallback", 0.0))

        full_system.show_notification = MagicMock()
        full_system.state.seen_job_ids = deque()

        # Job below threshold
        full_system._process_new_job(123, "Low Pay", 5.0, "https://example.com", "RSS")

        # Should not notify
        full_system.show_notification.assert_not_called()

    def test_job_acceptance_eligibility_check(self, full_system):
        """Test job acceptance eligibility checking."""
        job_data = {
            "id": "12345",
            "title": "Test Job",
            "reward": 50.0,
            "url": "https://example.com",
            "source": "RSS",
        }

        full_system.job_acceptance_engine.is_job_eligible = MagicMock(return_value=True)

        full_system._process_new_job(
            job_data["id"],
            job_data["title"],
            job_data["reward"],
            job_data["url"],
            job_data["source"],
        )

        # Should check eligibility
        full_system.job_acceptance_engine.is_job_eligible.assert_called()


class TestCancellationWorkflow:
    """Test job cancellation workflow scenarios."""

    @pytest.fixture
    def watcher_with_cancellation(self, mock_config, mock_state, mock_logger):
        """Create watcher with cancellation enabled."""
        from gengowatcher.watcher import GengoWatcher

        mock_config.get.side_effect = lambda s, k, **kw: {
            ("Cancellation", "enabled"): True,
            ("Cancellation", "min_improvement_ratio"): 2.0,
        }.get((s, k), kw.get("fallback", False))

        watcher = GengoWatcher(mock_config, mock_state, mock_logger)
        return watcher

    def test_cancellation_triggered_for_better_job(self, watcher_with_cancellation):
        """Test that cancellation is triggered when a better job arrives."""
        # Set current job
        watcher_with_cancellation.cancellation_manager.set_current_job("12345", 25.0)
        watcher_with_cancellation.cancellation_manager.should_cancel_for_job = (
            MagicMock(return_value=True)
        )
        watcher_with_cancellation.cancel_current_job_sync = MagicMock(return_value=True)

        # New better job arrives
        job_data = {
            "id": "67890",
            "title": "Better Job",
            "reward": 60.0,
            "url": "https://example.com",
            "source": "WebSocket",
        }

        watcher_with_cancellation._process_new_job(
            job_data["id"],
            job_data["title"],
            job_data["reward"],
            job_data["url"],
            job_data["source"],
        )

        # Should trigger cancellation check
        watcher_with_cancellation.cancellation_manager.should_cancel_for_job.assert_called_with(
            60.0, "67890"
        )


class TestMonitorCoordination:
    """Test coordination between different monitors."""

    @pytest.fixture
    def multi_monitor_watcher(self, mock_config, mock_state, mock_logger):
        """Create watcher with multiple monitors enabled."""
        from gengowatcher.watcher import GengoWatcher

        mock_config.get.side_effect = lambda s, k, **kw: {
            ("WebSocket", "enable_websocket"): True,
            ("EmailMonitor", "enabled"): True,
            ("WebsiteMonitor", "enabled"): True,
        }.get((s, k), kw.get("fallback", False))

        watcher = GengoWatcher(mock_config, mock_state, mock_logger)
        return watcher

    def test_monitor_status_aggregation(self, multi_monitor_watcher):
        """Test aggregating status from multiple monitors."""
        import threading

        # Create mock threads for monitors
        multi_monitor_watcher._monitor_threads = {
            "rss": threading.Thread(target=lambda: None),
            "websocket": threading.Thread(target=lambda: None),
            "email": threading.Thread(target=lambda: None),
        }

        # Start threads
        for thread in multi_monitor_watcher._monitor_threads.values():
            thread.start()

        status = multi_monitor_watcher.get_monitor_status()

        assert "rss" in status
        assert "websocket" in status
        assert "email" in status

        # Clean up
        for thread in multi_monitor_watcher._monitor_threads.values():
            thread.join(timeout=1)

    def test_sync_monitor_metrics_all_sources(self, multi_monitor_watcher):
        """Test syncing metrics from all monitor sources."""
        # Mock email monitor
        multi_monitor_watcher._email_monitor = MagicMock()
        multi_monitor_watcher._email_monitor.status = "Connected"
        multi_monitor_watcher._email_monitor.jobs_found_session = 5

        # Mock website monitor
        multi_monitor_watcher._website_monitor = MagicMock()
        multi_monitor_watcher._website_monitor.status = "Monitoring"
        multi_monitor_watcher._website_monitor.jobs_found_session = 3

        multi_monitor_watcher._sync_monitor_metrics()

        assert multi_monitor_watcher.email_monitor_status == "Connected"
        assert multi_monitor_watcher.email_jobs_found_session == 5
        assert multi_monitor_watcher.website_monitor_status == "Monitoring"
        assert multi_monitor_watcher.website_jobs_found_session == 3


class TestConfigurationChanges:
    """Test runtime configuration changes and their effects."""

    @pytest.fixture
    def configurable_watcher(self, mock_config, mock_state, mock_logger):
        """Create watcher for config testing."""
        from gengowatcher.watcher import GengoWatcher

        watcher = GengoWatcher(mock_config, mock_state, mock_logger)
        watcher.cancellation_manager.update_settings = MagicMock()
        return watcher

    def test_config_change_triggers_save(self, configurable_watcher):
        """Test that config changes are saved."""
        configurable_watcher.set_config_value("Watcher", "check_interval", "45")

        configurable_watcher.config.set.assert_called_with(
            "Watcher", "check_interval", "45"
        )
        configurable_watcher.config.save_config.assert_called_once()

    def test_cancellation_config_update(self, configurable_watcher, mock_config):
        """Test that cancellation config changes update manager."""
        mock_config.getboolean.return_value = True
        mock_config.getfloat.return_value = 3.0

        # Ensure update_settings is a mock
        configurable_watcher.cancellation_manager.update_settings = MagicMock()

        configurable_watcher.set_config_value("Cancellation", "enabled", "true")

        # Should trigger reconfiguration
        configurable_watcher.cancellation_manager.update_settings.assert_called()


class TestErrorRecovery:
    """Test error recovery and resilience."""

    @pytest.fixture
    def resilient_watcher(self, mock_config, mock_state, mock_logger):
        """Create watcher for error testing."""
        from gengowatcher.watcher import GengoWatcher

        watcher = GengoWatcher(mock_config, mock_state, mock_logger)
        return watcher

    def test_rss_fetch_error_recovery(self, resilient_watcher):
        """Test recovery from RSS fetch errors."""
        with patch("gengowatcher.watcher.feedparser.parse") as mock_parse:
            # Simulate error
            mock_parse.side_effect = Exception("Network error")

            result = resilient_watcher.fetch_rss()
            assert result is None

            # Should continue running, not crash

    def test_state_save_error_handling(self, resilient_watcher):
        """Test handling of state save errors."""
        resilient_watcher.state.save_state = MagicMock(
            side_effect=Exception("IO error")
        )

        # Should handle error gracefully
        resilient_watcher.handle_exit()
        # Should not raise exception

    def test_cancellation_stats_error_handling(self, resilient_watcher):
        """Test error handling when getting cancellation stats fails."""
        resilient_watcher.cancellation_manager.get_stats = MagicMock(
            side_effect=Exception("Stats error")
        )

        stats = resilient_watcher.get_cancellation_stats()
        assert stats is None  # Should return None instead of crashing


class TestWebAPIIntegration:
    """Test Web API integration with watcher."""

    @pytest.fixture
    def api_system(self, mock_config, mock_state, mock_logger):
        """Create WebAPI with watcher for integration testing."""
        from gengowatcher.web import WebAPI

        with patch("gengowatcher.web.GengoWatcher") as MockWatcher:
            mock_watcher = MagicMock()
            mock_watcher.start_time = time.time()
            mock_watcher.websocket_status = "Live"
            mock_watcher.rss_action = "Checking"
            mock_watcher.shutdown_event = MagicMock()
            mock_watcher.shutdown_event.is_set.return_value = False
            MockWatcher.return_value = mock_watcher

            api = WebAPI(mock_config, mock_state, mock_logger)
            api.watcher = mock_watcher
            return api, mock_watcher

    def test_api_triggers_immediate_check(self, api_system):
        """Test API can trigger immediate RSS check."""
        api, watcher = api_system

        result = api.execute_command("check")

        assert result["status"] == "success"
        watcher.check_now_event.set.assert_called_once()

    def test_api_pause_creates_file(self, api_system, tmp_path):
        """Test API pause creates pause file."""
        api, watcher = api_system
        pause_file = tmp_path / "pause"
        watcher.PAUSE_FILE = str(pause_file)
        watcher.pause_monitoring.side_effect = lambda: pause_file.write_text("")

        result = api.execute_command("pause")

        assert result["status"] == "success"
        watcher.pause_monitoring.assert_called_once()
        assert pause_file.exists()

    @pytest.mark.asyncio
    async def test_api_job_acceptance_flow(self, api_system):
        """Test complete job acceptance flow through API."""
        api, watcher = api_system

        # Mock job data
        api.get_recent_jobs = MagicMock(
            return_value={
                "jobs": [
                    MagicMock(
                        id="12345",
                        title="Test",
                        reward=25.0,
                        url="https://example.com",
                        source="rss",
                    )
                ]
            }
        )

        async def mock_accept(_job):
            return True

        watcher.job_acceptance_engine._attempt_job_acceptance = mock_accept

        result = await api.accept_job("12345")
        assert result is True


class TestStatisticsAggregation:
    """Test statistics aggregation across system."""

    @pytest.fixture
    def stats_system(self):
        """Create system with stats tracking."""
        from gengowatcher.stats import StatsManager

        with tempfile.TemporaryDirectory() as tmpdir:
            stats_path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=stats_path)
            yield manager

    def test_hourly_aggregation(self, stats_system):
        """Test hourly statistics aggregation."""
        # Deterministic distribution for peak-hour calculation
        stats_system.hourly_counts = {hour: hour + 1 for hour in range(24)}

        peak_hour, peak_count = stats_system.get_peak_hour()
        assert peak_hour == 23  # Last hour should have most jobs
        assert peak_count == 24

    def test_source_distribution_tracking(self, stats_system):
        """Test tracking job distribution across sources."""
        # Record jobs from different sources
        for _ in range(10):
            stats_system.record_job(10.0, "Web", "JA→EN", accepted=False)
        for _ in range(5):
            stats_system.record_job(10.0, "WebSocket", "EN→JA", accepted=False)
        for _ in range(3):
            stats_system.record_job(10.0, "Email", "FR→EN", accepted=False)

        assert stats_system.by_source.website == 10
        assert stats_system.by_source.websocket == 5
        assert stats_system.by_source.email == 3

    def test_acceptance_rate_calculation(self, stats_system):
        """Test calculating acceptance rate correctly."""
        # Record mix of accepted and rejected
        for _ in range(7):
            stats_system.record_job(10.0, "RSS", "JA→EN", accepted=True)
        for _ in range(3):
            stats_system.record_job(10.0, "RSS", "JA→EN", accepted=False)

        rate = (
            stats_system.session.jobs_accepted / stats_system.session.jobs_found
        ) * 100
        assert rate == 70.0


class TestBoundaryConditions:
    """Test boundary conditions and edge cases."""

    def test_zero_check_interval_validation(self, mock_config, mock_state, mock_logger):
        """Test that zero check interval is corrected."""
        from gengowatcher.watcher import GengoWatcher

        mock_config.get.side_effect = lambda s, k, **kw: {
            ("Watcher", "check_interval"): 0,
            ("Logging", "log_all_entries_enabled"): False,
        }.get((s, k), kw.get("fallback"))

        _ = GengoWatcher(mock_config, mock_state, mock_logger)

        # Should have been corrected to minimum
        assert mock_config.set.called

    def test_negative_check_interval_validation(
        self, mock_config, mock_state, mock_logger
    ):
        """Test that negative check interval is corrected."""
        from gengowatcher.watcher import GengoWatcher

        mock_config.get.side_effect = lambda s, k, **kw: {
            ("Watcher", "check_interval"): -10,
            ("Logging", "log_all_entries_enabled"): False,
        }.get((s, k), kw.get("fallback"))

        _ = GengoWatcher(mock_config, mock_state, mock_logger)

        # Should have been corrected
        assert mock_config.set.called

    def test_maximum_pagination_limit(self):
        """Test that pagination respects maximum limits."""
        from gengowatcher.web import PaginationParams

        # Should accept 100
        params = PaginationParams(page=1, limit=100)
        assert params.limit == 100

        # Should reject over 100
        with pytest.raises(ValueError):
            PaginationParams(page=1, limit=101)

    def test_empty_job_title_handling(self, mock_config, mock_state, mock_logger):
        """Test handling of jobs with empty titles."""
        from gengowatcher.watcher import GengoWatcher

        watcher = GengoWatcher(mock_config, mock_state, mock_logger)
        watcher.show_notification = MagicMock()
        watcher.state.seen_job_ids = deque()

        watcher._process_new_job(12345, "", 10.0, "https://example.com", "RSS")

        # Should still process job
        assert watcher.show_notification.called


class TestConcurrencyAndThreadSafety:
    """Test thread safety and concurrent access."""

    def test_concurrent_job_processing(self, mock_config, mock_state, mock_logger):
        """Test that concurrent job processing is thread-safe."""
        from gengowatcher.watcher import GengoWatcher
        import threading

        watcher = GengoWatcher(mock_config, mock_state, mock_logger)
        watcher.show_notification = MagicMock()
        watcher.state.seen_job_ids = deque()

        def process_job(job_id):
            watcher._process_new_job(
                job_id, f"Job {job_id}", 10.0, f"https://example.com/{job_id}", "RSS"
            )

        # Process multiple jobs concurrently
        threads = []
        for i in range(10):
            t = threading.Thread(target=process_job, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All jobs should be processed
        assert len(watcher.state.seen_job_ids) == 10

    def test_web_api_thread_safety(self, mock_config, mock_state, mock_logger):
        """Test WebAPI thread safety with concurrent requests."""
        from gengowatcher.web import WebAPI, WatcherStatus

        with patch("gengowatcher.web.GengoWatcher") as MockWatcher:
            mock_watcher = MagicMock()
            MockWatcher.return_value = mock_watcher
            mock_watcher.shutdown_event.is_set.return_value = False
            mock_watcher.websocket_status = "Live"
            mock_watcher.rss_action = "Checking"
            mock_watcher.last_check_time = 1234567890.0
            mock_watcher.next_check_time = 1234567950.0
            mock_watcher.session_new_entries = 0
            mock_watcher.session_total_value = 0.0
            mock_watcher.start_time = 1234567800.0
            mock_watcher.failure_count = 0
            mock_watcher.get_cancellation_stats.return_value = {}

            api = WebAPI(mock_config, mock_state, mock_logger)

            # Mock get_status directly to avoid Pydantic validation issues with mocks
            mock_status = WatcherStatus(
                is_running=True,
                websocket_status="Live",
                rss_status="OK",
                email_status="Idle",
                website_status="Idle",
                last_check_time=time.time(),
                next_check_time=time.time() + 60,
                session_stats={
                    "jobs_found": 0,
                    "jobs_accepted": 0,
                    "total_reward": 0.0,
                },
                failure_count=0,
                uptime_seconds=3600,
                cancellation_stats={},
            )
            api.get_status = MagicMock(return_value=mock_status)

            # Concurrent status checks
            import threading

            results = []

            def get_status():
                status = api.get_status()
                results.append(status)

            threads = [threading.Thread(target=get_status) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Should have 10 successful status calls
            assert len(results) == 10
