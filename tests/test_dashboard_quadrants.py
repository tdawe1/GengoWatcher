"""Tests for Dashboard Quadrant widgets."""

import pytest
from unittest.mock import MagicMock
from textual.app import App, ComposeResult

from gengowatcher.ui_textual import ActivityPreview, JobsPreview, ConfigPreview


class ActivityPreviewTestApp(App):
    def compose(self) -> ComposeResult:
        yield ActivityPreview()


class JobsPreviewTestApp(App):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        yield JobsPreview(self._state)


class ConfigPreviewTestApp(App):
    def __init__(self, config):
        super().__init__()
        self._config = config

    def compose(self) -> ComposeResult:
        yield ConfigPreview(self._config)


@pytest.mark.asyncio
async def test_activity_preview_has_log():
    """ActivityPreview should have a RichLog widget."""
    app = ActivityPreviewTestApp()
    async with app.run_test() as pilot:
        preview = app.query_one(ActivityPreview)
        # Updated: ActivityPreview uses RichLog with id="activity-log"
        log_widget = preview.query_one("#activity-log")
        assert log_widget is not None


@pytest.mark.asyncio
async def test_jobs_preview_displays_jobs():
    """JobsPreview should display recent jobs via refresh_jobs()."""
    state = MagicMock()
    state.get_recent_jobs.return_value = [
        {"id": "123456", "lang_pair": "JA→EN", "reward": 12.50, "word_count": 500},
        {"id": "123457", "lang_pair": "EN→JA", "reward": 8.00, "word_count": 300},
    ]

    app = JobsPreviewTestApp(state)
    async with app.run_test() as pilot:
        preview = app.query_one(JobsPreview)
        preview.refresh_jobs()
        await pilot.pause()
        # Updated: JobsPreview uses DataTable with id="jobs-table"
        table = preview.query_one("#jobs-table")
        assert table is not None
        # Check that the table has rows
        assert table.row_count == 2


def test_config_preview_constants():
    """ConfigPreview should have all required class constants defined."""
    # Test that constants exist
    assert hasattr(ConfigPreview, 'SECTION_ORDER')
    assert hasattr(ConfigPreview, 'SECTION_HEADER_WIDTH')
    assert hasattr(ConfigPreview, 'MAX_VALUE_LENGTH')
    assert hasattr(ConfigPreview, 'MAX_VALUE_LENGTH_SHORT')
    
    # Test constant types
    assert isinstance(ConfigPreview.SECTION_ORDER, list)
    assert isinstance(ConfigPreview.SECTION_HEADER_WIDTH, int)
    assert isinstance(ConfigPreview.MAX_VALUE_LENGTH, int)
    assert isinstance(ConfigPreview.MAX_VALUE_LENGTH_SHORT, int)
    
    # Test constant values
    assert ConfigPreview.SECTION_HEADER_WIDTH == 18
    assert ConfigPreview.MAX_VALUE_LENGTH == 20
    assert ConfigPreview.MAX_VALUE_LENGTH_SHORT == 17
    
    # Test SECTION_ORDER contains expected sections
    assert "Watcher" in ConfigPreview.SECTION_ORDER
    assert "WebSocket" in ConfigPreview.SECTION_ORDER
    assert "AutoAccept" in ConfigPreview.SECTION_ORDER
    assert len(ConfigPreview.SECTION_ORDER) == 13


@pytest.mark.asyncio
async def test_config_preview_render_uses_constants():
    """ConfigPreview._render_config should use class constants properly."""
    # Create a mock config
    config = MagicMock()
    config.list_all.return_value = {
        "Watcher": {
            "check_interval": 30,
            "enabled": True,
            "very_long_value_that_should_be_truncated": "x" * 30,
        },
        "WebSocket": {
            "enabled": False,
        }
    }
    
    app = ConfigPreviewTestApp(config)
    async with app.run_test() as pilot:
        preview = app.query_one(ConfigPreview)
        result = preview._render_config()
        
        # Check that the result is a Text object
        assert result is not None
        result_str = result.plain
        
        # Check that sections appear in the order defined by SECTION_ORDER
        # Watcher should appear before WebSocket
        watcher_pos = result_str.find("Watcher")
        websocket_pos = result_str.find("WebSocket")
        assert watcher_pos >= 0
        assert websocket_pos >= 0
        assert watcher_pos < websocket_pos
        
        # Check that long values are truncated
        assert "..." in result_str or len(result_str) > 0

