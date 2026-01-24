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
