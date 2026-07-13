"""Thin application entrypoint."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from rich.console import Console

from .cli import (
    build_argument_parser,
    handle_cli_config_commands,
    should_handle_lightweight_command,
)
# Re-export browser session helpers so callers (and tests) can ``patch(
# "gengowatcher.main.fetch_browser_session_snapshot_sync")`` etc.
from .browser_session import (  # noqa: F401  -- re-exported for back-compat (test patches)
    fetch_browser_session_snapshot_sync,
    fetch_browser_session_token_sync,
)
from .config import AppConfig
from .logging_setup import APP_THEME
from .prom_metrics import start_watcher_metrics_server
from .runtime import run_application


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _start_metrics_server_if_enabled(config: AppConfig, watcher, logger):
    if not config.getboolean("Metrics", "enabled", fallback=False):
        return None

    host = str(config.get("Metrics", "host", fallback="127.0.0.1") or "127.0.0.1")
    port = int(config.getint("Metrics", "port", fallback=9091) or 9091)
    return start_watcher_metrics_server(
        host=host,
        port=port,
        watcher=watcher,
        logger=logger,
    )


def main() -> None:
    """Parse CLI args and dispatch to lightweight or full runtime paths."""
    parser = build_argument_parser()
    args = parser.parse_args()
    console = Console(theme=APP_THEME)

    if should_handle_lightweight_command(args):
        try:
            config = AppConfig()
            if handle_cli_config_commands(args, config, console):
                sys.exit(0)
        except Exception as exc:
            console.print(f"[error]Configuration error: {exc}[/]")
            sys.exit(1)

    run_application(args, console)


def run() -> None:
    """Change to the project root before running the app."""
    os.chdir(PROJECT_ROOT)
    main()


if __name__ == "__main__":
    main()
