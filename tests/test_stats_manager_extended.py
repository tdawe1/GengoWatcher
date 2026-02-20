"""Extended tests for StatsManager with additional coverage."""

import pytest
import tempfile
import pathlib
import time
import json
from gengowatcher.stats import (
    StatsManager,
    SessionStats,
    AllTimeStats,
    SourceStats,
)


class TestSessionStats:
    """Extended tests for SessionStats."""

    def test_session_stats_initialization(self):
        """Test SessionStats initializes with correct defaults."""
        stats = SessionStats()
        assert stats.jobs_found == 0
        assert stats.jobs_accepted == 0
        assert stats.total_value == 0.0
        assert stats.start_time > 0

    def test_session_stats_duration_calculation(self):
        """Test duration calculation works correctly."""
        stats = SessionStats()
        time.sleep(0.1)  # Small delay
        assert stats.duration_seconds >= 0.1

    def test_session_stats_with_data(self):
        """Test SessionStats with actual data."""
        stats = SessionStats()
        stats.jobs_found = 10
        stats.jobs_accepted = 5
        stats.total_value = 125.50

        assert stats.jobs_found == 10
        assert stats.jobs_accepted == 5
        assert stats.total_value == 125.50


class TestAllTimeStats:
    """Tests for AllTimeStats."""

    def test_all_time_stats_initialization(self):
        """Test AllTimeStats initializes correctly."""
        stats = AllTimeStats()
        assert stats.total_jobs == 0
        assert stats.total_sessions == 0
        assert stats.total_value == 0.0

    def test_all_time_stats_with_values(self):
        """Test AllTimeStats with set values."""
        stats = AllTimeStats()
        stats.total_jobs = 100
        stats.total_sessions = 10
        stats.total_value = 1000.0

        assert stats.total_jobs == 100
        assert stats.total_sessions == 10
        assert stats.total_value == 1000.0


class TestSourceStats:
    """Tests for SourceStats."""

    def test_source_stats_initialization(self):
        """Test SourceStats initializes with zeros."""
        stats = SourceStats()
        assert stats.websocket == 0
        assert stats.email == 0
        assert stats.website == 0

    def test_source_stats_increment(self):
        """Test incrementing source counters."""
        stats = SourceStats()
        stats.websocket = 5
        stats.email = 3
        stats.website = 2

        assert stats.websocket == 5
        assert stats.email == 3
        assert stats.website == 2


class TestStatsManagerRecording:
    """Tests for StatsManager job recording."""

    def test_record_job_increments_found(self):
        """Test that recording a job increments found count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "Web", "JA→EN", accepted=False)
            manager.record_job(10.0, "RSS", "JA→EN", accepted=False)

            assert manager.session.jobs_found == 1
            assert manager.session.jobs_accepted == 0

    def test_record_job_increments_accepted(self):
        """Test that recording an accepted job increments both counters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(15.0, "WebSocket", "EN→JA", accepted=True)

            assert manager.session.jobs_found == 1
            assert manager.session.jobs_accepted == 1
            assert manager.session.total_value == 15.0

    def test_record_job_tracks_source(self):
        """Test that job source is tracked correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "RSS", "JA→EN", accepted=False)
            manager.record_job(20.0, "WebSocket", "EN→JA", accepted=False)
            manager.record_job(30.0, "Email", "FR→EN", accepted=False)

            assert manager.by_source.rss == 1
            assert manager.by_source.websocket == 1
            assert manager.by_source.email == 1

    def test_record_job_tracks_language_pair(self):
        """Test that language pairs are tracked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "RSS", "JA→EN", accepted=False)
            manager.record_job(20.0, "RSS", "JA→EN", accepted=False)
            manager.record_job(30.0, "RSS", "EN→FR", accepted=False)

            assert manager.by_language["JA→EN"] == 2
            assert manager.by_language["EN→FR"] == 1

    def test_record_job_case_insensitive_source(self):
        """Test that source matching is case-insensitive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "rss", "JA→EN", accepted=False)
            manager.record_job(20.0, "RSS", "EN→JA", accepted=False)
            manager.record_job(30.0, "Rss", "FR→EN", accepted=False)

            assert manager.by_source.rss == 3

    def test_record_job_unknown_source(self):
        """Test recording job with unknown source."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "unknown_source", "JA→EN", accepted=False)

            # Should still increment found count
            assert manager.session.jobs_found == 1


