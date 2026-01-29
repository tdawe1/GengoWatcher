"""Tests for StatsManager."""

import pytest
import tempfile
import pathlib
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
        assert manager.by_source.websocket == 1
        assert manager.by_language["JA→EN"] == 1


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

        # Record jobs at different hours
        import datetime
        from unittest.mock import patch

        # Mock time to record jobs at specific hours
        with patch('gengowatcher.stats.datetime') as mock_datetime:
            # Record 5 jobs at hour 14
            mock_datetime.datetime.now.return_value = datetime.datetime(2024, 1, 1, 14, 0, 0)
            for _ in range(5):
                manager.record_job(10.0, "WebSocket", "JA→EN", accepted=True)

            # Record 3 jobs at hour 10
            mock_datetime.datetime.now.return_value = datetime.datetime(2024, 1, 1, 10, 0, 0)
            for _ in range(3):
                manager.record_job(10.0, "WebSocket", "JA→EN", accepted=True)

        # Peak should be hour 14 with 5 jobs
        peak_hour, peak_rate = manager.get_peak_hour()
        assert peak_hour == 14
        assert peak_rate == 5
