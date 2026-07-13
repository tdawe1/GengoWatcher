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
        assert "output" in tab_ids
        assert "charts" in tab_ids
        assert "telemetry" in tab_ids
        assert "api" in tab_ids


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

        # Switch to output tab
        tabbed.active = "output"
        await pilot.pause()
        assert tabbed.active == "output"


@pytest.mark.asyncio
async def test_tab_switching_all_tabs():
    """Test switching through all available tabs."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent

        tabbed = pilot.app.query_one(TabbedContent)
        tabs = [
            "dashboard",
            "jobs",
            "output",
            "charts",
            "telemetry",
            "api",
        ]

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
            TelemetryPanel,
        )

        # Should be on dashboard by default - check for widgets
        activity = pilot.app.query_one(ActivityPreview)
        jobs = pilot.app.query_one(JobsPreview)
        config = pilot.app.query_one(ConfigPreview)
        metrics = pilot.app.query_one(MetricsRow)
        status = pilot.app.query_one(StatusRow)
        telemetry = pilot.app.query_one(TelemetryPanel)

        assert activity is not None
        assert jobs is not None
        assert config is not None
        assert metrics is not None
        assert status is not None
        assert telemetry is not None


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
        with patch("gengowatcher.stats.datetime") as mock_datetime:
            # Add 5 jobs at hour 14
            mock_datetime.datetime.now.return_value = datetime.datetime(
                2024, 1, 1, 14, 0, 0
            )
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


@pytest.mark.asyncio
async def test_dashboard_contains_chart():
    """Verify Dashboard contains chart widget."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import HourlyActivity

        chart = pilot.app.query_one(HourlyActivity)
        assert chart is not None


@pytest.mark.asyncio
async def test_dashboard_contains_telemetry_panel():
    """Verify Dashboard contains telemetry panel widget."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import TelemetryPanel

        telemetry = pilot.app.query_one(TelemetryPanel)
        assert telemetry is not None


@pytest.mark.asyncio
async def test_jobs_tab_contains_datatable():
    """Verify Jobs tab contains DataTable."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent, DataTable
        from gengowatcher.ui_textual import JobsPanel

        tabbed = pilot.app.query_one(TabbedContent)
        tabbed.active = "jobs"
        await pilot.pause()

        # Check for jobs table
        panel = pilot.app.query_one(JobsPanel)
        table = pilot.app.query_one("#jobs-table-full", DataTable)
        assert table is not None
        assert panel.size.height > 0
        assert table.size.height > 0


@pytest.mark.asyncio
async def test_telemetry_tab_contains_visible_table():
    """Verify Telemetry tab table mounts with usable height."""
    app = create_mock_app()

    async with app.run_test(size=(160, 48)) as pilot:
        from gengowatcher.ui_textual import TelemetryTab
        from textual.widgets import TabbedContent, DataTable

        tabbed = pilot.app.query_one(TabbedContent)
        tabbed.active = "telemetry"
        await pilot.pause(0.2)

        tab = pilot.app.query_one(TelemetryTab)
        table = pilot.app.query_one("#telemetry-tab-table", DataTable)
        assert tab.size.height > 0
        assert table.size.height > 0
        assert table.row_count > 0


@pytest.mark.asyncio
async def test_jobs_tab_renders_accepted_workbench_job():
    """Accepted workbench data should render in the full Jobs table."""
    app = create_mock_app()
    app.state.get_recent_jobs.return_value = [
        {
            "id": "8012055",
            "title": "Japanese > English",
            "lang_pair": "JA→EN",
            "reward": 12.62,
            "source": "browser_worker",
            "timestamp": time.time(),
            "accepted": True,
            "accepted_expired": False,
            "accepted_time_left": "1h 45m",
            "accepted_unit_count": 263,
            "accepted_source_text": "Full source text for workflow.",
        }
    ]

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import JOBS_FULL_COLUMNS
        from textual.widgets import TabbedContent, DataTable

        tabbed = pilot.app.query_one(TabbedContent)
        tabbed.active = "jobs"
        await pilot.pause()

        table = pilot.app.query_one("#jobs-table-full", DataTable)
        labels = tuple(
            str(getattr(column.label, "plain", column.label))
            for column in table.columns.values()
        )
        assert labels == JOBS_FULL_COLUMNS
        assert table.row_count == 1

        row = [str(cell) for cell in table.get_row_at(0)]
        assert row[:7] == [
            "8012055",
            "JA→EN",
            "263",
            "$12.62",
            "browser_worker",
            "✓",
            "1h 45m",
        ]


