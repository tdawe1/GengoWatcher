"""Tests for StatsManager."""

import pytest
import tempfile
import pathlib
import time
import json
from gengowatcher.stats import StatsManager, SessionStats


def test_session_stats_duration():
    """SessionStats should track duration."""
    stats = SessionStats()
    # Duration should be near 0 at start
    assert stats.duration_seconds < 2


def test_stats_manager_record_job():
    """StatsManager should record job stats."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        manager.record_job(10.0, "WebSocket", "JA→EN", accepted=True)

        assert manager.session.jobs_found == 1
        assert manager.session.jobs_accepted == 1
        assert manager.session.total_value == 10.0
        assert manager.all_time.total_jobs == 1
        assert manager.all_time.total_jobs_accepted == 1
        assert manager.by_source.websocket == 1
        assert manager.by_language["JA→EN"] == 1


def test_stats_manager_tracks_rss_source():
    """RSS jobs should increment rss, not website."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        manager.record_job(10.0, "RSS", "JA→EN", accepted=False)

        assert manager.by_source.rss == 1
        assert manager.by_source.website == 0


def test_stats_manager_persistence():
    """StatsManager should persist and reload stats."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"

        # First manager - record data
        manager1 = StatsManager(stats_path=path)
        manager1.record_job(25.0, "Email", "EN→JA", accepted=True)
        manager1.all_time.total_jobs = 100
        manager1.save()

        # Second manager - reload
        manager2 = StatsManager(stats_path=path)
        assert manager2.all_time.total_jobs == 100
        assert manager2.all_time.total_jobs_accepted == 1
        assert manager2.by_source.email == 1


def test_get_peak_hour_with_empty_data():
    """get_peak_hour() should return zero rate when hourly_counts is empty."""

    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        # With no jobs recorded, hourly_counts should be empty
        assert len(manager.hourly_counts) == 0

        # get_peak_hour should return (12, 0.0) for empty data
        peak_hour, peak_rate = manager.get_peak_hour()
        assert peak_hour == 12  # Default hour
        assert peak_rate == 0.0  # Zero activity

        # This test demonstrates the issue: UI code must check peak_rate > 0
        # before highlighting the peak period to avoid misleading users


def test_get_peak_hour_with_data():
    """get_peak_hour() should return correct peak hour and rate."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        # Record 5 jobs: 3 accepted, 2 not accepted
        manager.record_job(10.0, "WebSocket", "JA→EN", accepted=True)
        manager.record_job(15.0, "WebSocket", "JA→EN", accepted=True)
        manager.record_job(20.0, "Email", "EN→JA", accepted=False)
        manager.record_job(25.0, "WebSocket", "JA→EN", accepted=True)
        manager.record_job(30.0, "Email", "EN→JA", accepted=False)

        # Check that total_jobs counts all jobs (5)
        assert manager.all_time.total_jobs == 5
        # Check that total_value only includes accepted jobs (10 + 15 + 25 = 50)
        assert manager.all_time.total_value == 50.0
        # Check that avg_job_value is calculated correctly (50 / 5)
        expected_avg = 50.0 / 5
        assert abs(manager.all_time.avg_job_value - expected_avg) < 0.001

        # Reset hourly counts to isolate peak hour assertions
        manager.hourly_counts.clear()
        # Record jobs at different hours
        import datetime
        from unittest.mock import patch

        # Mock time to record jobs at specific hours
        with patch("gengowatcher.stats.datetime") as mock_datetime:
            # Record 5 jobs at hour 14
            mock_datetime.datetime.now.return_value = datetime.datetime(
                2024, 1, 1, 14, 0, 0
            )
            for _ in range(5):
                manager.record_job(10.0, "WebSocket", "JA→EN", accepted=True)

            # Record 3 jobs at hour 10
            mock_datetime.datetime.now.return_value = datetime.datetime(
                2024, 1, 1, 10, 0, 0
            )
            for _ in range(3):
                manager.record_job(10.0, "WebSocket", "JA→EN", accepted=True)

        # Peak should be hour 14 with 5 jobs
        peak_hour, peak_rate = manager.get_peak_hour()
        assert peak_hour == 14
        assert peak_rate == 5


