import pytest
import logging
import collections
from unittest.mock import MagicMock

# Correctly import from the gengowatcher package
from gengowatcher import ui
from gengowatcher.watcher import GengoWatcher
from gengowatcher.config import AppConfig
from gengowatcher.state import AppState


@pytest.fixture
def tui_instance():
    """
    Creates an instance of the CommandLineInterface with mocked dependencies.
    """
    # Using MagicMock is better than dummy classes as it adapts to any method calls
    mock_watcher = MagicMock(spec=GengoWatcher)
    mock_watcher.logger = logging.getLogger("test")  # Mock logger needs a real logger

    mock_config = MagicMock(spec=AppConfig)
    mock_state = MagicMock(spec=AppState)
    mock_console = MagicMock()
    log_queue = collections.deque()

    tui = ui.CommandLineInterface(
        mock_watcher, mock_config, mock_state, mock_console, log_queue
    )
    # Return the mocks as well so tests can inspect them
    return tui, mock_watcher


def test_handle_command_known(tui_instance):
    """Tests that a known command calls the correct handler."""
    tui, mock_watcher = tui_instance

    # We can mock the handler directly on the instance for this test
    tui.commands["help"]["handler"] = MagicMock(return_value="help output")
    tui.command_output.clear()

    tui.handle_command("help")

    assert list(tui.command_output) == ["help output"]
    tui.commands["help"]["handler"].assert_called_once()


def test_handle_command_unknown(tui_instance):
    """Tests that an unknown command logs an error."""
    tui, mock_watcher = tui_instance
    tui.command_output.clear()

    # We are only interested in the 'error' method for this test.
    # Let's replace it with a mock *just for this test*.
    mock_watcher.logger.error = MagicMock()

    tui.handle_command("unknowncmd")

    # Now this assertion will work because we are calling it on a MagicMock object
    mock_watcher.logger.error.assert_called_once_with("Unknown command: 'unknowncmd'")
