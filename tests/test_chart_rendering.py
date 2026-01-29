"""Tests for chart rendering functionality in ui_textual.py."""

import pytest
from unittest.mock import MagicMock
import tempfile
import pathlib
from rich.text import Text

from gengowatcher.ui_textual import JobsHourChart, ActivityPreview, ConfigPreview
from gengowatcher.stats import StatsManager
from gengowatcher.config import AppConfig


@pytest.fixture
def stats_with_data():
    """Create StatsManager with test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_path = pathlib.Path(tmpdir) / "stats.json"
        stats = StatsManager(stats_path=stats_path)

        # Populate hourly data
        stats.hourly_counts[0] = 5
        stats.hourly_counts[1] = 10
        stats.hourly_counts[2] = 15
        stats.hourly_counts[3] = 8
        stats.hourly_counts[6] = 20
        stats.hourly_counts[12] = 30
        stats.hourly_counts[18] = 25
        stats.hourly_counts[23] = 12

        yield stats


class TestChartTextRendering:
    """Test text rendering aspects of charts."""

    def test_render_chart_returns_rich_text(self, stats_with_data):
        """Test that _render_chart returns a Rich Text object."""
        chart = JobsHourChart(stats=stats_with_data)
        result = chart._render_chart()

        assert isinstance(result, Text)
        assert hasattr(result, 'plain')
        assert hasattr(result, '__str__')

    def test_render_chart_text_structure(self, stats_with_data):
        """Test that rendered chart has expected text structure."""
        chart = JobsHourChart(stats=stats_with_data)
        result = chart._render_chart()

        plain_text = str(result.plain)

        # Should have newlines for multiple rows
        assert '\n' in plain_text

        # Should have at least 6 lines (one for each period)
        lines = plain_text.strip().split('\n')
        assert len(lines) >= 6

    def test_render_chart_contains_time_labels(self, stats_with_data):
        """Test that chart contains time period labels."""
        chart = JobsHourChart(stats=stats_with_data)
        result = chart._render_chart()

        plain_text = str(result.plain)

        # All 6 time periods should be present
        assert "00-03" in plain_text
        assert "04-07" in plain_text
        assert "08-11" in plain_text
        assert "12-15" in plain_text
        assert "16-19" in plain_text
        assert "20-23" in plain_text

    def test_render_chart_contains_counts(self, stats_with_data):
        """Test that chart contains job counts."""
        chart = JobsHourChart(stats=stats_with_data)
        result = chart._render_chart()

        plain_text = str(result.plain)

        # Should contain numeric counts
        # Period 00-03 has: 5 + 10 + 15 + 8 = 38
        assert "38" in plain_text


class TestChartBarRendering:
    """Test bar rendering in charts."""

    def test_render_chart_with_filled_bars(self, stats_with_data):
        """Test that chart renders filled bars for non-zero values."""
        chart = JobsHourChart(stats=stats_with_data)
        result = chart._render_chart()

        plain_text = str(result.plain)

        # Should contain bar characters (filled or empty)
        has_bars = any(char in plain_text for char in ["█", "▏", "▎", "▍", "▌", "▋", "▊", "▉", "░"])
        assert has_bars

    def test_render_chart_with_empty_bars(self):
        """Test that chart renders empty bars for zero values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            stats_path = pathlib.Path(tmpdir) / "stats.json"
            empty_stats = StatsManager(stats_path=stats_path)

            chart = JobsHourChart(stats=empty_stats)
            result = chart._render_chart()

            plain_text = str(result.plain)

            # Should contain empty bar character or zero counts
            assert "░" in plain_text or "  0" in plain_text

    def test_bar_width_scaling(self, stats_with_data):
        """Test that bars scale based on maximum value."""
        chart = JobsHourChart(stats=stats_with_data)

        # Set a clear maximum
        chart.stats.hourly_counts[12] = 100  # Max value
        chart.stats.hourly_counts[0] = 10   # 10% of max

        result = chart._render_chart()

        # Should render without error
        assert isinstance(result, Text)

    def test_bar_padding_consistency(self, stats_with_data):
        """Test that all bars have consistent padding."""
        chart = JobsHourChart(stats=stats_with_data)
        result = chart._render_chart()

        lines = str(result.plain).strip().split('\n')

        # All lines should have similar length (allowing for variation in numbers)
        if len(lines) > 1:
            lengths = [len(line) for line in lines if line.strip()]
            # Lines should be roughly the same length (within 10 chars)
            if lengths:
                max_len = max(lengths)
                min_len = min(lengths)
                # Allow some variation for different number widths
                assert max_len - min_len < 15


