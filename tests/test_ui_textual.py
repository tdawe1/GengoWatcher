"""Unit tests for shared helpers in the textual UI."""

import datetime
from unittest.mock import MagicMock

import pytest

from textual.css.query import NoMatches

from gengowatcher.ui_textual import (
    ChartsPanel,
    SourcesBreakdown,
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


def test_sources_breakdown_normalizes_sources():
    jobs = [
        {"source": "RSS"},
        {"source": "WebSocket"},
        {"source": "email"},
        {"source": "website"},
        {"source": "unknown"},
    ]
    state = DummySourceState(jobs)
    panel = SourcesBreakdown(state=state)
    mock_static = MagicMock()
    panel.query_one = MagicMock(return_value=mock_static)

    panel.refresh_sources()

    mock_static.update.assert_called_once_with(
        "WS: 20%\nEmail: 20%\nWebsite: 20%\nRSS: 20%"
    )


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
