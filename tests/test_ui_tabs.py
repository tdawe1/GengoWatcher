"""Tests for tabbed UI layout."""

import pytest
from unittest.mock import MagicMock
from collections import deque


def create_mock_app():
    """Create app with mocked dependencies for testing."""
    from gengowatcher.ui_textual import GengoWatcherApp

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
    mock_config.get.return_value = "test_value"
    mock_config.getboolean.return_value = True

    mock_state = MagicMock()
    mock_state.total_new_entries_found = 42
    mock_state.sparkline_data = [1.0, 2.5, 3.0, 2.0, 4.5]
    mock_state.get_job_count.return_value = 0
    mock_state.get_recent_jobs.return_value = []

    return GengoWatcherApp(
        watcher=mock_watcher,
        config=mock_config,
        state=mock_state,
        log_queue=deque(),
    )


@pytest.mark.asyncio
async def test_main_tabs_exist():
    """Verify main navigation tabs are present."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        # Check that TabbedContent exists with expected tabs
        tabbed = pilot.app.query_one("#main-tabs")
        assert tabbed is not None

        # Check tab panes exist
        tab_ids = [pane.id for pane in pilot.app.query("TabPane")]
        assert "dashboard" in tab_ids
        assert "jobs" in tab_ids
        assert "activity" in tab_ids
        assert "output" in tab_ids
        assert "charts" in tab_ids


@pytest.mark.asyncio
async def test_tab_switching_with_keys():
    """Test that number keys switch tabs."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        tabbed = pilot.app.query_one("#main-tabs")

        # Default should be dashboard
        assert tabbed.active == "dashboard"

        # Press 2 for Jobs
        await pilot.press("2")
        assert tabbed.active == "jobs"

        # Press 3 for Activity
        await pilot.press("3")
        assert tabbed.active == "activity"

        # Press 1 to go back to Dashboard
        await pilot.press("1")
        assert tabbed.active == "dashboard"


@pytest.mark.asyncio
async def test_dashboard_contains_panels():
    """Verify Dashboard tab contains RuntimeStatusPanel and HeaderPanel."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        # Should be on dashboard by default
        runtime = pilot.app.query_one("#runtime-panel")
        header = pilot.app.query_one("#header-panel")

        assert runtime is not None
        assert header is not None
