"""Tests for StatusIndicator and StatusRow widgets."""

import pytest
from unittest.mock import MagicMock
from textual.app import App, ComposeResult

from gengowatcher.ui_textual import StatusIndicator, StatusRow


class StatusIndicatorTestApp(App):
    def compose(self) -> ComposeResult:
        # Updated: StatusIndicator now takes (icon, name, **kwargs)
        yield StatusIndicator("●", "WebSocket")


class StatusRowTestApp(App):
    def __init__(self, watcher):
        super().__init__()
        self._watcher = watcher

    def compose(self) -> ComposeResult:
        yield StatusRow(self._watcher)


@pytest.mark.asyncio
async def test_status_indicator_displays_icon_and_state():
    """StatusIndicator should show icon and label text."""
    app = StatusIndicatorTestApp()
    async with app.run_test() as pilot:
        indicator = app.query_one(StatusIndicator)
        # Updated: use .status-label instead of .status-icon
        label_widget = indicator.query_one(".status-label")
        rendered = str(label_widget.render())
        assert "●" in rendered
        assert "WebSocket" in rendered


@pytest.mark.asyncio
async def test_status_indicator_set_state():
    """StatusIndicator.set_state should update CSS class."""
    app = StatusIndicatorTestApp()
    async with app.run_test() as pilot:
        indicator = app.query_one(StatusIndicator)
        indicator.set_state("error")
        await pilot.pause()
        # Check that the status-error class is applied
        assert indicator.has_class("status-error")


@pytest.mark.asyncio
async def test_status_row_renders_seven_indicators():
    """StatusRow should contain 7 status indicators."""
    watcher = MagicMock()
    watcher.websocket_connected = False
    watcher.email_monitor = MagicMock(enabled=False)
    watcher.website_monitor = MagicMock(enabled=False)

    app = StatusRowTestApp(watcher)
    async with app.run_test() as pilot:
        indicators = app.query(StatusIndicator)
        # Updated: Now 7 indicators (WS, Email, Web, RSS, Cap, Work, Auto)
        assert len(indicators) == 7
