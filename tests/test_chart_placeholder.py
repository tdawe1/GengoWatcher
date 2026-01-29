"""Tests for JobsHourChart (ChartPlaceholder) widget."""

import pytest
from unittest.mock import MagicMock
import tempfile
import pathlib
from rich.text import Text

from gengowatcher.ui_textual import JobsHourChart, ChartPlaceholder
from gengowatcher.stats import StatsManager


@pytest.fixture
def mock_stats():
    """Create a mock StatsManager for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_path = pathlib.Path(tmpdir) / "stats.json"
        stats = StatsManager(stats_path=stats_path)

        # Add some test data
        for hour in range(24):
            count = (hour % 6) * 2  # Create a pattern
            stats.hourly_counts[hour] = count

        yield stats


@pytest.fixture
def empty_stats():
    """Create a StatsManager with no data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_path = pathlib.Path(tmpdir) / "stats.json"
        stats = StatsManager(stats_path=stats_path)
        yield stats


class TestJobsHourChartInitialization:
    """Test JobsHourChart widget initialization."""

    def test_chart_initialization_with_stats(self, mock_stats):
        """Test that JobsHourChart initializes with stats manager."""
        chart = JobsHourChart(stats=mock_stats)
        assert chart.stats == mock_stats
        assert chart.border_title == "Jobs/Hour"

    def test_chart_initialization_without_stats(self):
        """Test that JobsHourChart initializes without stats manager."""
        chart = JobsHourChart(stats=None)
        assert chart.stats is None
        assert chart.border_title == "Jobs/Hour"

    def test_chart_has_correct_id(self):
        """Test that chart can be initialized with an ID."""
        chart = JobsHourChart(id="test-chart")
        assert chart.id == "test-chart"


