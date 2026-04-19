"""CLI argument parsing and lightweight config command handling."""

from __future__ import annotations

import argparse
import re
import time
from getpass import getpass

from rich.console import Console

from .browser_debug_launcher import (
    DEFAULT_FIREFOX_DEBUG_URL,
    get_firefox_debug_launch_spec,
    get_firefox_debug_retry_window,
    launch_managed_firefox_debug,
    maybe_launch_managed_firefox_debug,
)
from .browser_session import BrowserSessionSnapshot
from .config import AppConfig, PLACEHOLDER_CONFIG_VALUES

FALLBACK_BROWSER_USER_KEY = "browser-user-key"
FALLBACK_BROWSER_USER_AGENT = "Helium Browser"
FALLBACK_BROWSER_ACCEPT_LANGUAGE = "en-GB,en-US;q=0.9"


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
        "--config",
        dest="configure",
        action="store_true",
        help=argparse.SUPPRESS,
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
        "--sync-session-from-browser",
        action="store_true",
        help="Sync WebSocket session values from the live browser session",
    )
    parser.add_argument(
        "--sync-session",
        dest="sync_session_from_browser",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--check-session-from-browser",
        action="store_true",
        help="Compare configured WebSocket session values with the live browser session",
    )
    parser.add_argument(
        "--check-session",
        dest="check_session_from_browser",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--start-firefox-debug",
        action="store_true",
        help="Start a managed Firefox DevTools session for browser sync",
    )
    parser.add_argument(
        "--setup-email",
        action="store_true",
        help="Configure Gmail OAuth for email monitoring (interactive)",
    )
    parser.add_argument(
        "--setup-mail",
        dest="setup_email",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--setup-website",
        action="store_true",
        help="Configure WebsiteMonitor for browser-based job scraping (interactive)",
    )
    parser.add_argument(
        "--setup-web",
        dest="setup_website",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--setup-site",
        dest="setup_website",
        action="store_true",
        help=argparse.SUPPRESS,
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
        getattr(args, "set", None)
        or getattr(args, "get", None)
        or getattr(args, "list", False)
        or getattr(args, "configure", False)
        or getattr(args, "sync_session_from_browser", False)
        or getattr(args, "check_session_from_browser", False)
        or getattr(args, "start_firefox_debug", False)
    )


def _resolve_browser_debug_url(args: argparse.Namespace, config: AppConfig) -> str:
    browser_debug_url = getattr(args, "browser_debug_url", "") or ""
    if browser_debug_url:
        return browser_debug_url
    configured_debug_url = config.get("WebSocket", "browser_debug_url")
    return str(configured_debug_url or "")


def _load_browser_session_snapshot(
    args: argparse.Namespace, config: AppConfig
) -> BrowserSessionSnapshot:
    from . import main as main_module

    debug_url = _resolve_browser_debug_url(args, config)
    try:
        return main_module.fetch_browser_session_snapshot_sync(debug_url=debug_url)
    except Exception:
        if maybe_launch_managed_firefox_debug(config, debug_url):
            timeout_sec, retry_interval_sec = get_firefox_debug_retry_window(config)
            deadline = time.monotonic() + timeout_sec
            last_exc: Exception | None = None
            while time.monotonic() < deadline:
                time.sleep(retry_interval_sec)
                try:
                    return main_module.fetch_browser_session_snapshot_sync(
                        debug_url=debug_url
                    )
                except Exception as exc:  # pragma: no cover - exercised via caller
                    last_exc = exc
            if last_exc is not None:
                raise last_exc
        session_token = main_module.fetch_browser_session_token_sync(
            debug_url=debug_url
        )
        return BrowserSessionSnapshot(
            session_token=session_token,
            user_key=FALLBACK_BROWSER_USER_KEY,
            user_agent=FALLBACK_BROWSER_USER_AGENT,
            accept_language=FALLBACK_BROWSER_ACCEPT_LANGUAGE,
        )


