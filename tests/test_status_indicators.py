"""Tests for StatusIndicator and StatusRow widgets."""

import pytest
from unittest.mock import MagicMock
from textual.app import App, ComposeResult

from gengowatcher.ui_textual import StatusIndicator, StatusRow


class StatusIndicatorTestApp(App):
    def compose(self) -> ComposeResult:
        yield StatusIndicator("WebSocket", "live")


class StatusRowTestApp(App):
    def __init__(self, watcher):
        super().__init__()
        self._watcher = watcher

    def compose(self) -> ComposeResult:
        yield StatusRow(self._watcher)


@pytest.mark.asyncio
async def test_status_indicator_displays_icon_and_state():
    """StatusIndicator should show icon and state text."""
    app = StatusIndicatorTestApp()
    async with app.run_test() as pilot:
        indicator = app.query_one(StatusIndicator)
        # Check icon is rendered
        icon_widget = indicator.query_one(".status-icon")
        assert "●" in str(icon_widget.render())
        assert "WEBSOCKET" in str(icon_widget.render())


@pytest.mark.asyncio
async def test_status_indicator_set_state():
    """StatusIndicator.set_state should update display."""
    app = StatusIndicatorTestApp()
    async with app.run_test() as pilot:
        indicator = app.query_one(StatusIndicator)
        indicator.set_state("error")
        await pilot.pause()
        status_text = indicator.query_one(".status-text")
        assert "Error" in str(status_text.render())


@pytest.mark.asyncio
async def test_status_row_renders_five_indicators():
    """StatusRow should contain 5 status indicators."""
    watcher = MagicMock()
    watcher.websocket_connected = False
    watcher.email_monitor = MagicMock(enabled=False)
    watcher.website_monitor = MagicMock(enabled=False)

    app = StatusRowTestApp(watcher)
    async with app.run_test() as pilot:
        indicators = app.query(StatusIndicator)
        assert len(indicators) == 5
