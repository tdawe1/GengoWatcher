"""Tests for TitleBar widget."""

import pytest
from textual.app import App, ComposeResult

from gengowatcher.ui_textual import TitleBar


class TitleBarTestApp(App):
    def compose(self) -> ComposeResult:
        yield TitleBar()


@pytest.mark.asyncio
async def test_title_bar_renders():
    """TitleBar should render brand, session time, and clock."""
    app = TitleBarTestApp()
    async with app.run_test():
        title_bar = app.query_one(TitleBar)
        assert title_bar is not None

        # Check brand text exists
        brand = title_bar.query_one(".brand")
        assert "GENGOWATCHER" in str(brand.render())


@pytest.mark.asyncio
async def test_title_bar_session_time_updates():
    """Session time should be displayed."""
    app = TitleBarTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()  # Allow timer to tick
        # Updated: use #session-timer instead of #session-time
        session_time = app.query_one("#session-timer")
        content = str(session_time.render())
        # Session time shows format: "Session: Xh XXm"
        assert "Session:" in content
