"""Unit tests for shared helpers in the textual UI."""

import datetime
import logging
import threading
from unittest.mock import MagicMock, patch

import pytest

from textual.css.query import NoMatches

from gengowatcher.ui_textual import (
    ChartsPanel,
    CommandInput,
    GengoWatcherApp,
    HourlyActivity,
    JobsPreview,
    MetricsRow,
    TelemetryPanel,
    TextualLogHandler,
    _format_job_row,
    _format_job_time_left,
    _format_timestamp,
    _normalize_source,
)


class DummyState:
    def get_recent_jobs(self, limit):
        return [{"reward": float(i)} for i in range(limit)]


class DummySourceState:
    def __init__(self, jobs):
        self._jobs = jobs

    def get_recent_jobs(self, limit):
        return self._jobs[:limit]


class _DummyCommandInput(CommandInput):
    @property
    def value(self):
        return getattr(self, "_test_value", "")

    @value.setter
    def value(self, value):
        self._test_value = value


def _make_command_config(values):
    config = MagicMock()

    def list_all():
        return {
            section: section_values.copy() for section, section_values in values.items()
        }

    def get(section, key, fallback=None):
        return values.get(section, {}).get(key, fallback)

    def getboolean(section, key, fallback=None):
        value = get(section, key, fallback)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"true", "1", "yes", "on", "enabled"}
        return bool(value)

    def getint(section, key, fallback=None):
        return int(get(section, key, fallback))

    def set_value(section, key, value):
        values.setdefault(section, {})[key] = value

    config.list_all.side_effect = list_all
    config.get.side_effect = get
    config.getboolean.side_effect = getboolean
    config.getint.side_effect = getint
    config.set.side_effect = set_value
    return config


def _make_command_app(values):
    watcher = MagicMock()
    watcher.logger = logging.getLogger("test_ui_textual_commands")
    app = GengoWatcherApp(
        config=_make_command_config(values),
        state=MagicMock(),
        watcher=watcher,
        stats=MagicMock(),
    )
    app._textual_log_handler.write_log = MagicMock()
    return app


def test_format_timestamp_handles_various_formats():
    epoch = 1672531200
    expected = datetime.datetime.fromtimestamp(epoch).strftime("%H:%M:%S")
    assert _format_timestamp(epoch) == expected
    assert _format_timestamp("2024-01-01T12:34:56Z") == "12:34:56"
    assert _format_timestamp("2024-01-01 03:02:01") == "03:02:01"
    assert _format_timestamp("03:02:01.123") == "03:02:01"
    assert _format_timestamp("") == ""
    assert _format_timestamp(None) == ""


def test_format_job_time_left_uses_browser_countdown_for_visible_job():
    assert _format_job_time_left({"seconds_left": 3671, "accepted": False}) == "1h 01m"
    assert _format_job_time_left({"accepted_seconds_left": 59}) == "0m 59s"
    assert _format_job_time_left({"accepted_expired": True}) == "expired"


def test_format_job_row_includes_browser_collected_fields():
    row = _format_job_row(
        {
            "id": "34178123",
            "lang_pair": "JA->EN",
            "reward": 8.13,
            "source": "Browser",
            "acceptance_state": "details_visible",
            "seconds_left": 600,
            "timestamp": 1782967137.0,
            "order_id": 98765,
            "workbench_visible": True,
            "source_text": "hello",
            "segments": [{"source_content": "hello"}],
            "word_count": 263,
        }
    )

    assert row[:7] == (
        "34178123",
        "JA->EN",
        "263",
        "$8.13",
        "Browser",
        "details_visi",
        "10m 00s",
    )
    assert row[8:] == ("98765", "visible", "5c", "1")


