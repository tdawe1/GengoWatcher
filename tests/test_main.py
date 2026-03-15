"""Tests for CLI/runtime logging decisions in main.py."""

from argparse import Namespace
from unittest.mock import MagicMock, patch

from gengowatcher.main import PROJECT_ROOT, _should_enable_stdio_logging, run


def test_should_enable_stdio_logging_disables_configured_stdio_in_tui_mode():
    config = MagicMock()
    config.getboolean.return_value = True
    args = Namespace(stdio_logs=False)

    assert _should_enable_stdio_logging(args, config, tui_enabled=True) is False


def test_should_enable_stdio_logging_honors_explicit_cli_override():
    config = MagicMock()
    config.getboolean.return_value = False
    args = Namespace(stdio_logs=True)

    assert _should_enable_stdio_logging(args, config, tui_enabled=True) is True


def test_should_enable_stdio_logging_uses_config_when_no_tui_is_active():
    config = MagicMock()
    config.getboolean.return_value = True
    args = Namespace(stdio_logs=False)

    assert _should_enable_stdio_logging(args, config, tui_enabled=False) is True


def test_run_changes_to_project_root_before_calling_main():
    with patch("gengowatcher.main.os.chdir") as mock_chdir, patch(
        "gengowatcher.main.main"
    ) as mock_main:
        run()

    mock_chdir.assert_called_once_with(PROJECT_ROOT)
    mock_main.assert_called_once_with()
