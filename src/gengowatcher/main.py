import logging
import threading
import sys
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler
import collections
import datetime
import argparse

from rich.console import Console
from rich.text import Text
from rich.theme import Theme

from .browser_session import (
    DEFAULT_BROWSER_DEBUG_URL,
    fetch_browser_session_snapshot_sync,
)
from .config import AppConfig
from .prom_metrics import start_watcher_metrics_server
from .state import AppState
from .stats import StatsManager
from .watcher import GengoWatcher
from .ui_textual import GengoWatcherApp

DEBUG_CATEGORIES = [
    "websocket",
    "rss",
    "job",
    "captcha",
    "browser",
    "config",
    "system",
    "email",
    "website",
    "raw",
]

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

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
        self.log_queue.append(Text.from_markup(message, style=style))


def _should_enable_stdio_logging(
    args: argparse.Namespace, config: AppConfig, *, tui_enabled: bool
) -> bool:
    """Decide whether raw stderr logging should remain active."""
    if getattr(args, "stdio_logs", False):
        return True
    if tui_enabled:
        return False
    return bool(config.getboolean("Logging", "log_stdio_enabled", fallback=False))


def _start_metrics_server_if_enabled(config: AppConfig, watcher: GengoWatcher, logger):
    if not config.getboolean("Metrics", "enabled", fallback=False):
        return None

    host = str(config.get("Metrics", "host", fallback="127.0.0.1") or "127.0.0.1")
    port = config.getint("Metrics", "port", fallback=9091)
    return start_watcher_metrics_server(
        host=host,
        port=port,
        watcher=watcher,
        logger=logger,
    )


def handle_cli_config_commands(args, config: AppConfig, console: Console) -> bool:
    """Handle CLI config commands using AppConfig directly.

    Returns True if a command was handled (and we should exit), False otherwise.
    """
    if args.set:
        section, option, value = args.set
        import re

        if value.lower() in ("true", "false"):
            value = value.lower() == "true"
        elif re.match(r"^[+-]?\d+$", value):
            value = int(value)
        elif re.match(r"^[+-]?(?:\d+\.\d*|\d*\.\d+)$", value):
            value = float(value)
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
        # Interactive configuration - needs special handling
        _interactive_configure(config, console)
        return True

    if args.sync_session_from_browser or args.check_session_from_browser:
        debug_url = (
            args.browser_debug_url
            or config.get("WebSocket", "browser_debug_url")
            or DEFAULT_BROWSER_DEBUG_URL
        )
        snapshot = fetch_browser_session_snapshot_sync(debug_url=debug_url)
        token = snapshot.session_token
        current = config.get("WebSocket", "user_session")
        current_user_key = config.get("WebSocket", "user_key")

        def _mask(value):
            text = str(value or "")
            if len(text) <= 8:
                return text
            return f"{text[:4]}...{text[-4:]}"

        if args.check_session_from_browser:
            key_matches = (
                str(current_user_key or "").strip()
                == str(snapshot.user_key or "").strip()
            )
            if current == token and key_matches:
                print(
                    f"Browser session data matches [WebSocket] credentials at {debug_url}"
                )
            else:
                print(
                    "Browser session data differs from [WebSocket] credentials: "
                    f"user_session config={_mask(current)} browser={_mask(token)}; "
                    f"user_key config={_mask(current_user_key)} browser={_mask(snapshot.user_key)}"
                )
            return True

        config.set("WebSocket", "user_session", token)
        if str(snapshot.user_key or "").strip():
            config.set("WebSocket", "user_key", snapshot.user_key)
        if str(snapshot.user_agent or "").strip():
            config.set("Network", "browser_user_agent", snapshot.user_agent)
        if str(snapshot.accept_language or "").strip():
            config.set("Network", "browser_accept_language", snapshot.accept_language)
        config.set("WebSocket", "browser_debug_url", debug_url)
        config.save_config()
        print(f"Updated [WebSocket] browser session from browser at {debug_url}")
        return True

    return False


def _interactive_configure(config: AppConfig, console: Console):
    """Interactively prompt for missing/placeholder config values."""
    from .config import PLACEHOLDER_CONFIG_VALUES

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
            # Mask sensitive values
            masked = str(current)[:4] + "..." if len(str(current)) > 8 else str(current)
            prompt_text = f"[label]{description}[/] [{masked}]: "

        console.print(prompt_text, end="")
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


