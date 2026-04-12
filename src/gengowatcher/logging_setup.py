"""Logging and console theme setup for the application entrypoint."""

from __future__ import annotations

import argparse
import collections
import datetime
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.text import Text
from rich.theme import Theme

from .config import AppConfig

CATEGORY_KEYWORDS = {
    "websocket": ["websocket", "ws ", "pong", "ping", "heartbeat", "wss://"],
    "rss": ["rss", "feed", "entries", "fetching", "parsing"],
    "job": ["job", "acceptance", "accept", "reward", "translation", "cancellation"],
    "captcha": ["captcha", "recaptcha", "2captcha", "anti-captcha", "solver"],
    "browser": ["browser", "playwright", "selenium", "page", "click", "navigation"],
    "config": ["config", "setting", "reload", "configuration"],
    "system": [
        "starting",
        "stopping",
        "shutdown",
        "initialized",
        "error",
        "critical",
        "exception",
    ],
    "email": ["email", "imap", "gmail", "oauth", "inbox", "mail"],
    "website": ["website", "scrape", "viewport", "mouse", "scroll", "stealth"],
}

APP_THEME = Theme(
    {
        "info": "cyan",
        "success": "bold green",
        "warning": "yellow",
        "error": "bold red",
        "title": "bold magenta",
        "header": "bold bright_white",
        "label": "cyan",
        "value": "white",
        "path": "italic yellow",
        "panel_border": "bright_blue",
        "table_header": "bold magenta",
        "prompt": "bold white",
        "input": "white",
    }
)


class CategoryFilter(logging.Filter):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config

    def filter(self, record: logging.LogRecord) -> bool:
        formatted_msg = record.getMessage()
        sanitized_msg = formatted_msg.replace("\r", "\\r").replace("\n", "\\n")
        record.msg = sanitized_msg
        record.args = ()

        if record.levelno >= logging.WARNING:
            return True

        msg_lower = sanitized_msg.lower()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in msg_lower for kw in keywords):
                return bool(self.config.get("DebugCategories", category))

        return bool(self.config.get("DebugCategories", "system"))


class UILoggingHandler(logging.Handler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_queue = collections.deque(maxlen=100)

    def emit(self, record):
        level_style_map = {
            logging.INFO: "cyan",
            logging.WARNING: "yellow",
            logging.ERROR: "bold red",
            logging.CRITICAL: "bold white on red",
        }
        style = level_style_map.get(record.levelno, "white")
        message = (
            f"{datetime.datetime.fromtimestamp(record.created).strftime('%H:%M:%S')} - "
            f"{record.getMessage()}"
        )
        self.log_queue.append(Text(message, style=style))


def should_enable_stdio_logging(
    args: argparse.Namespace, config: AppConfig, *, tui_enabled: bool
) -> bool:
    """Decide whether raw stderr logging should remain active."""
    if getattr(args, "stdio_logs", False):
        return True
    if tui_enabled:
        return False
    return bool(config.getboolean("Logging", "log_stdio_enabled", fallback=False))


def create_logger() -> tuple[logging.Logger, UILoggingHandler]:
    """Create the base application logger and UI log handler."""
    log = logging.getLogger("gengowatcher")
    log.setLevel(logging.DEBUG)
    ui_handler = UILoggingHandler()
    log.addHandler(ui_handler)
    return log, ui_handler


def configure_logger(
    log: logging.Logger,
    ui_handler: UILoggingHandler,
    args: argparse.Namespace,
    config: AppConfig,
    *,
    tui_enabled: bool,
) -> None:
    """Finish logger configuration after config has been loaded."""
    category_filter = CategoryFilter(config)
    log.addFilter(category_filter)
    ui_handler.addFilter(category_filter)

    if config.getboolean("Logging", "log_main_enabled"):
        _attach_file_handler(log, config)

    if should_enable_stdio_logging(args, config, tui_enabled=tui_enabled):
        stdio_handler = logging.StreamHandler(stream=sys.stderr)
        stdio_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        stdio_handler.addFilter(category_filter)
        log.addHandler(stdio_handler)


def _attach_file_handler(log: logging.Logger, config: AppConfig) -> None:
    log_file = Path(str(config.get("Paths", "log_file") or "logs/gengowatcher.log"))
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Coerce log_max_bytes to int with safe fallback
    try:
        log_max_bytes = int(config.get("Logging", "log_max_bytes") or 0)
    except (TypeError, ValueError):
        log_max_bytes = 0
    if log_max_bytes < 1024:
        log_max_bytes = 10485760

    # Coerce log_backup_count to int with safe fallback
    try:
        log_backup_count = int(config.get("Logging", "log_backup_count") or 5)
    except (TypeError, ValueError):
        log_backup_count = 5

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=log_max_bytes,
        backupCount=log_backup_count,
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    log.addHandler(file_handler)