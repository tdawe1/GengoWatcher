import io
from unittest.mock import MagicMock

import pytest

from gengowatcher.orchestration.watcher_config_io import (
    get_config_value,
    set_config_value,
)
from gengowatcher.orchestration.watcher_debug import redact_raw_ws_value
from gengowatcher.orchestration.watcher_feed import log_all_entries
from gengowatcher.orchestration.watcher_monitor_status import sync_monitor_metrics


def test_log_all_entries_ignores_a_closed_file():
    watcher = MagicMock()
    log_file = io.StringIO()
    log_file.close()
    watcher._all_entries_log_file = log_file

    log_all_entries(watcher, [{"title": "job"}])

    watcher._csv_writer.writerow.assert_not_called()


def test_log_all_entries_tolerates_file_closing_during_flush():
    watcher = MagicMock()
    watcher._all_entries_log_file.closed = False
    watcher._all_entries_log_file.flush.side_effect = ValueError("closed")

    log_all_entries(watcher, [{"title": "job"}])

    watcher.logger.debug.assert_called_once()


def test_config_helpers_never_log_secret_values():
    watcher = MagicMock()
    watcher.config.get.return_value = "super-secret-session"

    set_config_value(
        watcher,
        "WebSocket",
        "user_session",
        "super-secret-session",
    )
    assert get_config_value(watcher, "WebSocket", "user_session") == (
        "super-secret-session"
    )

    logged = repr(
        watcher.logger.debug.call_args_list + watcher.logger.info.call_args_list
    )
    assert "super-secret-session" not in logged
    assert "<redacted>" in logged


def test_config_success_is_not_logged_when_save_fails():
    watcher = MagicMock()
    watcher.config.save_config.side_effect = OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        set_config_value(watcher, "Watcher", "check_interval", 60)

    watcher.logger.info.assert_not_called()


def test_sync_monitor_metrics_clears_stale_values():
    watcher = MagicMock()
    watcher._email_monitor = None
    watcher._website_monitor = None
    watcher.email_monitor_status = "Connected"
    watcher.email_last_check_time = 123.0
    watcher.email_jobs_found_session = 4
    watcher.website_monitor_status = "Monitoring"
    watcher.website_last_check_time = 456.0
    watcher.website_jobs_found_session = 5

    sync_monitor_metrics(watcher)

    assert watcher.email_monitor_status == "Disabled"
    assert watcher.email_last_check_time is None
    assert watcher.email_jobs_found_session == 0
    assert watcher.website_monitor_status == "Disabled"
    assert watcher.website_last_check_time is None
    assert watcher.website_jobs_found_session == 0


def test_recursive_raw_ws_redaction_masks_secrets_under_benign_keys():
    redacted = redact_raw_ws_value(
        {"notes": "token=abc123", "items": ["my_gengo_session=session-value"]}
    )

    assert redacted == {
        "notes": "token=[REDACTED]",
        "items": ["my_gengo_session=[REDACTED]"],
    }
