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
    mock_config.getboolean.return_value = True

    # Mock the get() method for ConfigPreview - returns section/key specific values
    def mock_get(section, key):
        config_values = {
            ("Watcher", "check_interval"): 30,
            ("Watcher", "min_reward"): 10.0,
            ("AutoAccept", "enabled"): True,
            ("WebSocket", "enable_websocket"): True,
        }
        return config_values.get((section, key), "test_value")

    mock_config.get.side_effect = mock_get

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
        assert "dashboard-tab" in tab_ids
        assert "jobs-tab" in tab_ids
        assert "activity-tab" in tab_ids
        assert "debug-tab" in tab_ids
        assert "charts-tab" in tab_ids
        assert "stats-tab" in tab_ids


@pytest.mark.asyncio
async def test_tab_switching_with_keys():
    """Test that number keys switch tabs."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        # Ensure input doesn't capture keys
        pilot.app.set_focus(None)

        tabbed = pilot.app.query_one("#main-tabs")

        # Default should be dashboard
        assert tabbed.active == "dashboard-tab"

        # Press 2 for Jobs
        await pilot.press("2")
        assert tabbed.active == "jobs-tab"

        # Press 3 for Activity
        await pilot.press("3")
        assert tabbed.active == "activity-tab"

        # Press 6 for Stats
        await pilot.press("6")
        assert tabbed.active == "stats-tab"

        # Press 1 to go back to Dashboard
        await pilot.press("1")
        assert tabbed.active == "dashboard-tab"


@pytest.mark.asyncio
async def test_dashboard_contains_panels():
    """Verify Dashboard tab contains new preview panels."""
    app = create_mock_app()

    async with app.run_test() as pilot:
        # Should be on dashboard by default
        activity = pilot.app.query_one("#activity-preview")
        jobs = pilot.app.query_one("#jobs-preview")
        config = pilot.app.query_one("#config-preview")

        assert activity is not None
        assert jobs is not None
        assert config is not None
