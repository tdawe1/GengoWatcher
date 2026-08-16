"""Tests for runtime-owned watcher sharing."""

from argparse import Namespace
import socket
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from gengowatcher.runtime import (
    _find_ratatui_command,
    _is_tcp_port_available,
    _run_tui,
    _run_web_only,
    _start_web_server_if_requested,
)


class _DeadWebThread:
    def __init__(self, startup_error=None):
        self.gengowatcher_api_server = SimpleNamespace(startup_error=startup_error)

    def is_alive(self):
        return False


def test_run_web_only_stops_managed_server_on_interrupt():
    console = MagicMock()
    server = MagicMock()
    web_thread = MagicMock()
    web_thread.gengowatcher_api_server = server
    web_thread.join.side_effect = KeyboardInterrupt

    with pytest.raises(SystemExit) as exit_info:
        _run_web_only(console, web_thread)

    assert exit_info.value.code == 0
    server.stop.assert_called_once_with()


def test_start_web_server_reuses_runtime_watcher_for_tui_web_mode():
    args = Namespace(web=True, web_only=False, web_port=37181)
    config = MagicMock()
    state = MagicMock()
    logger = MagicMock()
    watcher = MagicMock()
    web_thread = MagicMock()

    with (
        patch(
            "gengowatcher.web.start_web_server_thread",
            return_value=web_thread,
        ) as mock_start_web_server,
        patch("gengowatcher.runtime.time.sleep"),
    ):
        thread = _start_web_server_if_requested(
            args,
            MagicMock(),
            config=config,
            state=state,
            logger=logger,
            watcher=watcher,
        )

    assert thread is web_thread
    mock_start_web_server.assert_called_once_with(
        host="127.0.0.1",
        port=37181,
        config=config,
        state=state,
        logger=logger,
        watcher=watcher,
        start_watcher_thread=False,
        terminal_logging=False,
    )


def test_start_web_server_starts_runtime_watcher_for_web_only_mode():
    args = Namespace(web=False, web_only=True, web_port=37181)
    config = MagicMock()
    state = MagicMock()
    logger = MagicMock()
    watcher = MagicMock()

    with (
        patch("gengowatcher.web.start_web_server_thread") as mock_start_web_server,
        patch("gengowatcher.runtime.time.sleep"),
    ):
        _start_web_server_if_requested(
            args,
            MagicMock(),
            config=config,
            state=state,
            logger=logger,
            watcher=watcher,
        )

    assert mock_start_web_server.call_args.kwargs["start_watcher_thread"] is True
    assert mock_start_web_server.call_args.kwargs["terminal_logging"] is True


def test_start_web_server_is_forced_for_ratatui_on_loopback():
    args = Namespace(
        web=False,
        web_only=False,
        web_port=37181,
        tui="ratatui",
    )
    config = MagicMock()
    config.getboolean.return_value = False
    config.getint.return_value = 48222
    state = MagicMock()
    logger = MagicMock()
    watcher = MagicMock()
    web_thread = MagicMock()

    with (
        patch("gengowatcher.runtime._is_tcp_port_available", return_value=True),
        patch(
            "gengowatcher.web.start_web_server_thread",
            return_value=web_thread,
        ) as mock_start_web_server,
        patch("gengowatcher.runtime.time.sleep"),
    ):
        result = _start_web_server_if_requested(
            args,
            MagicMock(),
            config=config,
            state=state,
            logger=logger,
            watcher=watcher,
        )

    assert result is web_thread
    assert mock_start_web_server.call_args.kwargs["host"] == "127.0.0.1"
    assert mock_start_web_server.call_args.kwargs["port"] == 48222
    assert mock_start_web_server.call_args.kwargs["start_watcher_thread"] is False


def test_start_web_server_exits_web_only_when_thread_records_startup_error():
    args = Namespace(web=False, web_only=True, web_port=37181)
    config = MagicMock()
    state = MagicMock()
    logger = MagicMock()
    watcher = MagicMock()
    console = MagicMock()
    startup_error = RuntimeError("bind failed")

    with (
        patch("gengowatcher.runtime._is_tcp_port_available", return_value=True),
        patch(
            "gengowatcher.web.start_web_server_thread",
            return_value=_DeadWebThread(startup_error),
        ),
        patch("gengowatcher.runtime.time.sleep"),
        pytest.raises(SystemExit) as exit_info,
    ):
        _start_web_server_if_requested(
            args,
            console,
            config=config,
            state=state,
            logger=logger,
            watcher=watcher,
        )

    assert exit_info.value.code == 1
    logger.error.assert_called_once()
    console.print.assert_called_once()