@pytest.mark.parametrize(
    "source,expected",
    [
        ("WebSocket", "websocket"),
        ("ws", "websocket"),
        ("EMAIL", "email"),
        ("imap", "email"),
        ("rss feed", "rss"),
        ("https://example.com", "website"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_normalize_source_maps_known_buckets(source, expected):
    assert _normalize_source(source) == expected


def test_value_trend_limits_to_20_jobs():
    panel = ChartsPanel(stats=None, state=DummyState())
    text = panel._render_value_trend()
    lines = [line for line in text.plain.splitlines() if line.strip()]
    assert len(lines) == 20


def test_charts_panel_renders_normalized_source_breakdown():
    jobs = [
        {"source": "RSS"},
        {"source": "WebSocket"},
        {"source": "email"},
        {"source": "website"},
        {"source": "unknown"},
    ]
    state = DummySourceState(jobs)
    panel = ChartsPanel(stats=None, state=state)

    text = panel._render_sources_chart()
    lines = text.plain.strip().splitlines()

    assert len(lines) == 5
    assert lines[0].startswith("WebSocket") and "1 ( 20.0%)" in lines[0]
    assert lines[1].startswith("Email") and "1 ( 20.0%)" in lines[1]
    assert lines[2].startswith("Website") and "1 ( 20.0%)" in lines[2]
    assert lines[3].startswith("RSS") and "1 ( 20.0%)" in lines[3]
    assert lines[4].startswith("Unknown") and "1 ( 20.0%)" in lines[4]


def test_textual_log_handler_write_to_log_handles_missing_widget():
    app = MagicMock()
    app.query_one.side_effect = NoMatches
    handler = TextualLogHandler(app)

    handler._write_to_log("#activity-log", handler._colorize_message("msg", 20))


def test_textual_log_handler_write_to_log_writes_to_widget():
    log_widget = MagicMock()
    app = MagicMock()
    app.query_one.return_value = log_widget
    handler = TextualLogHandler(app)

    colored_text = handler._colorize_message("msg", 20)
    handler._write_to_log("#activity-log", colored_text)

    log_widget.write.assert_called_once_with(colored_text)


def test_textual_log_handler_emit_on_app_thread_writes_directly():
    app = MagicMock()
    handler = TextualLogHandler(app, ui_thread_id=threading.get_ident())
    handler.write_log = MagicMock()

    record = logging.LogRecord(
        "test_ui_textual", logging.INFO, __file__, 1, "hello", (), None
    )
    handler.emit(record)

    handler.write_log.assert_called_once_with("hello", logging.INFO)
    app.call_from_thread.assert_not_called()


def test_textual_log_handler_emit_from_background_thread_uses_call_from_thread():
    app = MagicMock()
    handler = TextualLogHandler(app, ui_thread_id=threading.get_ident() + 1)
    handler.write_log = MagicMock()

    record = logging.LogRecord(
        "test_ui_textual", logging.WARNING, __file__, 1, "hello", (), None
    )
    handler.emit(record)

    app.call_from_thread.assert_called_once_with(
        handler.write_log, "hello", logging.WARNING
    )
    handler.write_log.assert_not_called()


def test_textual_log_handler_writes_info_to_output_log():
    app = MagicMock()
    handler = TextualLogHandler(app)
    handler._write_to_log = MagicMock()

    handler.write_log("RSS check triggered", logging.INFO)

    written_widget_ids = [call.args[0] for call in handler._write_to_log.call_args_list]
    assert written_widget_ids == [
        "#activity-log",
        "#output-log",
    ]


def test_app_setup_logging_attaches_handler_on_mount_and_removes_on_unmount(tmp_path):
    watcher_logger = logging.getLogger("test_ui_textual_app_logger")
    watcher_logger.handlers = []
    watcher_logger.propagate = False

    watcher = MagicMock()
    watcher.logger = watcher_logger

    app = GengoWatcherApp(
        config=MagicMock(),
        state=MagicMock(),
        watcher=watcher,
        stats=MagicMock(),
    )

    try:
        assert not any(
            isinstance(handler, TextualLogHandler)
            for handler in watcher_logger.handlers
        )

        app._setup_jobs_table = MagicMock()
        app._refresh_dashboard_panels = MagicMock()
        app.set_interval = MagicMock()
        app.on_mount()

        assert app._log_source is watcher_logger
        assert isinstance(app._textual_log_handler, TextualLogHandler)
        assert app._textual_log_handler in watcher_logger.handlers
    finally:
        app.on_unmount()

    assert watcher.on_job_added_callback is None
    assert app._textual_log_handler not in watcher_logger.handlers


def test_refresh_dashboard_panels_only_targets_mounted_dashboard_widgets():
    app = GengoWatcherApp(
        config=MagicMock(),
        state=MagicMock(),
        watcher=MagicMock(),
        stats=MagicMock(),
    )
    app._refresh_widget = MagicMock()

    app._refresh_dashboard_panels()

    assert app._refresh_widget.call_args_list == [
        ((MetricsRow, "refresh_metrics"), {"missing_level": logging.WARNING}),
        ((JobsPreview, "refresh_jobs"), {"missing_level": logging.WARNING}),
        ((HourlyActivity, "refresh_hourly"), {"missing_level": logging.WARNING}),
        ((TelemetryPanel, "refresh_telemetry"), {"missing_level": logging.WARNING}),
    ]


def test_command_input_submission_runs_command_and_clears_input():
    app = _make_command_app({"WebServer": {"enabled": False}})
    app._run_command = MagicMock()
    command_input = object.__new__(_DummyCommandInput)
    command_input.value = "help"
    event = MagicMock()
    event.input = command_input
    event.value = "help"

    app._on_command_submitted(event)

    app._run_command.assert_called_once_with("help")
    assert command_input.value == ""
    event.stop.assert_called_once()


@pytest.mark.asyncio
async def test_command_input_submission_from_textual_input_runs_command():
    app = _make_command_app({"WebServer": {"enabled": False}})
    app.state.get_recent_jobs.return_value = []
    app.state.session_start = None
    app._run_command = MagicMock()

    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.focused, CommandInput)
        await pilot.press("h", "e", "l", "p", "enter")
        await pilot.pause()

    app._run_command.assert_called_once_with("help")


def test_run_command_sets_existing_config_value():
    values = {"WebServer": {"enabled": False, "host": "127.0.0.1", "port": 8000}}
    app = _make_command_app(values)

    app._run_command("set WebServer.enabled true")

    assert values["WebServer"]["enabled"] is True
    app.config.set.assert_called_with("WebServer", "enabled", True)
    app.config.save_config.assert_called_once()
    app._textual_log_handler.write_log.assert_any_call(
        "Set WebServer.enabled = True",
        logging.INFO,
    )


def test_run_command_get_masks_sensitive_value():
    values = {"WebSocket": {"user_session": "abcdef123456"}}
    app = _make_command_app(values)

    app._run_command("get WebSocket.user_session")

    messages = [
        call.args[0] for call in app._textual_log_handler.write_log.call_args_list
    ]
    assert "WebSocket.user_session = abcd...3456" in messages
    assert all("abcdef123456" not in message for message in messages)


def test_run_command_watcher_control_aliases_call_watcher_methods():
    app = _make_command_app({"WebServer": {"enabled": False}})

    app._run_command("pause")
    app.watcher.pause_monitoring.assert_called_once()
    app._textual_log_handler.write_log.assert_any_call(
        "Watcher paused.",
        logging.INFO,
    )

    app._run_command("resume")
    app.watcher.resume_monitoring.assert_called_once()
    app._textual_log_handler.write_log.assert_any_call(
        "Watcher resumed.",
        logging.INFO,
    )

    app._run_command("notify")
    app.watcher.run_notify_test.assert_called_once()
    app._textual_log_handler.write_log.assert_any_call(
        "Notification test requested.",
        logging.INFO,
    )

    app._run_command("ping")
    app.watcher.queue_websocket_test_command.assert_called_once_with("ping")
    app._textual_log_handler.write_log.assert_any_call(
        "WebSocket ping test queued.",
        logging.INFO,
    )


def test_run_command_api_status_reports_url():
    values = {"WebServer": {"enabled": False, "host": "127.0.0.1", "port": 8765}}
    app = _make_command_app(values)
    app._api_port_open = MagicMock(return_value=False)

    app._run_command("api status")

    app._textual_log_handler.write_log.assert_any_call(
        "API stopped; enabled=False; url=http://127.0.0.1:8765",
        logging.INFO,
    )


def test_run_command_api_start_saves_config_and_starts_server():
    values = {"WebServer": {"enabled": False, "host": "127.0.0.1", "port": 8765}}
    app = _make_command_app(values)
    app._api_port_open = MagicMock(side_effect=[False, True])
    api_server = MagicMock()
    api_server.startup_error = None
    api_thread = MagicMock()
    api_thread.gengowatcher_api_server = api_server

    with patch(
        "gengowatcher.web.start_web_server_thread",
        return_value=api_thread,
    ) as mock_start_web_server:
        app._run_command("api start")

    assert values["WebServer"]["enabled"] is True
    app.config.set.assert_called_with("WebServer", "enabled", True)
    app.config.save_config.assert_called_once()
    mock_start_web_server.assert_called_once_with(
        host="127.0.0.1",
        port=8765,
        config=app.config,
        state=app.state,
        logger=app._log_source,
        watcher=app.watcher,
        start_watcher_thread=False,
    )
    app._textual_log_handler.write_log.assert_any_call(
        "API started at http://127.0.0.1:8765",
        logging.INFO,
    )


def test_run_command_api_stop_stops_owned_server_and_disables_config():
    values = {"WebServer": {"enabled": True, "host": "127.0.0.1", "port": 8765}}
    app = _make_command_app(values)
    api_server = MagicMock()
    api_server.stop.return_value = True
    app._api_server = api_server
    app._api_thread = MagicMock()

    app._run_command("api stop")

    assert values["WebServer"]["enabled"] is False
    api_server.stop.assert_called_once_with(timeout=5.0)
    app._textual_log_handler.write_log.assert_any_call(
        "API stopped and disabled.",
        logging.INFO,
    )
