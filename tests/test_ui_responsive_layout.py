"""Tests for responsive TUI layout decisions."""

from unittest.mock import MagicMock

import pytest

from gengowatcher.ui_textual import GengoWatcherApp

TWO_COL = (
    GengoWatcherApp.DASHBOARD_PANEL_MIN_WIDTH * 2
    + GengoWatcherApp.DASHBOARD_GRID_CHROME_WIDTH
)
FULL_H = GengoWatcherApp.DASHBOARD_CONTENT_FULL_HEIGHT


def _create_app() -> GengoWatcherApp:
    return GengoWatcherApp(
        config=MagicMock(),
        state=MagicMock(),
        watcher=MagicMock(),
        stats=MagicMock(),
    )


@pytest.mark.parametrize(
    ("width", "height", "expected_stacked", "expected_compact"),
    [
        (TWO_COL, FULL_H, True, False),
        (TWO_COL + 1, FULL_H, False, False),
        (TWO_COL, FULL_H - 1, True, True),
        (TWO_COL + 1, FULL_H - 1, True, True),
    ],
)
def test_apply_responsive_layout_boundaries(
    width: int,
    height: int,
    expected_stacked: bool,
    expected_compact: bool,
) -> None:
    app = _create_app()

    app._apply_responsive_layout(width=width, height=height)

    assert ("dashboard-stacked" in app.classes) is expected_stacked
    assert ("dashboard-compact" in app.classes) is expected_compact