def main():
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
        "--sync-session-from-browser",
        action="store_true",
        help="Read my_gengo_session from a live browser via CDP and save it to config.toml",
    )
    parser.add_argument(
        "--check-session-from-browser",
        action="store_true",
        help="Compare config.toml session token against a live browser session via CDP",
    )
    parser.add_argument(
        "--browser-debug-url",
        help="Browser remote debugging base URL (default: [WebSocket] browser_debug_url or http://127.0.0.1:9222)",
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
    args, unknown = parser.parse_known_args()

    console = Console(theme=APP_THEME)

    # =========================================================================
    # LIGHTWEIGHT CONFIG COMMANDS - No GengoWatcher initialization required
    # =========================================================================
    # Handle config commands BEFORE initializing the heavy GengoWatcher instance.
    # This allows CLI config operations to work even if another watcher is running.

    if (
        args.set
        or args.get
        or args.list
        or args.configure
        or args.sync_session_from_browser
        or args.check_session_from_browser
    ):
        try:
            config = AppConfig()
            if handle_cli_config_commands(args, config, console):
                sys.exit(0)
        except Exception as e:
            console.print(f"[error]Configuration error: {e}[/]")
            sys.exit(1)

    # =========================================================================
    # FULL WATCHER INITIALIZATION - Only for running the main application
    # =========================================================================

    log = logging.getLogger("gengowatcher")
    log.setLevel(logging.DEBUG)
    log.propagate = False
    ui_handler = UILoggingHandler()
    log.addHandler(ui_handler)

    try:
        config = AppConfig()
        category_filter = CategoryFilter(config)
        log.addFilter(category_filter)
        ui_handler.addFilter(category_filter)
        if config.get("Logging", "log_main_enabled"):
            try:
                log_file = Path(
                    str(config.get("Paths", "log_file") or "logs/gengowatcher.log")
                )
                log_file.parent.mkdir(parents=True, exist_ok=True)
                # Validate log_max_bytes to prevent handler crash
                log_max_bytes = config.get("Logging", "log_max_bytes") or 0
                if log_max_bytes < 1024:  # Minimum 1KB
                    log_max_bytes = 10485760  # Default 10MB
                file_handler = RotatingFileHandler(
                    log_file,
                    maxBytes=log_max_bytes,
                    backupCount=config.get("Logging", "log_backup_count") or 5,
                )
                file_handler.setFormatter(
                    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
                )
                log.addHandler(file_handler)
            except IOError as e:
                console.print(f"[error]Could not set up file logging: {e}[/]")
        if _should_enable_stdio_logging(
            args,
            config,
            tui_enabled=not args.web_only,
        ):
            stdio_handler = logging.StreamHandler(stream=sys.stderr)
            stdio_handler.setFormatter(
                logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            )
            stdio_handler.addFilter(category_filter)
            log.addHandler(stdio_handler)
        state = AppState(logger=log)
        watcher = GengoWatcher(config=config, state=state, logger=log)
    except Exception as e:
        if log.handlers:
            log.critical(f"A critical error occurred during initialization: {e}")
        else:
            console.print(
                f"[error]A critical error occurred during initialization: {e}[/]"
            )
        sys.exit(1)

    if args.setup_email:
        try:
            from .oauth_setup import run_setup_sync

            success = run_setup_sync(config)
            sys.exit(0 if success else 1)
        except ImportError as e:
            console.print(f"[error]OAuth setup dependencies missing: {e}[/]")
            console.print("[info]Install with: pip install google-auth-oauthlib[/]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[error]Email setup error: {e}[/]")
            sys.exit(1)

    if args.setup_website:
        try:
            from .website_setup import setup_website_interactive

            success = setup_website_interactive(config)
            sys.exit(0 if success else 1)
        except ImportError as e:
            console.print(f"[error]Website setup dependencies missing: {e}[/]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[error]Website setup error: {e}[/]")
            sys.exit(1)

    if not watcher.is_config_complete():
        print("\n⚠️  Configuration is incomplete or contains placeholder values.")
        print(
            "The following settings need to be configured for GengoWatcher to work properly:"
        )
        watcher.prompt_for_config_values()

    metrics_server = _start_metrics_server_if_enabled(config, watcher, log)

    # Start web server if requested
    web_thread = None
    if args.web or args.web_only:
        try:
            from .web import run_web_server

            def start_web_server():
                print(f"Starting web server on http://127.0.0.1:{args.web_port}")
                run_web_server(host="127.0.0.1", port=args.web_port)

            web_thread = threading.Thread(
                target=start_web_server, daemon=True, name="WebServerThread"
            )
            web_thread.start()

            # Give web server time to start
            import time

            time.sleep(1)

        except ImportError as e:
            console.print(f"[error]Could not start web server: {e}[/]")
            console.print("[error]Make sure fastapi and uvicorn are installed[/]")
            if args.web_only:
                sys.exit(1)

    # Exit if only web server was requested
    if args.web_only:
        try:
            if web_thread is not None:
                web_thread.join()
        except KeyboardInterrupt:
            console.print("[info]Web server shutting down...[/]")
        sys.exit(0)

    # Start the Textual TUI
    stats_manager = StatsManager()
    app = GengoWatcherApp(
        watcher=watcher,
        config=config,
        state=state,
        stats=stats_manager,
    )

    watcher_thread = threading.Thread(
        target=watcher.run, daemon=True, name="WatcherThread"
    )
    watcher_thread.start()

    try:
        app.run()
    except Exception as e:
        log.exception("UI loop crashed")
    finally:
        try:
            stats_manager.end_session()
        except Exception:
            log.exception("Failed to persist session stats on shutdown")
        if metrics_server is not None:
            server, thread = metrics_server
            try:
                server.shutdown()
                thread.join(timeout=2)
            except Exception:
                log.exception("Failed to shut down Prometheus metrics server")
        if not watcher.shutdown_event.is_set():
            watcher.handle_exit()

    # Print helpful exit message
    print("\n" + "=" * 60)
    print("👋 GengoWatcher has shut down.")
    print("💡 Tip: Run with --configure to change settings later")
    print("   Example: python -m gengowatcher.main --configure")
    print("=" * 60)

    try:
        watcher_thread.join(timeout=2)
        console.print("[info]GengoWatcher has shut down.[/]")
    except KeyboardInterrupt:
        console.print("[info]Shutting down...[/]")


def run():
    """Console-script entrypoint that preserves the repo-root runtime layout."""
    os.chdir(PROJECT_ROOT)
    main()


if __name__ == "__main__":
    main()
