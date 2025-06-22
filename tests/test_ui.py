import pytest
import logging
import collections
from unittest.mock import MagicMock

from gengowatcher import ui
from gengowatcher.watcher import GengoWatcher
from gengowatcher.config import AppConfig
from gengowatcher.state import AppState


@pytest.fixture
def tui_instance():
    """
    Creates an instance of the CommandLineInterface with mocked dependencies.
    """
    mock_watcher = MagicMock(spec=GengoWatcher)
    mock_watcher.logger = logging.getLogger("test")

    mock_config = MagicMock(spec=AppConfig)
    mock_state = MagicMock(spec=AppState)
    mock_console = MagicMock()
    log_queue = collections.deque()

    tui = ui.CommandLineInterface(
        mock_watcher, mock_config, mock_state, mock_console, log_queue
    )
    return tui, mock_watcher


def test_handle_command_known(tui_instance):
    """Tests that a known command calls the correct handler."""
    tui, mock_watcher = tui_instance

    tui.commands["help"]["handler"] = MagicMock(return_value="help output")
    tui.command_output.clear()

    tui.handle_command("help")

    assert list(tui.command_output) == ["help output"]
    tui.commands["help"]["handler"].assert_called_once()


def test_handle_command_unknown(tui_instance):
    """Tests that an unknown command logs an error."""
    tui, mock_watcher = tui_instance
    tui.command_output.clear()

    mock_watcher.logger.error = MagicMock()

    tui.handle_command("unknowncmd")

    mock_watcher.logger.error.assert_called_once_with("Unknown command: 'unknowncmd'")


def test_handle_command_toggle_websocket(tui_instance):
    """Tests that the togglewebsocket command calls the correct config methods."""
    tui, mock_watcher = tui_instance
    mock_watcher.logger = MagicMock()

    mock_config = tui.config
    mock_config.get.return_value = True
    tui.handle_command("togglewebsocket")

    mock_config.set.assert_called_once_with("WebSocket", "enable_websocket", False)
    mock_config.save_config.assert_called_once()
    mock_watcher.logger.info.assert_called_with(
        "WebSocket monitoring has been disabled."
    )
    mock_watcher.logger.warning.assert_called_with(
        "A restart is required for this change to take effect."
    )