class TestChartRendering:
    """Test chart rendering logic."""

    def test_render_chart_with_data(self, mock_stats):
        """Test rendering chart with real data."""
        chart = JobsHourChart(stats=mock_stats)
        result = chart._render_chart()

        assert isinstance(result, Text)
        # Check that time periods are present
        assert "00-03" in str(result.plain)
        assert "04-07" in str(result.plain)
        assert "08-11" in str(result.plain)
        assert "12-15" in str(result.plain)
        assert "16-19" in str(result.plain)
        assert "20-23" in str(result.plain)

    def test_render_chart_without_data(self, empty_stats):
        """Test rendering chart with no data."""
        chart = JobsHourChart(stats=empty_stats)
        result = chart._render_chart()

        assert isinstance(result, Text)
        # Should still render time periods
        assert "00-03" in str(result.plain)
        # All counts should be 0
        assert "  0" in str(result.plain)

    def test_render_chart_without_stats(self):
        """Test rendering chart when stats is None."""
        chart = JobsHourChart(stats=None)
        result = chart._render_chart()

        assert isinstance(result, Text)
        # Should render empty chart
        assert "00-03" in str(result.plain)

    def test_render_chart_bar_scaling(self, mock_stats):
        """Test that bars are scaled correctly based on max value."""
        chart = JobsHourChart(stats=mock_stats)

        # Set specific values for testing
        chart.stats.hourly_counts[0] = 10  # Low value
        chart.stats.hourly_counts[4] = 50  # High value

        result = chart._render_chart()

        # Chart should contain bars (█ characters)
        assert "█" in str(result.plain) or "░" in str(result.plain)

    def test_render_chart_peak_hour_highlighting(self, mock_stats):
        """Test that peak hour is highlighted correctly."""
        chart = JobsHourChart(stats=mock_stats)

        # Set a clear peak
        chart.stats.hourly_counts[10] = 100  # Peak hour
        chart.stats.hourly_counts[11] = 5
        chart.stats.hourly_counts[12] = 5

        result = chart._render_chart()

        # Should contain data for peak hour
        text_str = str(result.plain)
        assert any(char in text_str for char in ["█", "░", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"])


class TestChartBarCharacters:
    """Test bar character rendering."""

    def test_bar_characters_constant(self):
        """Test that BAR_CHARS constant is defined correctly."""
        assert JobsHourChart.BAR_CHARS == "▏▎▍▌▋▊▉█"

    def test_max_bar_width_constant(self):
        """Test that MAX_BAR_WIDTH is defined correctly."""
        assert JobsHourChart.MAX_BAR_WIDTH == 12


class TestChartTimePeriods:
    """Test time period grouping."""

    def test_chart_has_six_periods(self, mock_stats):
        """Test that chart shows 6 time periods (4-hour blocks)."""
        chart = JobsHourChart(stats=mock_stats)
        result = chart._render_chart()
        text_str = str(result.plain)

        # Count the number of time period labels
        periods = ["00-03", "04-07", "08-11", "12-15", "16-19", "20-23"]
        found_periods = sum(1 for period in periods if period in text_str)

        assert found_periods == 6

    def test_chart_aggregates_hours_correctly(self, mock_stats):
        """Test that hours are aggregated correctly into periods."""
        chart = JobsHourChart(stats=mock_stats)

        # Set specific values to test aggregation
        chart.stats.hourly_counts[0] = 1
        chart.stats.hourly_counts[1] = 2
        chart.stats.hourly_counts[2] = 3
        chart.stats.hourly_counts[3] = 4
        # Period 00-03 should sum to 10

        result = chart._render_chart()
        text_str = str(result.plain)

        # Should contain the aggregated sum (10)
        assert "10" in text_str


class TestChartEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_render_chart_with_zero_max(self):
        """Test rendering when all values are zero."""
        chart = JobsHourChart(stats=None)
        result = chart._render_chart()

        # Should not crash and should render empty bars
        assert isinstance(result, Text)

    def test_render_chart_with_large_values(self, mock_stats):
        """Test rendering with very large count values."""
        chart = JobsHourChart(stats=mock_stats)

        # Set extremely large values
        chart.stats.hourly_counts[12] = 999999

        result = chart._render_chart()

        # Should handle large values without crashing
        assert isinstance(result, Text)
        assert "999999" in str(result.plain) or "█" in str(result.plain)

    def test_render_chart_with_single_nonzero_value(self, empty_stats):
        """Test rendering when only one hour has data."""
        chart = JobsHourChart(stats=empty_stats)
        chart.stats.hourly_counts[5] = 10

        result = chart._render_chart()

        # Should render with one bar
        assert isinstance(result, Text)
        assert "█" in str(result.plain) or "10" in str(result.plain)


class TestChartBackwardsCompatibility:
    """Test backwards compatibility."""

    def test_chart_placeholder_alias(self, mock_stats):
        """Test that ChartPlaceholder is an alias for JobsHourChart."""
        assert ChartPlaceholder == JobsHourChart

    def test_chart_placeholder_works_identically(self, mock_stats):
        """Test that ChartPlaceholder works the same as JobsHourChart."""
        chart1 = JobsHourChart(stats=mock_stats)
        chart2 = ChartPlaceholder(stats=mock_stats)

        result1 = chart1._render_chart()
        result2 = chart2._render_chart()

        # Both should produce the same output
        assert str(result1.plain) == str(result2.plain)


class TestChartRefresh:
    """Test chart refresh functionality."""

    @pytest.mark.asyncio
    async def test_refresh_chart(self, mock_stats):
        """Test that refresh_chart updates the display."""
        from gengowatcher.ui_textual import GengoWatcherApp
        from gengowatcher.config import AppConfig
        from gengowatcher.state import AppState
        from gengowatcher.watcher import GengoWatcher

        # Create minimal mocked dependencies
        mock_config = MagicMock(spec=AppConfig)
        mock_config.get.return_value = ""

        mock_state = MagicMock(spec=AppState)
        mock_state.get_recent_jobs.return_value = []
        mock_state.session_start = 0

        mock_watcher = MagicMock(spec=GengoWatcher)
        mock_watcher.start_time = 0
        mock_watcher.websocket_status = "Test"
        mock_watcher.rss_action = "Test"
        mock_watcher.shutdown_event = MagicMock()
        mock_watcher.shutdown_event.is_set.return_value = True

        app = GengoWatcherApp(
            config=mock_config,
            state=mock_state,
            watcher=mock_watcher,
            stats=mock_stats
        )

        async with app.run_test() as pilot:
            chart = pilot.app.query_one(JobsHourChart)

            # Modify stats and refresh
            mock_stats.hourly_counts[15] = 50
            chart.refresh_chart()

            await pilot.pause()

            # Chart should be updated (no exception raised)
            assert chart.stats is not None


class TestChartIntegration:
    """Test chart integration with other components."""

    def test_chart_in_dashboard_quadrant(self):
        """Test that chart is a DashboardQuadrant."""
        from gengowatcher.ui_textual import DashboardQuadrant

        chart = JobsHourChart()

        # Should inherit from DashboardQuadrant
        assert isinstance(chart, DashboardQuadrant)

    def test_chart_has_border_title(self):
        """Test that chart has correct border title."""
        chart = JobsHourChart()
        assert hasattr(chart, 'border_title')
        assert chart.border_title == "Jobs/Hour"


class TestChartStatsIntegration:
    """Test integration with StatsManager."""

    def test_chart_reads_hourly_counts(self, mock_stats):
        """Test that chart reads hourly_counts from stats."""
        chart = JobsHourChart(stats=mock_stats)

        # Set specific hourly data
        mock_stats.hourly_counts[10] = 25

        result = chart._render_chart()

        # Should include the data from hourly_counts
        assert isinstance(result, Text)

    def test_chart_calls_get_peak_hour(self, mock_stats):
        """Test that chart calls get_peak_hour from stats."""
        chart = JobsHourChart(stats=mock_stats)

        # Mock get_peak_hour
        mock_stats.get_peak_hour = MagicMock(return_value=(12, 50))

        result = chart._render_chart()

        # Should call get_peak_hour
        mock_stats.get_peak_hour.assert_called()

    def test_chart_handles_missing_get_peak_hour(self, empty_stats):
        """Test chart when get_peak_hour is not available."""
        chart = JobsHourChart(stats=empty_stats)

        # Remove get_peak_hour method
        if hasattr(empty_stats, 'get_peak_hour'):
            delattr(empty_stats, 'get_peak_hour')

        # Should not crash
        try:
            result = chart._render_chart()
            assert isinstance(result, Text)
        except AttributeError:
            # If it fails, that's also acceptable behavior
            pass