class TestStatsManagerPersistence:
    """Tests for StatsManager persistence functionality."""

    def test_save_and_load(self):
        """Test that stats persist across save/load cycles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"

            # First manager - record data and save
            manager1 = StatsManager(stats_path=path)
            manager1.record_job(25.0, "Email", "EN→JA", accepted=True)
            manager1.all_time.total_jobs = 100
            manager1.all_time.total_sessions = 5
            manager1.save()

            # Second manager - load from same file
            manager2 = StatsManager(stats_path=path)
            assert manager2.all_time.total_jobs == 100
            assert manager2.all_time.total_sessions == 5
            assert manager2.by_source.email == 1

    def test_save_creates_directory(self):
        """Test that save creates parent directory if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "subdir" / "stats.json"

            manager = StatsManager(stats_path=path)
            manager.save()

            assert path.exists()
            assert path.parent.exists()

    def test_load_missing_file(self):
        """Test loading when stats file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "missing.json"

            manager = StatsManager(stats_path=path)

            # Should initialize with default values
            assert manager.all_time.total_jobs == 0
            assert manager.session.jobs_found == 0

    def test_load_corrupted_file(self):
        """Test loading corrupted JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "corrupted.json"
            path.write_text("{invalid json")

            manager = StatsManager(stats_path=path)

            # Should initialize with defaults when file is corrupted
            assert manager.all_time.total_jobs == 0


