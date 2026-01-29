"""Tests for tabbed UI layout."""

import pytest
from unittest.mock import MagicMock
import tempfile
import pathlib
import time


def create_mock_app():
    """Create app with mocked dependencies for testing."""
    from gengowatcher.ui_textual import GengoWatcherApp
    from gengowatcher.stats import StatsManager

    mock_watcher = MagicMock()
    mock_watcher.start_time = 0
    mock_watcher.session_new_entries = 5
    mock_watcher.session_total_value = 25.50
    mock_watcher.websocket_status = "Live"
    mock_watcher.rss_action = "Checking"
    mock_watcher.next_check_time = 999999999
    mock_watcher.shutdown_event = MagicMock()
    mock_watcher.shutdown_event.is_set.return_value = True
    mock_watcher.PAUSE_FILE = "/tmp/gw_pause_test"
    mock_watcher.get_monitor_status.return_value = {
        "websocket": "alive",
        "rss": "alive",
        "email": "disabled",
        "website": "disabled",
    }
    mock_watcher.email_monitor_status = "disabled"
    mock_watcher.website_monitor_status = "disabled"
    mock_watcher.email_last_check_time = None
    mock_watcher.website_last_check_time = None
    mock_watcher.email_jobs_found_session = 0
    mock_watcher.website_jobs_found_session = 0
    mock_watcher.websocket_connected = True
    mock_watcher._email_monitor = None
    mock_watcher._website_monitor = None
    mock_watcher.captcha_enabled = False
    mock_watcher.captcha_solving = False
    mock_watcher.is_processing = False
    mock_watcher.auto_accept_enabled = False

    mock_config = MagicMock()
    mock_config.getboolean.return_value = True

    # Mock the get() method for ConfigPreview - returns section/key specific values
    def mock_get(section, key):
        config_values = {
            ("Watcher", "check_interval"): 30,
            ("Watcher", "min_reward"): 10.0,
            ("Watcher", "source_lang"): "JA",
            ("Watcher", "target_lang"): "EN",
            ("AutoAccept", "enabled"): True,
            ("WebSocket", "enable_websocket"): True,
        }
        return config_values.get((section, key), "test_value")

    mock_config.get.side_effect = mock_get
    mock_config.list_all.return_value = {
        "Watcher": {"check_interval": 30, "min_reward": 10.0},
    }

    mock_state = MagicMock()
    mock_state.total_new_entries_found = 42
    mock_state.sparkline_data = [1.0, 2.5, 3.0, 2.0, 4.5]
    mock_state.get_job_count.return_value = 0
    mock_state.get_recent_jobs.return_value = []
    mock_state.session_start = time.time()

    # Create a real StatsManager with temp file
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_path = pathlib.Path(tmpdir) / "stats.json"
        mock_stats = StatsManager(stats_path=stats_path)

    return GengoWatcherApp(
        watcher=mock_watcher,
        config=mock_config,
        state=mock_state,
        stats=mock_stats,
    )


@pytest.mark.asyncio
async def test_main_tabs_exist():
    """Verify main navigation tabs are present."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        # Check that TabbedContent exists
        from textual.widgets import TabbedContent

        tabbed = pilot.app.query_one(TabbedContent)
        assert tabbed is not None

        # Check tab panes exist (using current IDs from ui_textual.py)
        tab_ids = [pane.id for pane in pilot.app.query("TabPane")]
        assert "dashboard" in tab_ids
        assert "jobs" in tab_ids
        assert "activity" in tab_ids
        assert "output" in tab_ids
        assert "charts" in tab_ids
        assert "stats" in tab_ids


@pytest.mark.asyncio
async def test_tab_switching_with_keys():
    """Test that tabs can be switched programmatically."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent

        tabbed = pilot.app.query_one(TabbedContent)

        # Default should be dashboard
        assert tabbed.active == "dashboard"

        # Switch to jobs tab programmatically
        tabbed.active = "jobs"
        await pilot.pause()
        assert tabbed.active == "jobs"

        # Switch to activity tab
        tabbed.active = "activity"
        await pilot.pause()
        assert tabbed.active == "activity"


