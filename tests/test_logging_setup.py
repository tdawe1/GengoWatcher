from __future__ import annotations

from argparse import Namespace
import logging
from unittest.mock import MagicMock

from gengowatcher.logging_setup import UILoggingHandler, configure_logger


def _config(*, stdio: bool) -> MagicMock:
    config = MagicMock()
    config.getboolean.side_effect = lambda section, option, fallback=False: {
        ("Logging", "log_main_enabled"): False,
        ("Logging", "log_stdio_enabled"): stdio,
    }.get((section, option), fallback)
    config.get.return_value = True
    return config


def _logger(name: str) -> tuple[logging.Logger, UILoggingHandler]:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.filters.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    ui_handler = UILoggingHandler()
    logger.addHandler(ui_handler)
    return logger, ui_handler


def test_tui_logging_never_writes_to_stderr(capsys):
    logger, ui_handler = _logger("test.tui.logging")
    configure_logger(
        logger,
        ui_handler,
        Namespace(stdio_logs=True),
        _config(stdio=True),
        tui_enabled=True,
    )

    logger.warning("kept in the UI queue")

    assert capsys.readouterr().err == ""
    assert len(ui_handler.log_queue) == 1
    assert not any(
        isinstance(handler, logging.StreamHandler) and handler is not ui_handler
        for handler in logger.handlers
    )


def test_web_only_logging_honors_explicit_stderr(capsys):
    logger, ui_handler = _logger("test.web.logging")
    configure_logger(
        logger,
        ui_handler,
        Namespace(stdio_logs=True),
        _config(stdio=False),
        tui_enabled=False,
    )

    logger.warning("visible in web-only mode")

    assert "visible in web-only mode" in capsys.readouterr().err