class TestStatsManagerHourlyTracking:
    """Tests for hourly job tracking."""

    def test_record_job_updates_hourly_counts(self):
        """Test that jobs are counted by hour."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "RSS", "JA→EN", accepted=False)

            # Should have recorded in current hour
            from datetime import datetime

            current_hour = datetime.now().hour
            assert current_hour in manager.hourly_counts
            assert manager.hourly_counts[current_hour] >= 1

    def test_get_peak_hour(self):
        """Test getting peak hour statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            # Manually set hourly counts
            manager.hourly_counts = {8: 5, 10: 10, 14: 7, 16: 3}

            peak_hour, peak_count = manager.get_peak_hour()

            assert peak_hour == 10
            assert peak_count == 10

    def test_get_peak_hour_no_data(self):
        """Test get_peak_hour with no data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            peak_hour, peak_count = manager.get_peak_hour()

            # Should return sensible defaults
            assert peak_hour >= 0
            assert peak_count == 0


class TestStatsManagerAverages:
    """Tests for average calculations."""

    def test_average_reward_with_jobs(self):
        """Test calculating average reward."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "Website", "JA→EN", accepted=True)
            manager.record_job(20.0, "WebSocket", "EN→JA", accepted=True)
            manager.record_job(30.0, "Email", "FR→EN", accepted=True)

            avg = manager.session.total_value / manager.session.jobs_found
            assert avg == 20.0

    def test_average_reward_no_jobs(self):
        """Test average reward with no jobs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            # Should handle division by zero
            if manager.session.jobs_found > 0:
                avg = manager.session.total_value / manager.session.jobs_found
            else:
                avg = 0.0

            assert avg == 0.0


class TestStatsManagerEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_record_job_zero_reward(self):
        """Test recording job with zero reward."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(0.0, "Web", "JA→EN", accepted=False)
            manager.record_job(0.0, "RSS", "JA→EN", accepted=False)

            assert manager.session.jobs_found == 1
            assert manager.session.total_value == 0.0

    def test_record_job_negative_reward(self):
        """Test recording job with negative reward (should be prevented)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            # Negative rewards should probably be rejected, but test current behavior
            manager.record_job(-10.0, "Web", "JA→EN", accepted=False)
            manager.record_job(-10.0, "RSS", "JA→EN", accepted=False)

            assert manager.session.jobs_found == 1
            # Value might be negative or zero depending on implementation

    def test_record_job_very_large_reward(self):
        """Test recording job with very large reward."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(999999.99, "Web", "JA→EN", accepted=True)

            assert manager.session.total_value == 999999.99
            manager.record_job(999999.99, "Website", "JA→EN", accepted=True)

            assert manager.session.total_value == 999999.99
            assert manager.all_time.total_value == 999999.99

    def test_record_job_empty_language_pair(self):
        """Test recording job with empty language pair."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "Web", "", accepted=False)
            manager.record_job(10.0, "RSS", "", accepted=False)

            assert manager.session.jobs_found == 1
            assert "" in manager.by_language

    def test_multiple_saves(self):
        """Test multiple save operations don't corrupt data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            for i in range(10):
                manager.record_job(10.0, "Web", "JA→EN", accepted=False)
                manager.record_job(10.0, "RSS", "JA→EN", accepted=False)
                manager.save()

            # Reload and verify
            manager2 = StatsManager(stats_path=path)
            assert manager2.by_source.website == 10
            assert manager2.by_source.rss == 10

    def test_concurrent_language_pair_tracking(self):
        """Test tracking multiple language pairs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            pairs = ["JA→EN", "EN→JA", "FR→EN", "EN→FR", "DE→EN"]
            for pair in pairs:
                manager.record_job(10.0, "Web", pair, accepted=False)
                manager.record_job(10.0, "RSS", pair, accepted=False)

            assert len(manager.by_language) == len(pairs)
            for pair in pairs:
                assert manager.by_language[pair] == 1

    def test_stats_persistence_unicode(self):
        """Test that Unicode language pairs persist correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"

            manager1 = StatsManager(stats_path=path)
            manager1.record_job(10.0, "Web", "日本語→English", accepted=False)
            manager1.record_job(10.0, "RSS", "日本語→English", accepted=False)
            manager1.save()

            manager2 = StatsManager(stats_path=path)
            assert "日本語→English" in manager2.by_language
            assert manager2.by_language["日本語→English"] == 1

    def test_acceptance_rate_calculation(self):
        """Test calculating acceptance rate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            manager.record_job(10.0, "Web", "JA→EN", accepted=True)
            manager.record_job(20.0, "Web", "JA→EN", accepted=True)
            manager.record_job(30.0, "Web", "JA→EN", accepted=False)
            manager.record_job(40.0, "Web", "JA→EN", accepted=False)
            manager.record_job(10.0, "RSS", "JA→EN", accepted=True)
            manager.record_job(20.0, "RSS", "JA→EN", accepted=True)
            manager.record_job(30.0, "RSS", "JA→EN", accepted=False)
            manager.record_job(40.0, "RSS", "JA→EN", accepted=False)

            # 2 accepted out of 4 found = 50%
            acceptance_rate = (
                manager.session.jobs_accepted / manager.session.jobs_found
            ) * 100
            assert acceptance_rate == 50.0

    def test_source_distribution_percentages(self):
        """Test calculating source distribution percentages."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "stats.json"
            manager = StatsManager(stats_path=path)

            # Record 10 Web, 5 WebSocket, 5 Email = 20 total
            for _ in range(10):
                manager.record_job(10.0, "Web", "JA→EN", accepted=False)
            # Record 10 RSS, 5 WebSocket, 5 Email = 20 total
            for _ in range(10):
                manager.record_job(10.0, "RSS", "JA→EN", accepted=False)
            for _ in range(5):
                manager.record_job(10.0, "WebSocket", "JA→EN", accepted=False)
            for _ in range(5):
                manager.record_job(10.0, "Email", "JA→EN", accepted=False)

            total = manager.session.jobs_found
            rss_pct = (manager.by_source.website / total) * 100
            rss_pct = (manager.by_source.rss / total) * 100
            ws_pct = (manager.by_source.websocket / total) * 100
            email_pct = (manager.by_source.email / total) * 100

            assert rss_pct == 50.0
            assert ws_pct == 25.0
            assert email_pct == 25.0