@pytest.mark.asyncio
async def test_dashboard_activity_preview_contains_richlog():
    """Verify dashboard activity preview contains RichLog."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import RichLog

        await pilot.pause()

        # Check for dashboard activity log
        log = pilot.app.query_one("#activity-log", RichLog)
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
        assert "ind-api" in indicator_ids
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
        assert len(tabs) == 6  # dashboard, jobs, output, charts, telemetry, api


@pytest.mark.asyncio
async def test_dashboard_quadrants_exist():
    """Verify all dashboard quadrants are present."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import (
            JobsPreview,
            HourlyActivity,
            ConfigPreview,
            TelemetryPanel,
        )

        # All four quadrants should exist
        jobs_preview = pilot.app.query_one(JobsPreview)
        chart = pilot.app.query_one(HourlyActivity)
        config = pilot.app.query_one(ConfigPreview)
        session = pilot.app.query_one(TelemetryPanel)

        assert jobs_preview is not None
        assert chart is not None
        assert config is not None
        assert session is not None


@pytest.mark.asyncio
async def test_dashboard_refresh_targets_match_mounted_widgets():
    """Required dashboard refresh targets should all be mounted widgets."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from gengowatcher.ui_textual import (
            HourlyActivity,
            JobsPreview,
            MetricsRow,
            TelemetryPanel,
        )

        expected_targets = [
            (MetricsRow, "refresh_metrics"),
            (JobsPreview, "refresh_jobs"),
            (HourlyActivity, "refresh_hourly"),
            (TelemetryPanel, "refresh_telemetry"),
        ]

        assert app._dashboard_refresh_targets() == expected_targets
        for widget_class, _ in expected_targets:
            assert pilot.app.query_one(widget_class) is not None


@pytest.mark.asyncio
async def test_app_bindings_defined():
    """Verify app has key bindings defined."""
    app = create_mock_app()

    assert hasattr(app, "BINDINGS")
    assert len(app.BINDINGS) > 0

    # Check for expected bindings
    binding_keys = [
        b.key if hasattr(b, "key") else b[0] for b in app.BINDINGS if b is not None
    ]
    assert "q" in binding_keys  # quit
    assert "c" in binding_keys  # check
    assert "p" in binding_keys  # pause


@pytest.mark.asyncio
async def test_plain_q_exits_when_command_prompt_is_empty():
    """Bare q should quit instead of being typed into the bottom prompt."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause(0.1)

        assert pilot.app.is_running is False


@pytest.mark.asyncio
async def test_q_is_typed_into_command_prompt_when_not_empty():
    """q should be input text once the command prompt already has content."""
    from textual.widgets import Input

    app = create_mock_app()

    async with app.run_test() as pilot:
        prompt = pilot.app.query_one(Input)
        prompt.focus()
        await pilot.press("h")
        await pilot.press("q")
        await pilot.pause(0.1)

        assert pilot.app.is_running is True
        assert prompt.value.endswith("q")


@pytest.mark.asyncio
async def test_tab_switching_performance():
    """Test rapid tab switching doesn't cause issues."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent

        tabbed = pilot.app.query_one(TabbedContent)
        tabs = [
            "dashboard",
            "jobs",
            "output",
            "charts",
            "telemetry",
            "api",
        ]

        # Rapidly switch tabs
        for _ in range(3):
            for tab in tabs:
                tabbed.active = tab
                await pilot.pause(0.01)  # Small pause

        # Should end on last tab
        assert tabbed.active == "api"


@pytest.mark.asyncio
async def test_app_css_path_defined():
    """Verify app has CSS path defined."""
    app = create_mock_app()

    assert hasattr(app, "CSS_PATH")
    assert app.CSS_PATH is not None


def test_sources_breakdown_removed_from_ui_module():
    """Unused SourcesBreakdown should stay removed from the UI module."""
    import gengowatcher.ui_textual as ui_textual

    assert not hasattr(ui_textual, "SourcesBreakdown")
