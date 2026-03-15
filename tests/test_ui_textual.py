"""Unit tests for shared helpers in the textual UI."""

import datetime
import logging
from unittest.mock import MagicMock

import pytest

from textual.css.query import NoMatches

from gengowatcher.ui_textual import (
    ChartsPanel,
    GengoWatcherApp,
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
    rendered = {line.split()[0]: line for line in lines}

    assert len(lines) == 5
    assert "1 ( 20.0%)" in rendered["WebSocket"]
    assert "1 ( 20.0%)" in rendered["Email"]
    assert "1 ( 20.0%)" in rendered["Website"]
    assert "1 ( 20.0%)" in rendered["RSS"]
    assert "1 ( 20.0%)" in rendered["Unknown"]


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


def test_app_setup_logging_attaches_handler_to_watcher_logger(tmp_path):
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
        assert app._log_source is watcher_logger
        assert isinstance(app._textual_log_handler, TextualLogHandler)
        assert app._textual_log_handler in watcher_logger.handlers
    finally:
        app.on_unmount()
