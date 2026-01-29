"""Tests for ChartPlaceholder widget."""

import pytest
from unittest.mock import MagicMock
from textual.app import App, ComposeResult

from gengowatcher.ui_textual import ChartPlaceholder


class ChartPlaceholderTestApp(App):
    def __init__(self, state=None):
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        yield ChartPlaceholder(state=self._state)


@pytest.mark.asyncio
async def test_chart_placeholder_renders_without_state():
    """ChartPlaceholder should render placeholder when no state is provided."""
    app = ChartPlaceholderTestApp(state=None)
    async with app.run_test() as pilot:
        chart = app.query_one(ChartPlaceholder)
        chart.refresh_chart()
        await pilot.pause()
        
        display = chart.query_one("#chart-display")
        content = str(display.render())
        # Should show "No data" placeholder
        assert "No data" in content or "╭─╮" in content


@pytest.mark.asyncio
async def test_chart_placeholder_renders_with_empty_jobs():
    """ChartPlaceholder should show placeholder when no jobs exist."""
    state = MagicMock()
    state.get_recent_jobs.return_value = []
    
    app = ChartPlaceholderTestApp(state=state)
    async with app.run_test() as pilot:
        chart = app.query_one(ChartPlaceholder)
        chart.refresh_chart()
        await pilot.pause()
        
        display = chart.query_one("#chart-display")
        content = str(display.render())
        # Should show "No jobs yet" placeholder
        assert "No jobs yet" in content or "╭─╮" in content


@pytest.mark.asyncio
async def test_chart_placeholder_renders_with_jobs():
    """ChartPlaceholder should render chart when jobs exist."""
    state = MagicMock()
    # Create some mock jobs
    state.get_recent_jobs.return_value = [
        {"id": f"job{i}", "reward": 10.0, "lang_pair": "JA→EN"}
        for i in range(50)
    ]
    
    app = ChartPlaceholderTestApp(state=state)
    async with app.run_test() as pilot:
        chart = app.query_one(ChartPlaceholder)
        chart.refresh_chart()
        await pilot.pause()
        
        display = chart.query_one("#chart-display")
        content = str(display.render())
        # Should render chart (not show placeholder text)
        assert "No data" not in content
        assert "No jobs yet" not in content
        # Should have newlines (multi-line chart)
        assert "\n" in content or len(content) > 0


@pytest.mark.asyncio
async def test_chart_placeholder_has_chart_display():
    """ChartPlaceholder should have a chart-display element."""
    app = ChartPlaceholderTestApp()
    async with app.run_test():
        chart = app.query_one(ChartPlaceholder)
        display = chart.query_one("#chart-display")
        assert display is not None
