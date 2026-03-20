"""Thin application entrypoint."""

from __future__ import annotations

import sys

from rich.console import Console

from .cli import build_argument_parser, handle_cli_config_commands, should_handle_lightweight_command
from .config import AppConfig
from .logging_setup import APP_THEME
from .runtime import run_application


def main() -> None:
    """Parse CLI args and dispatch to lightweight or full runtime paths."""
    parser = build_argument_parser()
    args, _unknown = parser.parse_known_args()
    console = Console(theme=APP_THEME)

    if should_handle_lightweight_command(args):
        try:
            config = AppConfig()
            if handle_cli_config_commands(args, config, console):
                sys.exit(0)
        except Exception as e:
            console.print(f"[error]Configuration error: {e}[/]")
            sys.exit(1)

    run_application(args, console)


def run():
    """Console-script entrypoint that preserves the repo-root runtime layout."""
    os.chdir(PROJECT_ROOT)
    main()


if __name__ == "__main__":
    main()
