import logging
import os
from pathlib import Path
import time
from unittest.mock import MagicMock

import pytest

import gengowatcher.browser_session as browser_session
import gengowatcher.browser_session_core as browser_session_core
import gengowatcher.ui_charts as ui_charts
import gengowatcher.ui_formatting as ui_formatting
import gengowatcher.ui_textual as ui_textual
from gengowatcher.watcher_debug import RAW_WS_REDACTED, redact_raw_ws_text
from gengowatcher.watcher_health import timestamp_or_none
from gengowatcher.watcher_job_metadata import (
    normalize_lang_pair_string,
    parse_lang_pair_from_title,
)
from gengowatcher.web_file_storage import WebFileStorage
from gengowatcher.web_models import CommandRequest, SECURITY


def _storage(tmp_path: Path) -> WebFileStorage:
    config = MagicMock()
    config.get.side_effect = lambda section, key, **kwargs: {
        ("Paths", "file_storage_dir"): str(tmp_path / "files"),
        ("TranslationWorkflow", "file_retention_days"): 1,
    }.get((section, key), kwargs.get("fallback", ""))
    return WebFileStorage(config, logging.getLogger("test-pr111-review-feedback"))


def test_file_storage_removes_expired_files_and_metadata(tmp_path):
    storage = _storage(tmp_path)
    entry = storage.save_uploaded_file("source.txt", b"text")
    path = storage.get_file_path(entry.stored_name)
    metadata_path = storage.metadata_path(path)
    old = time.time() - 3 * 86400
    os.utime(path, (old, old))
    os.utime(metadata_path, (old, old))

    assert storage.cleanup_expired_files() == 2
    assert not path.exists()
    assert not metadata_path.exists()


def test_backward_compatibility_aliases_live_in_importing_modules():
    assert not hasattr(browser_session_core, "_normalize_debug_url")
    assert not hasattr(browser_session_core, "_coerce_cookie_value")
    assert not hasattr(ui_charts, "_render_chart")
    assert not hasattr(ui_formatting, "_format_timestamp")

    assert browser_session._normalize_debug_url("127.0.0.1") == (
        "http://127.0.0.1:9222"
    )
    assert ui_textual._render_chart([1, 2], width=2, height=1)
    assert ui_textual._format_timestamp("2024-01-01T12:34:56Z") == "12:34:56"


def test_raw_websocket_text_redacts_common_token_like_fields():
    redacted = redact_raw_ws_text(
        'token=plain api_key:"abc123" "secret": "hidden" refresh_token=rtvalue'
    )

    assert "plain" not in redacted
    assert "abc123" not in redacted
    assert "hidden" not in redacted
    assert "rtvalue" not in redacted
    assert redacted.count(RAW_WS_REDACTED) == 4


def test_language_pair_split_does_not_treat_locale_hyphen_as_pair_separator():
    assert normalize_lang_pair_string("en-us") == ""
    assert parse_lang_pair_from_title("en-us | Locale-specific job") == ""
    assert normalize_lang_pair_string("JA - EN") == "JA→EN"
    assert normalize_lang_pair_string("JA->EN") == "JA→EN"


def test_timestamp_or_none_only_swallows_expected_timestamp_conversion_errors():
    class BadTimestamp:
        def timestamp(self):
            raise ValueError("outside supported range")

    class UnexpectedTimestampFailure:
        def timestamp(self):
            raise RuntimeError("programming error")

    assert timestamp_or_none(BadTimestamp()) is None
    with pytest.raises(RuntimeError, match="programming error"):
        timestamp_or_none(UnexpectedTimestampFailure())


def test_command_request_accepts_websocket_test_commands():
    for command in ("ping", "notify"):
        assert CommandRequest(command=command).command == command


def test_command_request_args_default_is_not_shared_and_accepts_none():
    first = CommandRequest(command="check")
    second = CommandRequest(command="check")

    first.args.append("now")

    assert second.args == []
    assert CommandRequest(command="check", args=None).args == []


def test_tiny_nonzero_chart_value_renders_minimal_block():
    chart = ui_charts.render_chart([0.01, 1.0], width=2, height=2)

    assert chart.splitlines()[-1][0] == ui_charts.BAR_CHARS[1]


def test_web_models_security_singleton_uses_constant_name():
    assert SECURITY.auto_error is False


def test_plotext_chart_clears_figure_after_exception(monkeypatch):
    class RaisingPlotext:
        def __init__(self):
            self.clear_count = 0

        def clear_figure(self):
            self.clear_count += 1

        def plotsize(self, width, height):
            pass

        def bar(self, *args, **kwargs):
            raise RuntimeError("plot failed")

    fake_plotext = RaisingPlotext()
    monkeypatch.setattr(ui_charts, "plotext", fake_plotext)

    assert (
        ui_charts.render_plotext_bar_chart(
            [1.0],
            width=10,
            height=4,
            x_left="old",
            x_mid="mid",
            x_right="new",
        )
        == ""
    )
    assert fake_plotext.clear_count == 2


def test_sanitize_filename_output_matches_stored_name_validator(tmp_path):
    storage = _storage(tmp_path)

    assert storage.sanitize_filename("résumé.pdf") == "resume.pdf"
    assert storage.sanitize_filename("日本語.txt") == "upload.txt"
    for raw_name in ("résumé.pdf", "quote?.txt", "Release Notes (final).txt"):
        sanitized = storage.sanitize_filename(raw_name)
        assert storage.is_valid_stored_name(sanitized)


def test_save_uploaded_file_stages_payload_and_metadata(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    original_stage = WebFileStorage._stage_atomic_file
    staged_names: list[str] = []

    def recording_stage(path: Path, content: bytes) -> Path:
        staged_names.append(path.name)
        return original_stage(path, content)

    monkeypatch.setattr(
        WebFileStorage,
        "_stage_atomic_file",
        staticmethod(recording_stage),
    )

    entry = storage.save_uploaded_file(
        "atomic.txt",
        b"payload",
        content_type="text/plain",
    )

    assert entry.stored_name == "atomic.txt"
    assert staged_names == ["atomic.txt", ".atomic.txt.meta.json"]
    assert storage.get_file_path("atomic.txt").read_bytes() == b"payload"
    assert storage.metadata_path(storage.get_file_path("atomic.txt")).is_file()
