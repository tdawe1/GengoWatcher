"""Tests for CLI/runtime logging decisions in main.py."""

from argparse import Namespace
from unittest.mock import MagicMock

from gengowatcher.main import _should_enable_stdio_logging


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
