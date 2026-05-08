"""Tests for responsive TUI layout decisions."""

from unittest.mock import MagicMock

from gengowatcher.ui_textual import GengoWatcherApp


def _create_app() -> GengoWatcherApp:
    return GengoWatcherApp(
        config=MagicMock(),
        state=MagicMock(),
        watcher=MagicMock(),
        stats=MagicMock(),
    )


def test_dashboard_stacks_when_terminal_is_narrow() -> None:
    app = _create_app()

    app._apply_responsive_layout(width=80, height=45)

    assert "dashboard-stacked" in app.classes
    assert "dashboard-compact" not in app.classes


def test_dashboard_stacks_and_compacts_when_content_area_is_short() -> None:
    app = _create_app()

    app._apply_responsive_layout(width=190, height=17)

    assert "dashboard-stacked" in app.classes
    assert "dashboard-compact" in app.classes


def test_dashboard_uses_grid_when_content_area_has_room() -> None:
    app = _create_app()

    app._apply_responsive_layout(width=190, height=25)

    assert "dashboard-stacked" not in app.classes
    assert "dashboard-compact" not in app.classes
