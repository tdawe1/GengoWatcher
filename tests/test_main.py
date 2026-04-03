"""Tests for CLI/runtime logging decisions in main.py."""

from argparse import Namespace
from unittest.mock import MagicMock, patch

from gengowatcher.main import (
    PROJECT_ROOT,
    _should_enable_stdio_logging,
    _start_metrics_server_if_enabled,
    run,
)


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
    with (
        patch("gengowatcher.main.os.chdir") as mock_chdir,
        patch("gengowatcher.main.main") as mock_main,
    ):
        run()

    mock_chdir.assert_called_once_with(PROJECT_ROOT)
    mock_main.assert_called_once_with()


def test_start_metrics_server_if_enabled_starts_server_from_config():
    config = MagicMock()
    config.getboolean.return_value = True
    config.get.side_effect = lambda section, key, fallback=None: {
        ("Metrics", "host"): "127.0.0.1",
    }.get((section, key), fallback)
    config.getint.side_effect = lambda section, key, fallback=None: {
        ("Metrics", "port"): 9091,
    }.get((section, key), fallback)
    watcher = MagicMock()
    logger = MagicMock()

    with patch("gengowatcher.main.start_watcher_metrics_server") as mock_start:
        server_handle = _start_metrics_server_if_enabled(config, watcher, logger)

    mock_start.assert_called_once_with(
        host="127.0.0.1",
        port=9091,
        watcher=watcher,
        logger=logger,
    )
    assert server_handle == mock_start.return_value


def test_start_metrics_server_if_enabled_skips_when_disabled():
    config = MagicMock()
    config.getboolean.return_value = False
    watcher = MagicMock()
    logger = MagicMock()

    with patch("gengowatcher.main.start_watcher_metrics_server") as mock_start:
        server_handle = _start_metrics_server_if_enabled(config, watcher, logger)

    mock_start.assert_not_called()
    assert server_handle is None