def _start_firefox_debug_session(
    args: argparse.Namespace, config: AppConfig, console: Console
) -> bool:
    configured_debug_url = _resolve_browser_debug_url(args, config)
    spec = get_firefox_debug_launch_spec(
        config,
        configured_debug_url,
        require_enabled=False,
        allow_default_debug_url=True,
    )
    if spec is None:
        raise RuntimeError(
            "Managed Firefox launch requires a local ws:// browser_debug_url, "
            f"for example {DEFAULT_FIREFOX_DEBUG_URL}"
        )

    if not configured_debug_url:
        config.set("WebSocket", "browser_debug_url", spec.debug_url)
        config.save_config()

    launch_managed_firefox_debug(spec)
    print(
        "Started managed Firefox debug session at "
        f"{spec.debug_url} using profile {spec.profile_path}"
    )
    return True


def _sync_session_from_browser(
    args: argparse.Namespace, config: AppConfig, console: Console
) -> bool:
    snapshot = _load_browser_session_snapshot(args, config)
    debug_url = _resolve_browser_debug_url(args, config)
    config.set("WebSocket", "user_session", snapshot.session_token)
    config.set("WebSocket", "user_key", snapshot.user_key)
    config.set("Network", "browser_user_agent", snapshot.user_agent)
    config.set("Network", "browser_accept_language", snapshot.accept_language)
    if debug_url:
        config.set("WebSocket", "browser_debug_url", debug_url)
    config.save_config()
    print("Updated [WebSocket] user_session from live browser state")
    return True


def _check_session_from_browser(
    args: argparse.Namespace, config: AppConfig, console: Console
) -> bool:
    snapshot = _load_browser_session_snapshot(args, config)
    current_session = config.get("WebSocket", "user_session")
    current_user_key = config.get("WebSocket", "user_key")
    current_user_agent = config.get("Network", "browser_user_agent")
    current_accept_language = config.get("Network", "browser_accept_language")

    mismatches = []
    if current_session != snapshot.session_token:
        mismatches.append("user_session")
    if current_user_key != snapshot.user_key:
        mismatches.append("user_key")
    if current_user_agent != snapshot.user_agent:
        mismatches.append("browser_user_agent")
    if current_accept_language != snapshot.accept_language:
        mismatches.append("browser_accept_language")

    if mismatches:
        print(
            "Configured browser session differs from the live browser state: "
            + ", ".join(mismatches)
        )
    else:
        print("Configured browser session matches the live browser state.")
    return True


def _coerce_cli_value(value: str, expected_type=None):
    """Convert CLI strings into appropriate types.

    Args:
        value: The raw string value from CLI input
        expected_type: The expected Python type from the config schema (if known)

    Returns:
        The coerced value matching the expected type where possible
    """
    import json

    # If we know the expected type, use it
    if expected_type is not None:
        # Handle list/sequence types
        if expected_type is list or (
            hasattr(expected_type, "__origin__") and expected_type.__origin__ is list
        ):
            # Try parsing as JSON first
            if value.startswith("[") and value.endswith("]"):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass
            # Fall back to comma-separated
            return [item.strip() for item in value.split(",") if item.strip()]

        # Handle dict/object types
        if expected_type is dict or (
            hasattr(expected_type, "__origin__") and expected_type.__origin__ is dict
        ):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
            return value

        # Handle boolean
        if expected_type is bool:
            return value.lower() in ("true", "1", "yes", "on")

        # Handle int
        if expected_type is int:
            try:
                return int(value)
            except ValueError:
                pass

        # Handle float
        if expected_type is float:
            try:
                return float(value)
            except ValueError:
                pass

    # Fall back to auto-detection if no type hint or coercion failed
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
        # Look up expected type from schema
        expected_type = None
        schema_default = config.DEFAULT_CONFIG.get(section, {}).get(option)
        if schema_default is not None:
            expected_type = type(schema_default)
        value = _coerce_cli_value(raw_value, expected_type)
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
                # Redact sensitive values
                option_lower = option.lower()
                is_sensitive = any(
                    keyword in option_lower
                    for keyword in [
                        "token",
                        "secret",
                        "key",
                        "password",
                        "oauth",
                        "api",
                    ]
                )
                if is_sensitive:
                    display_value = "******"
                else:
                    display_value = value
                print(f"  {option} = {display_value}")
        return True

    if args.configure:
        interactive_configure(config, console)
        return True

    if getattr(args, "sync_session_from_browser", False):
        return _sync_session_from_browser(args, config, console)

    if getattr(args, "check_session_from_browser", False):
        return _check_session_from_browser(args, config, console)

    if getattr(args, "start_firefox_debug", False):
        return _start_firefox_debug_session(args, config, console)

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
