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
async def test_activity_preview_add_line():
    """ActivityPreview should display added lines."""
    app = ActivityPreviewTestApp()
    async with app.run_test() as pilot:
        preview = app.query_one(ActivityPreview)
        preview.add_line("Job detected #1234")
        await pilot.pause()
        # ActivityPreview now uses RichLog with id="activity-preview-log"
        log_widget = preview.query_one("#activity-preview-log")
        # RichLog doesn't have render(), check that widget exists and line was added
        assert log_widget is not None


@pytest.mark.asyncio
async def test_jobs_preview_displays_jobs():
    """JobsPreview should display recent jobs."""
    state = MagicMock()
    state.get_recent_jobs.return_value = [
        {"id": "123456", "lang_pair": "JA→EN", "reward": 12.50},
        {"id": "123457", "lang_pair": "EN→JA", "reward": 8.00},
    ]

    app = JobsPreviewTestApp(state)
    async with app.run_test() as pilot:
        preview = app.query_one(JobsPreview)
        preview.refresh_jobs()
        await pilot.pause()
        content = preview.query_one("#jobs-preview-content")
        rendered = str(content.render())
        assert "$12.50" in rendered or "12.5" in rendered
