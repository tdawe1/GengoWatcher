"""Tests for MetricCard and MetricsRow widgets."""

import pytest
from unittest.mock import MagicMock
from textual.app import App, ComposeResult

from gengowatcher.ui_textual import MetricCard, MetricsRow


class MetricCardTestApp(App):
    def compose(self) -> ComposeResult:
        # Updated: MetricCard now takes (label, icon, value, **kwargs)
        yield MetricCard("Found", "▲", "42", classes="found")


class MetricsRowTestApp(App):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        yield MetricsRow(self._state)


@pytest.mark.asyncio
async def test_metric_card_displays_value():
    """MetricCard should display label and value."""
    app = MetricCardTestApp()
    async with app.run_test() as pilot:
        card = app.query_one(MetricCard)
        value_widget = card.query_one(".metric-value")
        label_widget = card.query_one(".metric-label")
        # Use render() for Static content inspection
        assert "42" in str(value_widget.render())
        assert "Found" in str(label_widget.render())


@pytest.mark.asyncio
async def test_metric_card_update_value():
    """MetricCard.update_value should change displayed value."""
    app = MetricCardTestApp()
    async with app.run_test() as pilot:
        card = app.query_one(MetricCard)
        card.update_value("99")
        await pilot.pause()
        value_widget = card.query_one(".metric-value")
        assert "99" in str(value_widget.render())


@pytest.mark.asyncio
async def test_metrics_row_renders_five_cards():
    """MetricsRow should contain 5 metric cards."""
    state = MagicMock()
    state.get_recent_jobs.return_value = []
    state.sparkline_data = []

    app = MetricsRowTestApp(state)
    async with app.run_test() as pilot:
        cards = app.query(MetricCard)
        assert len(cards) == 5
