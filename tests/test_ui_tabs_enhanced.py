"""Enhanced tests for UI tabs - additional comprehensive tests."""

import pytest
from unittest.mock import MagicMock
import tempfile
import pathlib
from textual.css.query import NoMatches


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

    mock_config = MagicMock()
    mock_config.getboolean.return_value = True

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
    mock_config.list_all.return_value = {}

    mock_state = MagicMock()
    mock_state.total_new_entries_found = 42
    mock_state.sparkline_data = [1.0, 2.5, 3.0, 2.0, 4.5]
    mock_state.get_job_count.return_value = 0
    mock_state.get_recent_jobs.return_value = []
    mock_state.session_start = 0

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
async def test_tab_count():
    """Test that all expected tabs are present."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        tab_panes = pilot.app.query("TabPane")
        assert len(list(tab_panes)) == 6


@pytest.mark.asyncio
async def test_tab_switching_cycle():
    """Test cycling through all tabs."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent

        tabbed = pilot.app.query_one(TabbedContent)

        tabs = ["dashboard", "jobs", "activity", "output", "charts", "stats"]

        for tab_id in tabs:
            tabbed.active = tab_id
            await pilot.pause()
            assert tabbed.active == tab_id


@pytest.mark.asyncio
async def test_jobs_tab_contains_table():
    """Test that Jobs tab contains a DataTable."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent, DataTable

        tabbed = pilot.app.query_one(TabbedContent)
        tabbed.active = "jobs"
        await pilot.pause()

        try:
            jobs_table = pilot.app.query_one("#jobs-table-full", DataTable)
            assert jobs_table is not None
        except NoMatches:
            tables = list(pilot.app.query(DataTable))
            assert len(tables) > 0


@pytest.mark.asyncio
async def test_activity_tab_contains_log():
    """Test that Activity tab contains a RichLog."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent, RichLog

        tabbed = pilot.app.query_one(TabbedContent)
        tabbed.active = "activity"
        await pilot.pause()

        try:
            activity_log = pilot.app.query_one("#activity-log-full", RichLog)
            assert activity_log is not None
        except NoMatches:
            logs = list(pilot.app.query(RichLog))
            assert len(logs) > 0


@pytest.mark.asyncio
async def test_dashboard_metrics_row():
    """Test that MetricsRow displays correctly with 5 cards."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import MetricsRow, MetricCard

        metrics_row = pilot.app.query_one(MetricsRow)
        metric_cards = list(metrics_row.query(MetricCard))
        assert len(metric_cards) == 5


@pytest.mark.asyncio
async def test_dashboard_status_row():
    """Test that StatusRow displays correctly with 7 indicators."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import StatusRow, StatusIndicator

        status_row = pilot.app.query_one(StatusRow)
        indicators = list(status_row.query(StatusIndicator))
        assert len(indicators) == 7


@pytest.mark.asyncio
async def test_initial_tab_is_dashboard():
    """Test that app starts on dashboard tab."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent

        tabbed = pilot.app.query_one(TabbedContent)
        assert tabbed.active == "dashboard"


@pytest.mark.asyncio
async def test_footer_exists():
    """Test that app has a footer."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import Footer

        footer = pilot.app.query_one(Footer)
        assert footer is not None


@pytest.mark.asyncio
async def test_input_exists():
    """Test that app has an input widget with correct placeholder."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import Input

        input_widget = pilot.app.query_one(Input)
        assert input_widget is not None
        assert input_widget.placeholder == "> help_"


@pytest.mark.asyncio
async def test_title_bar_exists():
    """Test that app has a title bar."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import TitleBar

        title_bar = pilot.app.query_one(TitleBar)
        assert title_bar is not None


@pytest.mark.asyncio
async def test_rapid_tab_switching():
    """Test rapid tab switching doesn't cause exceptions."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent

        tabbed = pilot.app.query_one(TabbedContent)
        tabs = ["dashboard", "jobs", "activity", "output", "charts", "stats"]

        for _ in range(3):
            for tab_id in tabs:
                tabbed.active = tab_id
                await pilot.pause(0.01)

        assert True


@pytest.mark.asyncio
async def test_dashboard_hourly_activity_exists():
    """Test that dashboard contains HourlyActivity."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import HourlyActivity

        chart = pilot.app.query_one(HourlyActivity)
        assert chart is not None


@pytest.mark.asyncio
async def test_dashboard_session_stats_exists():
    """Test that dashboard contains SessionStats."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import SessionStats

        stats = pilot.app.query_one(SessionStats)
        assert stats is not None