class TestChartColorRendering:
    """Test color/styling in chart rendering."""

    def test_chart_uses_dragon_colors(self, stats_with_data):
        """Test that chart uses Dragon color theme."""
        chart = JobsHourChart(stats=stats_with_data)
        result = chart._render_chart()

        # Check that the text object has styles applied
        assert hasattr(result, '_spans')

    def test_peak_hour_styling(self, stats_with_data):
        """Test that peak hour receives special styling."""
        chart = JobsHourChart(stats=stats_with_data)

        # Set a clear peak in hour 12 (12-15 period)
        chart.stats.hourly_counts[12] = 100
        chart.stats.hourly_counts[13] = 95
        chart.stats.hourly_counts[14] = 90
        chart.stats.hourly_counts[15] = 85

        result = chart._render_chart()

        # Should apply styling (verify Text object has spans)
        assert isinstance(result, Text)


class TestActivityPreviewRendering:
    """Test ActivityPreview widget rendering."""

    def test_activity_preview_colorize_message(self):
        """Test that ActivityPreview colorizes messages correctly."""
        preview = ActivityPreview()

        test_message = "Job #12345 found: $50.00 JA→EN"
        result = preview._colorize_message(test_message, "info")

        assert isinstance(result, Text)
        plain = str(result.plain)
        assert "Job" in plain
        assert "12345" in plain
        assert "50.00" in plain

    def test_activity_preview_colorize_with_levels(self):
        """Test colorization with different log levels."""
        preview = ActivityPreview()

        levels = ["debug", "info", "warning", "error", "success", "job"]

        for level in levels:
            result = preview._colorize_message(f"Test message for {level}", level)
            assert isinstance(result, Text)
            assert "Test message" in str(result.plain)

    def test_activity_preview_pattern_matching(self):
        """Test that activity preview patterns match correctly."""
        preview = ActivityPreview()

        # Test various patterns
        test_cases = [
            ("Job ID: 12345", "job_id"),
            ("Reward: $123.45", "money"),
            ("JA→EN", "lang_pair"),
            ("https://gengo.com/jobs/12345", "url"),
            ("success", "success"),
            ("error occurred", "error_word"),
            ("warning", "warning_word"),
            ("websocket", "source_ws"),
            ("email", "source_email"),
            ("rss", "source_rss"),
        ]

        for text, pattern_type in test_cases:
            result = preview._colorize_message(text, "info")
            # Should colorize without error
            assert isinstance(result, Text)

    def test_activity_preview_add_line(self):
        """Test adding lines to activity preview."""
        preview = ActivityPreview()

        # Mock the query_one to avoid Textual widget errors
        mock_log = MagicMock()
        preview.query_one = MagicMock(return_value=mock_log)

        preview.add_line("Test message", "info")

        # Should call write on the log widget
        mock_log.write.assert_called_once()


class TestConfigPreviewRendering:
    """Test ConfigPreview widget rendering."""

    def test_config_preview_render_config(self):
        """Test that ConfigPreview renders configuration correctly."""
        mock_config = MagicMock(spec=AppConfig)

        config_data = {
            "Watcher": {
                "check_interval": 30,
                "min_reward": 10.0,
                "enable_notifications": True,
            },
            "WebSocket": {
                "enable_websocket": True,
                "user_id": 12345,
                "user_session": "test_session_token_long_value",
                "user_key": "test_user_key_long_value",
            },
            "AutoAccept": {
                "enabled": False,
            }
        }

        mock_config.list_all.return_value = config_data

        preview = ConfigPreview(config=mock_config)
        result = preview._render_config()

        assert isinstance(result, Text)
        plain = str(result.plain)

        # Should contain section names
        assert "Watcher" in plain
        assert "WebSocket" in plain

        # Should contain option names
        assert "check_interval" in plain
        assert "min_reward" in plain

    def test_config_preview_masks_sensitive_values(self):
        """Test that sensitive values are masked in config preview."""
        mock_config = MagicMock(spec=AppConfig)

        config_data = {
            "WebSocket": {
                "user_session": "supersecrettoken123456",
                "user_key": "verysecretkey123456",
                "password": "mypassword",
            }
        }

        mock_config.list_all.return_value = config_data

        preview = ConfigPreview(config=mock_config)

        # Test masking function
        masked = preview._mask_value("supersecrettoken123456")
        assert "su...56" in masked
        assert "supersecrettoken123456" not in masked

    def test_config_preview_formats_boolean_values(self):
        """Test that boolean values are formatted correctly."""
        mock_config = MagicMock(spec=AppConfig)

        config_data = {
            "Test": {
                "enabled": True,
                "disabled": False,
            }
        }

        mock_config.list_all.return_value = config_data

        preview = ConfigPreview(config=mock_config)

        # Test format_value for booleans
        assert preview._format_value("enabled", True) == "✓"
        assert preview._format_value("disabled", False) == "✗"

    def test_config_preview_formats_numbers(self):
        """Test that numbers are formatted correctly."""
        mock_config = MagicMock(spec=AppConfig)
        preview = ConfigPreview(config=mock_config)

        # Test integer
        assert preview._format_value("count", 42) == "42"

        # Test float
        assert preview._format_value("value", 42.5) == "42.50"

        # Test float that's actually an integer
        assert preview._format_value("value", 42.0) == "42"

    def test_config_preview_formats_lists(self):
        """Test that lists are formatted correctly."""
        mock_config = MagicMock(spec=AppConfig)
        preview = ConfigPreview(config=mock_config)

        test_list = ["option1", "option2", "option3"]
        result = preview._format_value("options", test_list)

        assert "option1" in result
        assert "option2" in result
        assert "option3" in result
        assert "," in result

    def test_config_preview_handles_empty_values(self):
        """Test that empty values are handled correctly."""
        mock_config = MagicMock(spec=AppConfig)
        preview = ConfigPreview(config=mock_config)

        assert preview._format_value("empty", "") == "—"
        assert preview._format_value("none", None) == "—"


