"""CLI argument parsing and lightweight config command handling."""

from __future__ import annotations

import argparse
import re
from getpass import getpass

from rich.console import Console

from .config import AppConfig, PLACEHOLDER_CONFIG_VALUES


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser for the application."""
    parser = argparse.ArgumentParser(description="GengoWatcher CLI")
    parser.add_argument(
        "--set",
        nargs=3,
        metavar=("SECTION", "OPTION", "VALUE"),
        help="Set a config value",
    )
    parser.add_argument(
        "--get", nargs=2, metavar=("SECTION", "OPTION"), help="Get a config value"
    )
    parser.add_argument("--list", action="store_true", help="List all config values")
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Interactively configure missing/required values",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start web UI server alongside TUI",
    )
    parser.add_argument(
        "--web-only",
        action="store_true",
        help="Start only the web UI server (no TUI)",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=8000,
        help="Port for web server (default: 8000)",
    )
    parser.add_argument(
        "--setup-email",
        action="store_true",
        help="Configure Gmail OAuth for email monitoring (interactive)",
    )
    parser.add_argument(
        "--setup-website",
        action="store_true",
        help="Configure WebsiteMonitor for browser-based job scraping (interactive)",
    )
    parser.add_argument(
        "--stdio-logs",
        action="store_true",
        help="Also write watcher logs to stderr in addition to file/UI handlers",
    )
    return parser


def should_handle_lightweight_command(args: argparse.Namespace) -> bool:
    """Return whether args request a config-only command path."""
    return bool(
        args.set
        or args.get
        or args.list
        or args.configure
    )


def _coerce_cli_value(value: str):
    """Convert simple CLI strings into bool/int/float where appropriate."""
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if re.match(r"^[+-]?\d+$", value):
        return int(value)
    if re.match(r"^[+-]?(?:\d+\.\d*|\d*\.\d+)$", value):
        return float(value)
    return value


def handle_cli_config_commands(
    args: argparse.Namespace, config: AppConfig, console: Console
) -> bool:
    """Handle CLI config commands using AppConfig directly."""
    if args.set:
        section, option, raw_value = args.set
        value = _coerce_cli_value(raw_value)
        config.set(section, option, value)
        config.save_config()
        print(f"Set [{section}] {option} = {value}")
        return True

    if args.get:
        section, option = args.get
        value = config.get(section, option)
        print(f"[{section}] {option} = {value}")
        return True

    if args.list:
        all_values = config.list_all()
        for section, options in all_values.items():
            print(f"[{section}]")
            for option, value in options.items():
                print(f"  {option} = {value}")
        return True

    if args.configure:
        interactive_configure(config, console)
        return True

    return False


def interactive_configure(config: AppConfig, console: Console) -> None:
    """Interactively prompt for missing/placeholder config values."""
    console.print("[title]GengoWatcher Configuration[/]")
    console.print(
        "Enter values for the following settings (or press Enter to keep current):\n"
    )

    required_fields = [
        ("WebSocket", "user_id", "Your Gengo user ID", True),
        ("WebSocket", "user_key", "Your Gengo API key", False),
        ("WebSocket", "user_session", "Your session token from browser cookies", True),
    ]

    for section, option, description, required in required_fields:
        current = config.get(section, option)
        is_placeholder = current in PLACEHOLDER_CONFIG_VALUES

        if is_placeholder:
            label = "required" if required else "optional"
            prompt_text = f"[label]{description}[/] [warning]({label})[/]: "
        else:
            masked = str(current)[:4] + "..." if len(str(current)) > 8 else str(current)
            prompt_text = f"[label]{description}[/] [{masked}]: "

        console.print(prompt_text, end="")
        if option in {"user_key", "user_session"}:
            new_value = getpass("").strip()
        else:
            new_value = input().strip()
        if new_value:
            config.set(section, option, new_value)
            console.print("  [success]✓ Updated[/]")
        elif is_placeholder:
            console.print("  [warning]⚠ Keeping placeholder value[/]")
        else:
            console.print("  [info]Kept existing value[/]")

    config.save_config()
    console.print("\n[success]Configuration saved![/]")
