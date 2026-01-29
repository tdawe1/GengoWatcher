"""Tests for StatsManager."""

import pytest
import tempfile
import pathlib
import time
import datetime
from gengowatcher.stats import StatsManager, SessionStats, AllTimeStats, SourceStats


def test_session_stats_duration():
    """SessionStats should track duration."""
    stats = SessionStats()
    # Duration should be near 0 at start
    assert stats.duration_seconds < 2


def test_session_stats_rate_per_hour():
    """SessionStats should calculate rate per hour."""
    stats = SessionStats(start_time=time.time() - 3600)  # 1 hour ago
    stats.jobs_found = 10
    rate = stats.rate_per_hour
    assert 9 <= rate <= 11  # Allow for small timing differences


def test_session_stats_rate_with_minimal_time():
    """SessionStats should handle very short durations."""
    stats = SessionStats(start_time=time.time() - 0.001)
    stats.jobs_found = 5
    # Should not divide by zero or crash
    rate = stats.rate_per_hour
    assert rate > 0


def test_all_time_stats_avg_job_value():
    """AllTimeStats should calculate average job value."""
    stats = AllTimeStats(total_jobs=10, total_value=100.0)
    assert stats.avg_job_value == 10.0


def test_all_time_stats_avg_with_zero_jobs():
    """AllTimeStats should handle zero jobs."""
    stats = AllTimeStats(total_jobs=0, total_value=0.0)
    assert stats.avg_job_value == 0.0


def test_source_stats_total():
    """SourceStats should calculate total."""
    stats = SourceStats(websocket=5, email=3, website=2)
    assert stats.total == 10


def test_source_stats_percentages():
    """SourceStats should calculate percentages."""
    stats = SourceStats(websocket=50, email=30, website=20)
    percentages = stats.percentages()
    assert percentages["websocket"] == 50.0
    assert percentages["email"] == 30.0
    assert percentages["website"] == 20.0


def test_source_stats_percentages_with_zero():
    """SourceStats should handle zero total."""
    stats = SourceStats(websocket=0, email=0, website=0)
    percentages = stats.percentages()
    assert percentages["websocket"] == 0.0


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


def test_stats_manager_record_multiple_jobs():
    """StatsManager should accumulate multiple jobs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        manager.record_job(10.0, "WebSocket", "JA→EN", accepted=True)
        manager.record_job(20.0, "Email", "EN→JA", accepted=False)
        manager.record_job(15.0, "Website", "JA→EN", accepted=True)

        assert manager.session.jobs_found == 3
        assert manager.session.jobs_accepted == 2
        assert manager.session.total_value == 25.0
        assert manager.by_source.websocket == 1
        assert manager.by_source.email == 1
        assert manager.by_source.website == 1


def test_stats_manager_hourly_counts():
    """StatsManager should track hourly distribution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        # Record jobs at current hour
        current_hour = datetime.datetime.now().hour
        manager.record_job(10.0, "RSS", "JA→EN", accepted=True)

        assert manager.hourly_counts[current_hour] == 1


def test_stats_manager_daily_counts():
    """StatsManager should track daily distribution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        day_name = datetime.datetime.now().strftime("%A")
        manager.record_job(10.0, "RSS", "JA→EN", accepted=True)

        assert manager.daily_counts[day_name] == 1


def test_stats_manager_daily_earnings():
    """StatsManager should track daily earnings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        manager.record_job(10.0, "RSS", "JA→EN", accepted=True)
        manager.record_job(15.0, "WebSocket", "EN→JA", accepted=True)

        assert manager.daily_earnings[date_str] == 25.0


def test_stats_manager_best_day_tracking():
    """StatsManager should track best earning day."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        manager.record_job(100.0, "RSS", "JA→EN", accepted=True)

        assert manager.all_time.best_day_value == 100.0
        assert manager.all_time.best_day_date == date_str


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


def test_stats_manager_end_session():
    """StatsManager should update session count on end."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        manager.end_session()

        assert manager.all_time.total_sessions == 1


def test_stats_manager_get_peak_hour():
    """StatsManager should identify peak hour."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        manager.hourly_counts = {9: 5, 10: 12, 11: 8, 12: 15, 13: 10}
        peak_hour, peak_count = manager.get_peak_hour()

        assert peak_hour == 12
        assert peak_count == 15


def test_stats_manager_get_peak_hour_empty():
    """StatsManager should handle empty hourly data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        peak_hour, peak_count = manager.get_peak_hour()

        assert peak_hour == 12  # Default
        assert peak_count == 0.0


def test_stats_manager_get_slowest_hour():
    """StatsManager should identify slowest hour."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        manager.hourly_counts = {9: 5, 10: 2, 11: 8, 12: 15, 13: 10}
        slow_hour, slow_count = manager.get_slowest_hour()

        assert slow_hour == 10
        assert slow_count == 2


def test_stats_manager_get_recent_earnings():
    """StatsManager should return recent earnings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        today = datetime.date.today()
        for i in range(7):
            date = today - datetime.timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            manager.daily_earnings[date_str] = 10.0 * (i + 1)

        recent = manager.get_recent_earnings(days=7)

        assert len(recent) == 7


def test_stats_manager_corrupted_file_handling():
    """StatsManager should handle corrupted stats file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"

        # Create corrupted file
        with open(path, "w") as f:
            f.write("not valid json {")

        # Should load with defaults, not crash
        manager = StatsManager(stats_path=path)
        assert manager.all_time.total_jobs == 0


def test_stats_manager_source_detection():
    """StatsManager should correctly detect job sources."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        manager.record_job(10.0, "WebSocket", "JA→EN", accepted=True)
        manager.record_job(10.0, "ws", "JA→EN", accepted=True)
        manager.record_job(10.0, "Email Monitor", "JA→EN", accepted=True)
        manager.record_job(10.0, "Website", "JA→EN", accepted=True)

        assert manager.by_source.websocket == 2
        assert manager.by_source.email == 1
        assert manager.by_source.website == 1


def test_stats_manager_thread_safety():
    """StatsManager should be thread-safe."""
    import threading

    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        def record_jobs():
            for i in range(10):
                manager.record_job(10.0, "RSS", "JA→EN", accepted=True)

        threads = [threading.Thread(target=record_jobs) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert manager.session.jobs_found == 50


def test_stats_manager_language_tracking():
    """StatsManager should track language pairs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        manager.record_job(10.0, "RSS", "JA→EN", accepted=True)
        manager.record_job(15.0, "RSS", "JA→EN", accepted=True)
        manager.record_job(20.0, "RSS", "EN→JA", accepted=True)

        assert manager.by_language["JA→EN"] == 2
        assert manager.by_language["EN→JA"] == 1