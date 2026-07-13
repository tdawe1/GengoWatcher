"""Tests for MetricCard and MetricsRow widgets."""

import pytest
from unittest.mock import MagicMock
from textual.app import App, ComposeResult

from gengowatcher.ui_textual import MetricCard, MetricsRow, Icons


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
    """MetricCard should display only the stat value in card content."""
    app = MetricCardTestApp()
    async with app.run_test() as pilot:  # noqa: F841
        card = app.query_one(MetricCard)
        value_widget = card.query_one(".metric-value")
        # Use render() for Static content inspection
        assert "42" in str(value_widget.render())
        assert len(list(card.query(".metric-label"))) == 0


@pytest.mark.asyncio
async def test_metric_card_update_value():
    """MetricCard.update_value should change displayed value."""
    app = MetricCardTestApp()
    async with app.run_test() as pilot:  # noqa: F841
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
    async with app.run_test() as pilot:  # noqa: F841
        cards = app.query(MetricCard)
        assert len(cards) == 5


@pytest.mark.asyncio
async def test_metrics_row_card_titles_include_icons():
    """MetricsRow cards should show icon-prefixed border titles."""
    state = MagicMock()
    state.get_recent_jobs.return_value = []
    state.sparkline_data = []

    app = MetricsRowTestApp(state)
    async with app.run_test() as pilot:  # noqa: F841
        found = app.query_one("#card-found", MetricCard)
        accepted = app.query_one("#card-accepted", MetricCard)
        value = app.query_one("#card-value", MetricCard)
        rate = app.query_one("#card-rate", MetricCard)
        today = app.query_one("#card-today", MetricCard)

        assert found.border_title == f"{Icons.FOUND} Found"
        assert accepted.border_title == f"{Icons.ACCEPTED} Accepted"
        assert value.border_title == f"{Icons.VALUE} Value"
        assert rate.border_title == f"{Icons.RATE} Rate"
        assert today.border_title == f"{Icons.TODAY} Today"