def test_start_web_server_uses_saved_web_server_config_when_enabled():
    args = Namespace(web=False, web_only=False, web_port=37181)
    config = MagicMock()
    config.getboolean.return_value = True
    config.get.return_value = "0.0.0.0"
    config.getint.return_value = 48222
    state = MagicMock()
    logger = MagicMock()
    watcher = MagicMock()
    web_thread = MagicMock()

    with (
        patch(
            "gengowatcher.web.start_web_server_thread",
            return_value=web_thread,
        ) as mock_start_web_server,
        patch("gengowatcher.runtime.time.sleep"),
    ):
        thread = _start_web_server_if_requested(
            args,
            MagicMock(),
            config=config,
            state=state,
            logger=logger,
            watcher=watcher,
        )

    assert thread is web_thread
    mock_start_web_server.assert_called_once_with(
        host="0.0.0.0",
        port=48222,
        config=config,
        state=state,
        logger=logger,
        watcher=watcher,
        start_watcher_thread=False,
        terminal_logging=False,
    )


def test_start_web_server_skips_when_port_is_in_use():
    args = Namespace(web=False, web_only=False, web_port=37181)
    config = MagicMock()
    config.getboolean.return_value = True
    config.get.return_value = "127.0.0.1"
    config.getint.return_value = 8000
    state = MagicMock()
    logger = MagicMock()
    watcher = MagicMock()
    console = MagicMock()

    with (
        patch("gengowatcher.runtime._is_tcp_port_available", return_value=False),
        patch("gengowatcher.web.start_web_server_thread") as mock_start_web_server,
    ):
        thread = _start_web_server_if_requested(
            args,
            console,
            config=config,
            state=state,
            logger=logger,
            watcher=watcher,
        )

    assert thread is None
    mock_start_web_server.assert_not_called()
    logger.warning.assert_called_once()
    console.print.assert_not_called()


def test_start_web_server_prints_port_conflict_for_web_only_mode():
    args = Namespace(web=False, web_only=True, web_port=37181)
    config = MagicMock()
    config.getboolean.return_value = True
    config.get.return_value = "127.0.0.1"
    config.getint.return_value = 8000
    state = MagicMock()
    logger = MagicMock()
    watcher = MagicMock()
    console = MagicMock()

    with (
        patch("gengowatcher.runtime._is_tcp_port_available", return_value=False),
        patch("gengowatcher.web.start_web_server_thread") as mock_start_web_server,
        pytest.raises(SystemExit) as exit_info,
    ):
        _start_web_server_if_requested(
            args,
            console,
            config=config,
            state=state,
            logger=logger,
            watcher=watcher,
        )

    assert exit_info.value.code == 1
    mock_start_web_server.assert_not_called()
    logger.warning.assert_called_once()
    console.print.assert_called_once()


def test_start_web_server_port_conflict_stops_ratatui_before_token_forwarding():
    args = Namespace(
        web=False,
        web_only=False,
        web_port=37181,
        tui="ratatui",
    )
    config = MagicMock()
    config.getboolean.return_value = False
    config.getint.return_value = 48222
    state = MagicMock()
    logger = MagicMock()
    watcher = MagicMock()
    console = MagicMock()

    with (
        patch("gengowatcher.runtime._is_tcp_port_available", return_value=False),
        patch("gengowatcher.web.start_web_server_thread") as mock_start_web_server,
        pytest.raises(SystemExit) as exit_info,
    ):
        _start_web_server_if_requested(
            args,
            console,
            config=config,
            state=state,
            logger=logger,
            watcher=watcher,
        )

    assert exit_info.value.code == 1
    mock_start_web_server.assert_not_called()
    console.print.assert_called_once()


def test_is_tcp_port_available_uses_resolved_address_family():
    sockaddr = ("::1", 48222, 0, 0)
    with (
        patch(
            "gengowatcher.runtime.socket.getaddrinfo",
            return_value=[
                (
                    socket.AF_INET6,
                    socket.SOCK_STREAM,
                    0,
                    "",
                    sockaddr,
                )
            ],
        ),
        patch("gengowatcher.runtime.socket.socket") as mock_socket,
    ):
        available = _is_tcp_port_available("::1", 48222)

    assert available is True
    mock_socket.assert_called_once_with(socket.AF_INET6, socket.SOCK_STREAM, 0)
    mock_socket.return_value.__enter__.return_value.bind.assert_called_once_with(
        sockaddr
    )


def test_run_tui_passes_buffered_ui_log_handler_to_app():
    args = Namespace()
    console = MagicMock()
    logger = MagicMock()
    ui_handler = MagicMock()
    config = MagicMock()
    state = MagicMock()
    watcher = MagicMock()
    watcher.shutdown_event.is_set.return_value = False

    with (
        patch("gengowatcher.runtime.StatsManager") as mock_stats_manager,
        patch("gengowatcher.runtime.GengoWatcherApp") as mock_app_class,
        patch("gengowatcher.runtime.threading.Thread") as mock_thread,
    ):
        _run_tui(args, console, logger, ui_handler, config, state, watcher)

    mock_app_class.assert_called_once_with(
        watcher=watcher,
        config=config,
        state=state,
        stats=mock_stats_manager.return_value,
        ui_log_handler=ui_handler,
    )
    mock_thread.return_value.start.assert_called_once()
    mock_app_class.return_value.run.assert_called_once()


