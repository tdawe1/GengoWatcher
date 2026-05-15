"""Tests for runtime-owned watcher sharing."""

from argparse import Namespace
from unittest.mock import MagicMock, patch

from gengowatcher.runtime import _run_tui, _start_web_server_if_requested


class _InlineThread:
    def __init__(self, target, daemon=None, name=None):
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False

    def start(self):
        self.started = True
        self.target()

    def join(self, timeout=None):
        return None


def test_start_web_server_reuses_runtime_watcher_for_tui_web_mode():
    args = Namespace(web=True, web_only=False, web_port=37181)
    config = MagicMock()
    state = MagicMock()
    logger = MagicMock()
    watcher = MagicMock()

    with (
        patch("gengowatcher.web.run_web_server") as mock_run_web_server,
        patch("gengowatcher.runtime.threading.Thread", _InlineThread),
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

    assert isinstance(thread, _InlineThread)
    mock_run_web_server.assert_called_once_with(
        host="127.0.0.1",
        port=37181,
        config=config,
        state=state,
        logger=logger,
        watcher=watcher,
        start_watcher_thread=False,
    )


def test_start_web_server_starts_runtime_watcher_for_web_only_mode():
    args = Namespace(web=False, web_only=True, web_port=37181)
    config = MagicMock()
    state = MagicMock()
    logger = MagicMock()
    watcher = MagicMock()

    with (
        patch("gengowatcher.web.run_web_server") as mock_run_web_server,
        patch("gengowatcher.runtime.threading.Thread", _InlineThread),
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

    assert mock_run_web_server.call_args.kwargs["start_watcher_thread"] is True


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
