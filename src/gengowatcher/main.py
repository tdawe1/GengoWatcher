"""Thin application entrypoint."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from rich.console import Console
from rich.text import Text
from rich.theme import Theme

from .browser_session import (
    fetch_browser_session_snapshot_sync,
    fetch_browser_session_token_sync,
)
from .cli import (
    build_argument_parser,
    handle_cli_config_commands,
    should_handle_lightweight_command,
)
from .config import AppConfig
from .logging_setup import APP_THEME
from .logging_setup import should_enable_stdio_logging as _should_enable_stdio_logging
from .runtime import run_application


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    """Parse CLI args and dispatch to lightweight or full runtime paths."""
    parser = build_argument_parser()
    args = parser.parse_args()
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

    run_application(args, console)

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
        if args.stdio_logs or config.getboolean(
            "Logging", "log_stdio_enabled", fallback=False
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


if __name__ == "__main__":
    main()
