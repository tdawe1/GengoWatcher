"""Runtime bootstrap and application lifecycle management."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RATATUI_MANIFEST = PROJECT_ROOT / "prototypes" / "garden-ratatui" / "Cargo.toml"


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
    has_tui_selection = hasattr(args, "tui")
    selected_tui = getattr(args, "tui", None)
    ratatui_requested = (
        selected_tui == "ratatui"
        or (
            has_tui_selection
            and selected_tui is None
            and _find_ratatui_command() is not None
        )
    ) and not getattr(args, "web_only", False)
    config_enabled = False
    if not cli_requested:
        config_enabled = config.getboolean("WebServer", "enabled", fallback=False)

    if not (cli_requested or config_enabled or ratatui_requested):
        return None

    if cli_requested or ratatui_requested:
        host = "127.0.0.1"
        port = int(getattr(args, "web_port", 8000) or 8000)
    else:
        host = str(config.get("WebServer", "host", fallback="127.0.0.1") or "127.0.0.1")
        port = int(config.getint("WebServer", "port", fallback=8000) or 8000)

    if not _is_tcp_port_available(host, port):
        message = f"Web API not started because http://{host}:{port} is already in use."
        logger.warning(message)
        if args.web_only or ratatui_requested:
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
            terminal_logging=bool(getattr(args, "web_only", False)),
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
            if args.web_only or ratatui_requested:
                sys.exit(1)
            return None
        return web_thread
    except ImportError as e:
        console.print(f"[error]Could not start web server: {e}[/]")
        console.print("[error]Make sure fastapi and uvicorn are installed[/]")
        if args.web_only or ratatui_requested:
            sys.exit(1)
        return None


def _web_server_startup_error(web_thread: threading.Thread) -> BaseException | None:
    server = getattr(web_thread, "gengowatcher_api_server", None)
    startup_error = getattr(server, "startup_error", None)
    return startup_error if isinstance(startup_error, BaseException) else None


def _is_tcp_port_available(host: str, port: int) -> bool:
    try:
        addr_infos = socket.getaddrinfo(
            host,
            port,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
    except OSError:
        return False
    for family, socktype, proto, _canonname, sockaddr in addr_infos:
        try:
            with socket.socket(family, socktype, proto) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(sockaddr)
            return True
        except OSError:
            continue
    return False


def _stop_web_server(web_thread: threading.Thread | None) -> None:
    if web_thread is None:
        return
    server = getattr(web_thread, "gengowatcher_api_server", None)
    stop = getattr(server, "stop", None)
    if callable(stop):
        stop()


def _run_web_only(console: Console, web_thread: threading.Thread | None) -> None:
    try:
        if web_thread is not None:
            web_thread.join()
    except KeyboardInterrupt:
        console.print("[info]Web server shutting down...[/]")
    finally:
        _stop_web_server(web_thread)
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
    has_tui_selection = hasattr(args, "tui")
    backend = getattr(args, "tui", None)
    if backend is None:
        backend = (
            "ratatui"
            if has_tui_selection and _find_ratatui_command() is not None
            else "textual"
        )
    app = None
    if backend == "textual":
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

    ui_failed = False
    try:
        if backend == "ratatui":
            _run_ratatui_process(args, config, console, log)
        else:
            app.run()
    except Exception as exc:
        ui_failed = True
        log.exception("UI loop crashed")
        console.print(f"[error]Terminal UI failed: {exc}[/]")
    finally:
        try:
            stats_manager.end_session()
        except Exception:
            log.exception("Failed to persist session stats on shutdown")
        if not watcher.shutdown_event.is_set():
            watcher.handle_exit()
        if backend == "ratatui":
            _stop_web_server(api_thread)

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

    if ui_failed:
        raise SystemExit(1)


def _run_ratatui_process(
    args: argparse.Namespace,
    config: AppConfig,
    console: Console,
    logger: logging.Logger,
) -> None:
    command = _find_ratatui_command(allow_cargo=True)
    if command is None:
        raise RuntimeError(
            "Ratatui TUI binary and Cargo were not found. "
            "Build it with: cargo build --release --manifest-path "
            "prototypes/garden-ratatui/Cargo.toml"
        )

    token = str(config.get("WebServer", "auth_token", fallback="") or "").strip()
    if not token or token.startswith("REPLACE_WITH_"):
        raise RuntimeError("Web API token was not initialized for the Ratatui TUI")

    port = int(getattr(args, "web_port", 8000) or 8000)
    api_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment["GENGOWATCHER_API_TOKEN"] = token
    environment["GENGOWATCHER_API_URL"] = api_url

    logger.info("Starting Ratatui TUI connected to %s", api_url)
    result = subprocess.run(
        [*command, "--api-url", api_url],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
    )
    if result.returncode != 0:
        console.print(f"[error]Ratatui TUI exited with status {result.returncode}.[/]")
        raise RuntimeError(f"Ratatui TUI exited with status {result.returncode}")


def _find_ratatui_binary() -> list[str] | None:
    configured = os.getenv("GENGOWATCHER_RATATUI_BIN", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return [str(path)]

    installed = shutil.which("gengowatcher-tui")
    if installed:
        return [installed]

    target_dir = RATATUI_MANIFEST.parent / "target"
    for profile in ("release", "debug"):
        candidate = target_dir / profile / "gengowatcher-tui"
        if candidate.is_file():
            return [str(candidate)]
    return None


def _find_ratatui_command(*, allow_cargo: bool = False) -> list[str] | None:
    if command := _find_ratatui_binary():
        return command
    if allow_cargo:
        cargo = shutil.which("cargo")
        if cargo and RATATUI_MANIFEST.is_file():
            return [cargo, "run", "--manifest-path", str(RATATUI_MANIFEST), "--"]
    return None
