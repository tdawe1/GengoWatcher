"""Unit tests for shared helpers in the textual UI."""

import datetime
import logging
import threading
from unittest.mock import MagicMock

import pytest

from textual.css.query import NoMatches

from gengowatcher.ui_textual import (
    ChartsPanel,
    TextualLogHandler,
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


def test_format_timestamp_handles_various_formats():
    epoch = 1672531200
    expected = datetime.datetime.fromtimestamp(epoch).strftime("%H:%M:%S")
    assert _format_timestamp(epoch) == expected
    assert _format_timestamp("2024-01-01T12:34:56Z") == "12:34:56"
    assert _format_timestamp("2024-01-01 03:02:01") == "03:02:01"
    assert _format_timestamp("03:02:01.123") == "03:02:01"
    assert _format_timestamp("") == ""
    assert _format_timestamp(None) == ""


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
    app._thread_id = threading.get_ident()
    handler = TextualLogHandler(app)
    handler.write_log = MagicMock()

    record = logging.LogRecord(
        "test_ui_textual", logging.INFO, __file__, 1, "hello", (), None
    )
    handler.emit(record)

    handler.write_log.assert_called_once_with("hello", logging.INFO)
    app.call_from_thread.assert_not_called()


def test_textual_log_handler_emit_from_background_thread_uses_call_from_thread():
    app = MagicMock()
    app._thread_id = threading.get_ident() + 1
    handler = TextualLogHandler(app)
    handler.write_log = MagicMock()

    record = logging.LogRecord(
        "test_ui_textual", logging.WARNING, __file__, 1, "hello", (), None
    )
    handler.emit(record)

    app.call_from_thread.assert_called_once_with(
        handler.write_log, "hello", logging.WARNING
    )
    handler.write_log.assert_not_called()


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
        ((MetricsRow, "refresh_metrics"),),
        ((SessionStats, "refresh_stats"),),
        ((HourlyActivity, "refresh_hourly"),),
        ((JobsPreview, "refresh_jobs"),),
        ((TelemetryPanel, "refresh_telemetry"),),
    ]