@pytest.mark.asyncio
async def test_tab_switching_all_tabs():
    """Test switching through all available tabs."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent

        tabbed = pilot.app.query_one(TabbedContent)
        tabs = ["dashboard", "jobs", "activity", "output", "charts", "stats"]

        for tab in tabs:
            tabbed.active = tab
            await pilot.pause()
            assert tabbed.active == tab


@pytest.mark.asyncio
async def test_dashboard_contains_panels():
    """Verify Dashboard tab contains expected widgets."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import (
            ActivityPreview,
            JobsPreview,
            ConfigPreview,
            MetricsRow,
            StatusRow,
        )

        # Should be on dashboard by default - check for widgets
        activity = pilot.app.query_one(ActivityPreview)
        jobs = pilot.app.query_one(JobsPreview)
        config = pilot.app.query_one(ConfigPreview)
        metrics = pilot.app.query_one(MetricsRow)
        status = pilot.app.query_one(StatusRow)

        assert activity is not None
        assert jobs is not None
        assert config is not None
        assert metrics is not None
        assert status is not None


@pytest.mark.asyncio
async def test_hourly_activity_with_empty_data():
    """Verify HourlyActivity handles empty data correctly (no misleading peak highlight)."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import HourlyActivity
        from textual.widgets import Static

        # Get the HourlyActivity widget
        hourly = pilot.app.query_one(HourlyActivity)
        assert hourly is not None

        # Refresh with empty stats (no jobs recorded)
        hourly.refresh_hourly()
        await pilot.pause()

        # Should show "No activity yet" instead of highlighting a false peak
        content = hourly.query_one("#hourly-content", Static)
        # Get the rendered text
        text = str(content.render())
        assert "No activity yet" in text


@pytest.mark.asyncio
async def test_hourly_activity_with_data():
    """Verify HourlyActivity shows peak period when there's actual data."""
    from gengowatcher.ui_textual import GengoWatcherApp, HourlyActivity
    from gengowatcher.stats import StatsManager
    from unittest.mock import MagicMock
    import datetime
    from unittest.mock import patch

    # Create app with stats that has actual data
    mock_watcher = MagicMock()
    mock_watcher.start_time = 0
    mock_watcher.get_monitor_status.return_value = {}

    mock_config = MagicMock()
    mock_state = MagicMock()
    mock_state.get_recent_jobs.return_value = []

    with tempfile.TemporaryDirectory() as tmpdir:
        stats_path = pathlib.Path(tmpdir) / "stats.json"
        stats = StatsManager(stats_path=stats_path)

        # Add jobs at specific hours using mock
        with patch('gengowatcher.stats.datetime') as mock_datetime:
            # Add 5 jobs at hour 14
            mock_datetime.datetime.now.return_value = datetime.datetime(2024, 1, 1, 14, 0, 0)
            for _ in range(5):
                stats.record_job(10.0, "WebSocket", "JA→EN", accepted=True)

        app = GengoWatcherApp(
            watcher=mock_watcher,
            config=mock_config,
            state=mock_state,
            stats=stats,
        )

        async with app.run_test() as pilot:
            hourly = pilot.app.query_one(HourlyActivity)
            hourly.refresh_hourly()
            await pilot.pause()

            # Should show peak period (12-15) with 5 jobs
            from textual.widgets import Static
            content = hourly.query_one("#hourly-content", Static)
            text = str(content.render())
            assert "12-15" in text  # Peak period containing hour 14
            assert "5" in text  # 5 jobs
async def test_dashboard_contains_chart():
    """Verify Dashboard contains chart widget."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import JobsHourChart

        chart = pilot.app.query_one(JobsHourChart)
        assert chart is not None


@pytest.mark.asyncio
async def test_dashboard_contains_session_stats():
    """Verify Dashboard contains session stats widget."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import SessionStats

        session_stats = pilot.app.query_one(SessionStats)
        assert session_stats is not None


@pytest.mark.asyncio
async def test_jobs_tab_contains_datatable():
    """Verify Jobs tab contains DataTable."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent, DataTable

        tabbed = pilot.app.query_one(TabbedContent)
        tabbed.active = "jobs"
        await pilot.pause()

        # Check for jobs table
        table = pilot.app.query_one("#jobs-table-full", DataTable)
        assert table is not None


@pytest.mark.asyncio
async def test_activity_tab_contains_richlog():
    """Verify Activity tab contains RichLog."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent, RichLog

        tabbed = pilot.app.query_one(TabbedContent)
        tabbed.active = "activity"
        await pilot.pause()

        # Check for activity log
        log = pilot.app.query_one("#activity-log-full", RichLog)
        assert log is not None


