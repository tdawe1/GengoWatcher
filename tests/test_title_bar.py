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
    async with app.run_test() as pilot:
        title_bar = app.query_one(TitleBar)
        assert title_bar is not None

        # Check brand text exists
        brand = title_bar.query_one(".brand")
        # In newer Textual, we might need to check the renderable directly or use render()
        # For Static, it often holds a Text object or string.
        # Let's try checking the widget's content via its renderable property if available,
        # or fall back to checking what we expect it to render.
        # Since 'renderable' attribute failed, let's try accessing the content directly if it's a Static.
        # Static usually has 'update' method but extracting content is tricky if not exposed.
        # However, for testing, we can often rely on the fact that Static stores its content.
        # Let's try using the .render() method which should return the content.
        assert "GENGOWATCHER" in str(brand.render())


@pytest.mark.asyncio
async def test_title_bar_session_time_updates():
    """Session time should be displayed."""
    app = TitleBarTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()  # Allow timer to tick
        session_time = app.query_one("#session-time")
        content = str(session_time.render())
        assert "Session:" in content
