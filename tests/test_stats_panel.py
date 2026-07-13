"""Tests for StatsPanel widget."""

import pytest
import tempfile
import pathlib
from textual.app import App, ComposeResult

from gengowatcher.stats import StatsManager
from gengowatcher.ui_textual import StatsPanel


class StatsPanelTestApp(App):
    def __init__(self, stats_manager):
        super().__init__()
        self._stats = stats_manager

    def compose(self) -> ComposeResult:
        yield StatsPanel(self._stats)


@pytest.mark.asyncio
async def test_stats_panel_renders_sections():
    """StatsPanel should render all stat sections."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        app = StatsPanelTestApp(manager)
        async with app.run_test():
            panel = app.query_one(StatsPanel)
            # Check section titles exist
            assert panel.query_one("#stats-session-content") is not None
            assert panel.query_one("#stats-alltime-content") is not None


@pytest.mark.asyncio
async def test_stats_panel_refresh_updates_content():
    """StatsPanel.refresh_stats should update displayed values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)
        manager.record_job(50.0, "WebSocket", "JA→EN", accepted=True)

        app = StatsPanelTestApp(manager)
        async with app.run_test() as pilot:
            panel = app.query_one(StatsPanel)
            panel.refresh_stats()
            await pilot.pause()

            session_content = panel.query_one("#stats-session-content")
            # Use render() for checking Static content
            rendered = str(session_content.render())
            assert "1" in rendered  # jobs_found
