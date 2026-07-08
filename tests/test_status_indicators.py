"""Tests for StatusIndicator and StatusRow widgets."""

import pytest
from unittest.mock import MagicMock
from textual.app import App, ComposeResult

from gengowatcher.ui_textual import StatusIndicator, StatusRow


class StatusIndicatorTestApp(App):
    def compose(self) -> ComposeResult:
        # StatusIndicator takes (base_icon, name, id=...)
        yield StatusIndicator("●", "WebSocket", id="test-ws")


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
        # Check the label widget
        label_widget = indicator.query_one(".status-label")
        rendered = str(label_widget.render())
        # Default state is idle, so shows empty circle
        assert "○" in rendered or "●" in rendered
        assert "WebSocket" in rendered


@pytest.mark.asyncio
async def test_status_indicator_set_state():
    """StatusIndicator.set_state should update CSS class and icon."""
    app = StatusIndicatorTestApp()
    async with app.run_test() as pilot:
        indicator = app.query_one(StatusIndicator)

        # Set to live state
        indicator.set_state("live")
        await pilot.pause()
        assert indicator.has_class("status-live")

        # Set to error state
        indicator.set_state("error")
        await pilot.pause()
        assert indicator.has_class("status-error")
        assert not indicator.has_class("status-live")


@pytest.mark.asyncio
async def test_status_indicator_updates_detail_when_state_is_unchanged():
    app = StatusIndicatorTestApp()
    async with app.run_test() as pilot:
        indicator = app.query_one(StatusIndicator)
        label_widget = indicator.query_one(".status-label")

        indicator.set_state("live", "starting")
        await pilot.pause()
        assert "starting" in str(label_widget.render())

        indicator.set_state("live", "ready")
        await pilot.pause()
        rendered = str(label_widget.render())
        assert "ready" in rendered
        assert "starting" not in rendered


@pytest.mark.asyncio
async def test_status_row_renders_eight_indicators():
    """StatusRow should contain 8 status indicators."""
    watcher = MagicMock()
    watcher.websocket_connected = False
    watcher.websocket_status = ""
    watcher.email_monitor_status = ""
    watcher.website_monitor_status = ""
    watcher.rss_action = ""
    watcher.is_processing = False
    watcher.auto_accept_enabled = False

    app = StatusRowTestApp(watcher)
    async with app.run_test() as pilot:
        indicators = app.query(StatusIndicator)
        # 8 indicators: WS, RSS, HTTP, Mail, Web, Cap, Flow, Auto
        assert len(indicators) == 8


@pytest.mark.asyncio
async def test_status_indicator_pulse_animation():
    """StatusIndicator should pulse when in live state."""
    app = StatusIndicatorTestApp()
    async with app.run_test() as pilot:
        indicator = app.query_one(StatusIndicator)
        indicator.set_state("live")

        # Let the pulse timer tick a few times
        await pilot.pause(0.6)
        await pilot.pause(0.6)

        # Should still be in live state
        assert indicator.has_class("status-live")
