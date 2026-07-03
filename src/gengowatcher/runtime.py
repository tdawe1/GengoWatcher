"""Runtime bootstrap and application lifecycle management."""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import time

from rich.console import Console

from .config import AppConfig
from .logging_setup import configure_logger, create_logger
from .prom_metrics import start_watcher_metrics_server
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
        console.print(f"[error]A critical error occurred during initialization: {e}[/]")
        sys.exit(1)

    _handle_setup_commands(args, config, console)

    try:
        state = AppState(logger=log)
        watcher = GengoWatcher(config=config, state=state, logger=log)
        _start_metrics_server_if_enabled(config, watcher, log)
    except Exception as e:
        if log.handlers:
            log.critical(f"A critical error occurred during initialization: {e}")
        console.print(f"[error]A critical error occurred during initialization: {e}[/]")
        sys.exit(1)

    if not watcher.is_config_complete():
        print("\n⚠️  Configuration is incomplete or contains placeholder values.")
        print(
            "The following settings need to be configured for GengoWatcher to work properly:"
        )
        watcher.prompt_for_config_values()

    web_thread = _start_web_server_if_requested(
        args,
        console,
        config=config,
        state=state,
        logger=log,
        watcher=watcher,
    )
    if args.web_only:
        _run_web_only(console, web_thread)

    _run_tui(
        args, console, log, ui_handler, config, state, watcher, api_thread=web_thread
    )


def _start_metrics_server_if_enabled(
    config: AppConfig,
    watcher: GengoWatcher,
    logger: logging.Logger,
):
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
    args: argparse.Namespace,
    console: Console,
    *,
    config: AppConfig,
    state: AppState,
    logger: logging.Logger,
    watcher: GengoWatcher,
) -> threading.Thread | None:
    cli_requested = bool(
        getattr(args, "web", False) or getattr(args, "web_only", False)
    )
    config_enabled = False
    if not cli_requested:
        config_enabled = config.getboolean("WebServer", "enabled", fallback=False)

    if not (cli_requested or config_enabled):
        return None

    if cli_requested:
        host = "127.0.0.1"
        port = int(getattr(args, "web_port", 8000) or 8000)
    else:
        host = str(config.get("WebServer", "host", fallback="127.0.0.1") or "127.0.0.1")
        port = int(config.getint("WebServer", "port", fallback=8000) or 8000)

    if not _is_tcp_port_available(host, port):
        message = f"Web API not started because http://{host}:{port} is already in use."
        logger.warning(message)
        if args.web_only:
            console.print(f"[warning]{message}[/]")
            sys.exit(1)
        return None

    try:
        from .web import start_web_server_thread

        logger.info("Starting Web API on http://%s:%s", host, port)
        web_thread = start_web_server_thread(
            host=host,
            port=port,
            config=config,
            state=state,
            logger=logger,
            watcher=watcher,
            start_watcher_thread=bool(getattr(args, "web_only", False)),
        )
        time.sleep(1)
        startup_error = _web_server_startup_error(web_thread)
        is_alive = getattr(web_thread, "is_alive", None)
        thread_dead = callable(is_alive) and not bool(is_alive())
        if startup_error is not None or thread_dead:
            if startup_error is not None:
                message = f"Web API failed to start: {startup_error}"
                logger.error(message)
            else:
                message = "Web API failed to start: server thread exited."
                logger.error(message)
            console.print(f"[error]{message}[/]")
            if args.web_only:
                sys.exit(1)
            return None
        return web_thread
    except ImportError as e:
        console.print(f"[error]Could not start web server: {e}[/]")
        console.print("[error]Make sure fastapi and uvicorn are installed[/]")
        if args.web_only:
            sys.exit(1)
        return None


def _web_server_startup_error(web_thread: threading.Thread) -> BaseException | None:
    server = getattr(web_thread, "gengowatcher_api_server", None)
    startup_error = getattr(server, "startup_error", None)
    return startup_error if isinstance(startup_error, BaseException) else None


def _is_tcp_port_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
    except OSError:
        return False
    return True


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
    ui_handler: logging.Handler,
    config: AppConfig,
    state: AppState,
    watcher: GengoWatcher,
    api_thread: threading.Thread | None = None,
) -> None:
    stats_manager = StatsManager()
    app_kwargs = {
        "watcher": watcher,
        "config": config,
        "state": state,
        "stats": stats_manager,
        "ui_log_handler": ui_handler,
    }
    if api_thread is not None:
        app_kwargs["api_thread"] = api_thread
    app = GengoWatcherApp(**app_kwargs)

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