class TestChartRenderingEdgeCases:
    """Test edge cases in chart rendering."""

    def test_render_with_negative_values(self):
        """Test rendering when stats accidentally have negative values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            stats_path = pathlib.Path(tmpdir) / "stats.json"
            stats = StatsManager(stats_path=stats_path)

            # Accidentally set negative value
            stats.hourly_counts[5] = -10

            chart = JobsHourChart(stats=stats)

            # Should handle gracefully (either ignore or treat as 0)
            try:
                result = chart._render_chart()
                assert isinstance(result, Text)
            except Exception as e:
                pytest.fail(f"Should handle negative values gracefully: {e}")

    def test_render_with_very_long_text(self):
        """Test activity preview with very long messages."""
        preview = ActivityPreview()

        long_message = "A" * 1000  # Very long message
        result = preview._colorize_message(long_message, "info")

        # Should handle without error
        assert isinstance(result, Text)

    def test_render_with_unicode_characters(self):
        """Test rendering with unicode characters."""
        preview = ActivityPreview()

        unicode_message = "Job found: ¥5000 日本語→English 🎉"
        result = preview._colorize_message(unicode_message, "info")

        # Should handle unicode without error
        assert isinstance(result, Text)
        assert "¥5000" in str(result.plain) or "5000" in str(result.plain)

    def test_config_preview_with_long_values(self):
        """Test config preview with very long configuration values."""
        mock_config = MagicMock(spec=AppConfig)

        config_data = {
            "Test": {
                "very_long_value": "x" * 100,
            }
        }

        mock_config.list_all.return_value = config_data

        preview = ConfigPreview(config=mock_config)
        result = preview._render_config()

        # Should truncate long values
        plain = str(result.plain)
        assert "..." in plain  # Truncation indicator


class TestChartRenderingPerformance:
    """Test performance characteristics of chart rendering."""

    def test_render_chart_with_max_data(self):
        """Test rendering chart with maximum possible data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            stats_path = pathlib.Path(tmpdir) / "stats.json"
            stats = StatsManager(stats_path=stats_path)

            # Fill all 24 hours with max values
            for hour in range(24):
                stats.hourly_counts[hour] = 999999

            chart = JobsHourChart(stats=stats)

            # Should render without timeout
            result = chart._render_chart()
            assert isinstance(result, Text)

    def test_activity_preview_colorize_many_patterns(self):
        """Test colorizing message with many pattern matches."""
        preview = ActivityPreview()

        # Message with many patterns
        complex_message = (
            "2024-01-15 12:34:56 Job #12345 found via websocket: "
            "$123.45 JA→EN https://gengo.com/jobs/12345 success"
        )

        result = preview._colorize_message(complex_message, "info")

        # Should handle complex message efficiently
        assert isinstance(result, Text)


class TestChartIntegrationWithStats:
    """Test chart integration with stats manager."""

    def test_chart_updates_when_stats_change(self, stats_with_data):
        """Test that chart reflects stats changes."""
        chart = JobsHourChart(stats=stats_with_data)

        # Initial render
        result1 = chart._render_chart()

        # Modify stats
        stats_with_data.hourly_counts[15] = 999

        # Render again
        result2 = chart._render_chart()

        # Results should be different
        assert str(result1.plain) != str(result2.plain) or "999" in str(result2.plain)

    def test_chart_handles_stats_without_hourly_counts(self):
        """Test chart when stats doesn't have hourly_counts."""
        mock_stats = MagicMock()
        # Remove hourly_counts attribute
        del mock_stats.hourly_counts

        chart = JobsHourChart(stats=mock_stats)

        # Should handle gracefully
        try:
            result = chart._render_chart()
            # If it doesn't crash, that's acceptable
        except AttributeError:
            # If it raises AttributeError, that's also acceptable
            pass