def test_run_tui_passes_api_thread_to_app_when_available():
    args = Namespace()
    console = MagicMock()
    logger = MagicMock()
    ui_handler = MagicMock()
    config = MagicMock()
    state = MagicMock()
    watcher = MagicMock()
    api_thread = MagicMock()
    watcher.shutdown_event.is_set.return_value = False

    with (
        patch("gengowatcher.runtime.StatsManager") as mock_stats_manager,
        patch("gengowatcher.runtime.GengoWatcherApp") as mock_app_class,
        patch("gengowatcher.runtime.threading.Thread") as mock_thread,
    ):
        _run_tui(
            args,
            console,
            logger,
            ui_handler,
            config,
            state,
            watcher,
            api_thread=api_thread,
        )

    mock_app_class.assert_called_once_with(
        watcher=watcher,
        config=config,
        state=state,
        stats=mock_stats_manager.return_value,
        ui_log_handler=ui_handler,
        api_thread=api_thread,
    )
    mock_thread.return_value.start.assert_called_once()
    mock_app_class.return_value.run.assert_called_once()


def test_run_tui_launches_ratatui_with_token_in_environment_only():
    args = Namespace(tui="ratatui", web=False, web_port=8000)
    console = MagicMock()
    logger = MagicMock()
    ui_handler = MagicMock()
    config = MagicMock()
    config.get.return_value = "secret-token"
    config.getint.return_value = 48222
    state = MagicMock()
    watcher = MagicMock()
    watcher.shutdown_event.is_set.return_value = False

    with (
        patch("gengowatcher.runtime.StatsManager"),
        patch("gengowatcher.runtime.GengoWatcherApp") as mock_app_class,
        patch("gengowatcher.runtime.threading.Thread") as mock_thread,
        patch(
            "gengowatcher.runtime._find_ratatui_command",
            return_value=["/tmp/gengowatcher-tui"],
        ),
        patch("gengowatcher.runtime.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        _run_tui(args, console, logger, ui_handler, config, state, watcher)

    mock_app_class.assert_not_called()
    mock_thread.return_value.start.assert_called_once()
    command = mock_run.call_args.args[0]
    environment = mock_run.call_args.kwargs["env"]
    assert "secret-token" not in command
    assert environment["GENGOWATCHER_API_TOKEN"] == "secret-token"
    assert environment["GENGOWATCHER_API_URL"] == "http://127.0.0.1:48222"


def test_run_tui_cleans_up_and_exits_nonzero_when_ratatui_fails():
    args = Namespace(tui="ratatui", web=False, web_port=8000)
    console = MagicMock()
    logger = MagicMock()
    watcher = MagicMock()
    watcher.shutdown_event.is_set.return_value = False

    with (
        patch("gengowatcher.runtime.StatsManager"),
        patch("gengowatcher.runtime.threading.Thread"),
        patch(
            "gengowatcher.runtime._run_ratatui_process",
            side_effect=RuntimeError("binary missing"),
        ),
        pytest.raises(SystemExit) as exit_info,
    ):
        _run_tui(
            args,
            console,
            logger,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            watcher,
        )

    assert exit_info.value.code == 1
    watcher.handle_exit.assert_called_once()
    console.print.assert_any_call("[error]Terminal UI failed: binary missing[/]")


def test_find_ratatui_command_requires_binary_for_auto_select(tmp_path, monkeypatch):
    monkeypatch.delenv("GENGOWATCHER_RATATUI_BIN", raising=False)
    monkeypatch.setattr(
        "gengowatcher.runtime.shutil.which",
        lambda name: "/usr/bin/cargo" if name == "cargo" else None,
    )
    monkeypatch.setattr(
        "gengowatcher.runtime.RATATUI_MANIFEST", tmp_path / "Cargo.toml"
    )
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'garden-ratatui'\n")

    assert _find_ratatui_command() is None

    command = _find_ratatui_command(allow_cargo=True)
    assert command[:3] == ["/usr/bin/cargo", "run", "--manifest-path"]
    assert command[3] == str(tmp_path / "Cargo.toml")
    assert command[4] == "--"


def test_run_tui_auto_select_uses_textual_when_only_cargo_is_available(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("GENGOWATCHER_RATATUI_BIN", raising=False)
    monkeypatch.setattr(
        "gengowatcher.runtime.shutil.which",
        lambda name: "/usr/bin/cargo" if name == "cargo" else None,
    )
    monkeypatch.setattr(
        "gengowatcher.runtime.RATATUI_MANIFEST", tmp_path / "Cargo.toml"
    )
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'garden-ratatui'\n")

    args = Namespace(tui=None)
    watcher = MagicMock()
    watcher.shutdown_event.is_set.return_value = False

    with (
        patch("gengowatcher.runtime.StatsManager"),
        patch("gengowatcher.runtime.GengoWatcherApp") as mock_app_class,
        patch("gengowatcher.runtime.threading.Thread"),
        patch("gengowatcher.runtime._run_ratatui_process") as mock_ratatui,
    ):
        _run_tui(
            args,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            watcher,
        )

    mock_app_class.assert_called_once()
    mock_ratatui.assert_not_called()