class TestStatsManagerMultipleJobs:
    """Test recording multiple jobs."""

    def test_record_multiple_jobs(self):
        """Test recording multiple jobs updates all counters correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "Website", "JA→EN", accepted=True)
            manager.record_job(15.0, "WebSocket", "EN→JA", accepted=False)
            manager.record_job(20.0, "Email", "JA→EN", accepted=True)

            assert manager.session.jobs_found == 3
            assert manager.session.jobs_accepted == 2
            assert manager.session.total_value == 30.0

    def test_record_jobs_different_sources(self):
        """Test recording jobs from different sources."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "Website", "JA→EN", accepted=True)
            manager.record_job(15.0, "WebSocket", "EN→JA", accepted=True)
            manager.record_job(20.0, "Email", "JA→EN", accepted=True)
            manager.record_job(25.0, "Website", "EN→JA", accepted=True)

            assert manager.by_source.website == 2
            assert manager.by_source.websocket == 1
            assert manager.by_source.email == 1

    def test_record_jobs_different_languages(self):
        """Test recording jobs with different language pairs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "Website", "JA→EN", accepted=True)
            manager.record_job(15.0, "Website", "EN→JA", accepted=True)
            manager.record_job(20.0, "Website", "ZH→EN", accepted=True)
            manager.record_job(25.0, "Website", "JA→EN", accepted=True)

            assert manager.by_language["JA→EN"] == 2
            assert manager.by_language["EN→JA"] == 1
            assert manager.by_language["ZH→EN"] == 1


class TestStatsManagerHourlyCounts:
    """Test hourly job counting."""

    def test_hourly_counts_initialized(self):
        """Test that hourly_counts is initialized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            assert hasattr(manager, "hourly_counts")
            # Accessing any hour should yield a non-negative count (using .get to avoid mutating defaultdict)
            for hour in range(24):
                assert manager.hourly_counts.get(hour, 0) >= 0

    def test_get_peak_hour(self):
        """Test get_peak_hour method."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            # Set some hourly data
            manager.hourly_counts[10] = 50
            manager.hourly_counts[14] = 30
            manager.hourly_counts[18] = 20

            peak_hour, peak_count = manager.get_peak_hour()

            assert peak_hour == 10
            assert peak_count == 50

    def test_get_peak_hour_empty(self):
        """Test get_peak_hour when no jobs recorded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            peak_hour, peak_count = manager.get_peak_hour()

            assert peak_hour == 12
            assert peak_count == 0.0


class TestStatsManagerPersistence:
    """Test data persistence and reload."""

    def test_save_and_load_session_stats(self):
        """Test saving and loading session statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"

            manager1 = StatsManager(stats_path=path)
            manager1.record_job(100.0, "Website", "JA→EN", accepted=True)
            manager1.record_job(200.0, "WebSocket", "EN→JA", accepted=False)
            manager1.save()

            manager2 = StatsManager(stats_path=path)
            # Session stats should reset, but sources/languages should persist
            assert manager2.by_source.website == 1
            assert manager2.by_source.websocket == 1

    def test_save_and_load_hourly_counts(self):
        """Test saving and loading hourly counts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"

            manager1 = StatsManager(stats_path=path)
            manager1.hourly_counts[10] = 25
            manager1.hourly_counts[15] = 30
            manager1.save()

            manager2 = StatsManager(stats_path=path)
            assert manager2.hourly_counts[10] == 25
            assert manager2.hourly_counts[15] == 30

    def test_save_creates_file(self):
        """Test that save creates the stats file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"

            manager = StatsManager(stats_path=path)
            manager.record_job(50.0, "Website", "JA→EN", accepted=True)
            manager.save()

            assert path.exists()
            assert path.is_file()

    def test_load_invalid_json(self):
        """Test loading from invalid JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"

            # Write invalid JSON
            path.write_text("{ invalid json }")

            # Should handle gracefully and initialize with defaults
            manager = StatsManager(stats_path=path)
            assert manager.session.jobs_found == 0


class TestStatsManagerEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_record_job_zero_reward(self):
        """Test recording a job with zero reward."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(0.0, "Website", "JA→EN", accepted=True)

            assert manager.session.jobs_found == 1
            assert manager.session.total_value == 0.0

    def test_record_job_negative_reward(self):
        """Test recording a job with negative reward (edge case)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            # Negative rewards shouldn't happen, but test handling
            manager.record_job(-10.0, "Website", "JA→EN", accepted=True)

            assert manager.session.jobs_found == 1
            # Should either reject or accept the value
            assert isinstance(manager.session.total_value, (int, float))

    def test_record_job_very_large_reward(self):
        """Test recording a job with very large reward."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(999999.99, "Website", "JA→EN", accepted=True)

            assert manager.session.jobs_found == 1
            assert manager.session.total_value == 999999.99

    def test_record_job_unknown_source(self):
        """Test recording a job with unknown source."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "UnknownSource", "JA→EN", accepted=True)

            assert manager.session.jobs_found == 1
            # Should handle unknown source gracefully

    def test_record_job_empty_language_pair(self):
        """Test recording a job with empty language pair."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "Website", "", accepted=True)

            assert manager.session.jobs_found == 1
            # Should handle empty language pair gracefully


class TestStatsManagerReset:
    """Test stats reset functionality."""

    def test_session_stats_reset(self):
        """Test resetting session statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            # Record some jobs
            manager.record_job(10.0, "Website", "JA→EN", accepted=True)
            manager.record_job(20.0, "Website", "EN→JA", accepted=False)

            assert manager.session.jobs_found == 2

            # Reset session (if method exists)
            if hasattr(manager, "reset_session"):
                manager.reset_session()
                assert manager.session.jobs_found == 0


class TestSessionStatsTimestamp:
    """Test SessionStats timestamp tracking."""

    def test_session_stats_has_start_time(self):
        """Test that SessionStats tracks start time."""
        stats = SessionStats()

        assert hasattr(stats, "start_time")
        # Start time should be recent (within last second)
        assert abs(time.time() - stats.start_time) < 2

    def test_session_duration_increases(self):
        """Test that session duration increases over time."""
        stats = SessionStats()

        duration1 = stats.duration_seconds
        time.sleep(0.1)  # Wait a bit
        duration2 = stats.duration_seconds

        assert duration2 >= duration1


class TestStatsManagerConcurrency:
    """Test concurrent access scenarios."""

    def test_multiple_rapid_records(self):
        """Test recording many jobs rapidly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            # Record many jobs quickly
            for i in range(100):
                manager.record_job(
                    float(i),
                    "Website" if i % 2 == 0 else "WebSocket",
                    "JA→EN" if i % 3 == 0 else "EN→JA",
                    accepted=(i % 2 == 0),
                )

            assert manager.session.jobs_found == 100
            assert manager.session.jobs_accepted == 50


class TestStatsManagerExport:
    """Test stats export functionality."""

    def test_stats_file_format(self):
        """Test that saved stats file is valid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "Website", "JA→EN", accepted=True)
            manager.save()

            # Read and verify JSON format
            with open(path, "r") as f:
                data = json.load(f)

            assert isinstance(data, dict)

    def test_stats_contains_all_data(self):
        """Test that saved stats contains all required data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "Website", "JA→EN", accepted=True)
            manager.hourly_counts[12] = 5
            manager.save()

            with open(path, "r") as f:
                data = json.load(f)

            # Verify key sections exist
            assert isinstance(data, dict)
            assert "all_time" in data
            assert "by_source" in data
            assert "by_language" in data
            assert "hourly_counts" in data
            assert "daily_counts" in data
            assert "daily_earnings" in data