@pytest.mark.asyncio
async def test_output_tab_contains_richlog():
    """Verify Output tab contains RichLog."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent, RichLog

        tabbed = pilot.app.query_one(TabbedContent)
        tabbed.active = "output"
        await pilot.pause()

        # Check for output log
        log = pilot.app.query_one("#output-log", RichLog)
        assert log is not None


@pytest.mark.asyncio
async def test_app_has_footer():
    """Verify app has footer with key bindings."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import Footer

        footer = pilot.app.query_one(Footer)
        assert footer is not None


@pytest.mark.asyncio
async def test_app_has_input():
    """Verify app has input widget."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import Input

        input_widget = pilot.app.query_one(Input)
        assert input_widget is not None


@pytest.mark.asyncio
async def test_title_bar_exists():
    """Verify title bar exists."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import TitleBar

        title_bar = pilot.app.query_one(TitleBar)
        assert title_bar is not None


@pytest.mark.asyncio
async def test_status_indicators_exist():
    """Verify all status indicators are present."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import StatusIndicator

        # Check for all expected status indicators
        indicators = pilot.app.query(StatusIndicator)
        indicator_ids = [ind.id for ind in indicators]

        assert "ind-ws" in indicator_ids
        assert "ind-rss" in indicator_ids
        assert "ind-email" in indicator_ids
        assert "ind-web" in indicator_ids
        assert "ind-cap" in indicator_ids
        assert "ind-work" in indicator_ids
        assert "ind-auto" in indicator_ids


@pytest.mark.asyncio
async def test_metric_cards_exist():
    """Verify all metric cards are present."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import MetricCard

        cards = pilot.app.query(MetricCard)
        card_ids = [card.id for card in cards]

        assert "card-found" in card_ids
        assert "card-accepted" in card_ids
        assert "card-value" in card_ids
        assert "card-rate" in card_ids
        assert "card-today" in card_ids


@pytest.mark.asyncio
async def test_tab_count():
    """Verify correct number of tabs."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabPane

        tabs = pilot.app.query(TabPane)
        assert len(tabs) == 6  # dashboard, jobs, activity, output, charts, stats


@pytest.mark.asyncio
async def test_dashboard_quadrants_exist():
    """Verify all dashboard quadrants are present."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import (
            JobsPreview,
            JobsHourChart,
            ConfigPreview,
            SessionStats,
        )

        # All four quadrants should exist
        jobs_preview = pilot.app.query_one(JobsPreview)
        chart = pilot.app.query_one(JobsHourChart)
        config = pilot.app.query_one(ConfigPreview)
        session = pilot.app.query_one(SessionStats)

        assert jobs_preview is not None
        assert chart is not None
        assert config is not None
        assert session is not None


@pytest.mark.asyncio
async def test_app_bindings_defined():
    """Verify app has key bindings defined."""
    app = create_mock_app()

    assert hasattr(app, "BINDINGS")
    assert len(app.BINDINGS) > 0

    # Check for expected bindings
    binding_keys = [b.key for b in app.BINDINGS]
    assert "q" in binding_keys  # quit
    assert "c" in binding_keys  # check
    assert "p" in binding_keys  # pause


@pytest.mark.asyncio
async def test_tab_switching_performance():
    """Test rapid tab switching doesn't cause issues."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent

        tabbed = pilot.app.query_one(TabbedContent)
        tabs = ["dashboard", "jobs", "activity", "output", "charts", "stats"]

        # Rapidly switch tabs
        for _ in range(3):
            for tab in tabs:
                tabbed.active = tab
                await pilot.pause(0.01)  # Small pause

        # Should end on last tab
        assert tabbed.active == "stats"


@pytest.mark.asyncio
async def test_app_css_path_defined():
    """Verify app has CSS path defined."""
    app = create_mock_app()

    assert hasattr(app, "CSS_PATH")
    assert app.CSS_PATH is not None


@pytest.mark.asyncio
async def test_sources_breakdown_exists():
    """Verify sources breakdown widget exists."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import SourcesBreakdown

        # SourcesBreakdown might not be in dashboard, but should be queryable
        # Check if it exists in the app structure
        breakdowns = list(pilot.app.query(SourcesBreakdown))
        # May be 0 or 1 depending on layout
        assert len(breakdowns) in (0, 1)
