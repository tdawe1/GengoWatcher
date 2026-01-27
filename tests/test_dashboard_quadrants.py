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
