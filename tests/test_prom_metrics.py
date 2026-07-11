"""Tests for Prometheus metrics helpers used by the CLI/TUI runtime."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from gengowatcher.prom_metrics import (
    build_watcher_metrics_snapshot,
    start_watcher_metrics_server,
)


def test_build_watcher_metrics_snapshot_reads_watcher_state():
    watcher = MagicMock()
    watcher.shutdown_event.is_set.return_value = False
    watcher.failure_count = 3
    watcher.session_new_entries = 7
    watcher.session_total_value = 123.45
    watcher.start_time = 100.0

    snapshot = build_watcher_metrics_snapshot(watcher, now=160.0)

    assert snapshot["gengowatcher_watcher_running"] == 1.0
    assert snapshot["gengowatcher_failure_count"] == 3.0
    assert snapshot["gengowatcher_session_new_entries"] == 7.0
    assert snapshot["gengowatcher_session_total_value_usd"] == 123.45
    assert snapshot["gengowatcher_session_uptime_seconds"] == 60.0


def test_start_watcher_metrics_server_warns_when_port_is_in_use(monkeypatch):
    def start_http_server(*, port, addr):
        raise OSError(98, "Address already in use")

    monkeypatch.setitem(
        sys.modules,
        "prometheus_client",
        SimpleNamespace(Gauge=MagicMock(), start_http_server=start_http_server),
    )
    watcher = MagicMock()
    logger = MagicMock()

    server_handle = start_watcher_metrics_server(
        host="127.0.0.1",
        port=9091,
        watcher=watcher,
        logger=logger,
    )

    assert server_handle is None
    logger.warning.assert_called_once()
