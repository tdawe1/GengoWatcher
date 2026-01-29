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
        assert manager.all_time.total_jobs == 1
        assert manager.all_time.total_jobs_accepted == 1
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
        assert manager2.all_time.total_jobs_accepted == 1
        assert manager2.by_source.email == 1


def test_stats_manager_accepted_vs_total():
    """StatsManager should track accepted jobs separately from total jobs."""
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
        # Check that total_jobs_accepted counts only accepted jobs (3)
        assert manager.all_time.total_jobs_accepted == 3
        # Check that total_value only includes accepted jobs (10 + 15 + 25 = 50)
        assert manager.all_time.total_value == 50.0
        # Check that avg_job_value is calculated correctly (50 / 3)
        expected_avg = 50.0 / 3
        assert abs(manager.all_time.avg_job_value - expected_avg) < 0.001


