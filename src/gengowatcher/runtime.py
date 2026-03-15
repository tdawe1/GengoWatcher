"""Runtime bootstrap and application lifecycle management."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time

from rich.console import Console

from .config import AppConfig
from .logging_setup import configure_logger, create_logger
from .state import AppState
from .stats import StatsManager
from .ui_textual import GengoWatcherApp
from .watcher import GengoWatcher


def run_application(args: argparse.Namespace, console: Console) -> None:
    """Run the main watcher/TUI application lifecycle."""
    log, ui_handler = create_logger()

    try:
        config = AppConfig()
        configure_logger(log, ui_handler, args, config, tui_enabled=not args.web_only)
    except Exception as e:
        if log.handlers:
            log.critical(f"A critical error occurred during initialization: {e}")
        console.print(
            f"[error]A critical error occurred during initialization: {e}[/]"
        )
        sys.exit(1)

    _handle_setup_commands(args, config, console)

    try:
        state = AppState(logger=log)
        watcher = GengoWatcher(config=config, state=state, logger=log)
    except Exception as e:
        if log.handlers:
            log.critical(f"A critical error occurred during initialization: {e}")
        console.print(
            f"[error]A critical error occurred during initialization: {e}[/]"
        )
        sys.exit(1)

    if not watcher.is_config_complete():
        print("\n⚠️  Configuration is incomplete or contains placeholder values.")
        print(
            "The following settings need to be configured for GengoWatcher to work properly:"
        )
        watcher.prompt_for_config_values()

    web_thread = _start_web_server_if_requested(args, console)
    if args.web_only:
        _run_web_only(console, web_thread)

    _run_tui(args, console, log, config, state, watcher)


def _handle_setup_commands(
    args: argparse.Namespace, config: AppConfig, console: Console
) -> None:
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


def _start_web_server_if_requested(
    args: argparse.Namespace, console: Console
) -> threading.Thread | None:
    if not (args.web or args.web_only):
        return None

    try:
        from .web import run_web_server

        def start_web_server():
            print(f"Starting web server on http://127.0.0.1:{args.web_port}")
            run_web_server(host="127.0.0.1", port=args.web_port)

        web_thread = threading.Thread(
            target=start_web_server, daemon=True, name="WebServerThread"
        )
        web_thread.start()
        time.sleep(1)
        return web_thread
    except ImportError as e:
        console.print(f"[error]Could not start web server: {e}[/]")
        console.print("[error]Make sure fastapi and uvicorn are installed[/]")
        if args.web_only:
            sys.exit(1)
        return None


def _run_web_only(console: Console, web_thread: threading.Thread | None) -> None:
    try:
        if web_thread is not None:
            web_thread.join()
    except KeyboardInterrupt:
        console.print("[info]Web server shutting down...[/]")
    sys.exit(0)


def _run_tui(
    args: argparse.Namespace,
    console: Console,
    log: logging.Logger,
    config: AppConfig,
    state: AppState,
    watcher: GengoWatcher,
) -> None:
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
    except Exception:
        log.exception("UI loop crashed")
    finally:
        try:
            stats_manager.end_session()
        except Exception:
            log.exception("Failed to persist session stats on shutdown")
        if not watcher.shutdown_event.is_set():
            watcher.handle_exit()

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