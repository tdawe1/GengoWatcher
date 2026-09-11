"""Tests for translate fan-out service ported from scripts/translate-gengo.sh."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from gengowatcher.orchestration.translate_fanout import (
    TranslateBusyError,
    TranslateFanoutService,
    build_review_prompt,
    build_translate_prompt,
    decode_file_bytes,
    is_skip_output,
    parse_models,
    truncate_preview,
)
from gengowatcher.web import WebAPI, app, authenticator
from gengowatcher.web_models import TranslateStartRequest


def _make_config(tmp_path: Path, overrides: dict | None = None):
    values = {
        ("TranslateFanout", "enabled"): True,
        ("TranslateFanout", "models"): "grok,opencode,codex,claude",
        ("TranslateFanout", "timeout_s"): 300,
        ("TranslateFanout", "out_dir"): str(tmp_path / "translate-fanout"),
        ("TranslateFanout", "max_chars"): 50000,
        ("TranslateFanout", "max_concurrency"): 2,
        ("TranslateFanout", "allow_binary"): False,
        ("TranslateFanout", "preview_chars"): 500,
        ("WebServer", "event_history_size"): 200,
        ("Webhooks", "max_seen_event_ids"): 1000,
    }
    if overrides:
        values.update(overrides)
    config = MagicMock()
    config.get.side_effect = lambda s, k, **kw: values.get((s, k), kw.get("fallback"))
    config.config = {"TranslateFanout": {}, "WebServer": {}}
    return config


def _make_service(tmp_path: Path, overrides: dict | None = None):
    config = _make_config(tmp_path, overrides)
    logger = logging.getLogger("test-translate")
    events: list[tuple[str, dict]] = []
    service = TranslateFanoutService(
        config,
        logger,
        file_storage=None,
        event_callback=lambda event_type, payload: events.append(
            (event_type, dict(payload))
        ),
    )
    return service, events


def test_parse_models_preserves_order_and_drops_unknowns():
    assert parse_models("opencode,claude,unknown,grok") == [
        "opencode",
        "claude",
        "grok",
    ]
    assert parse_models(["claude", "claude", "grok"]) == ["claude", "grok"]
    assert parse_models(None) == ["grok", "opencode", "codex", "claude"]
    assert parse_models("") == []


def test_truncate_preview_keeps_short_text():
    assert truncate_preview("hello", 500) == "hello"
    long_text = "x" * 600
    preview = truncate_preview(long_text, 500)
    assert len(preview) == 500
    assert preview.endswith("…")


def test_skip_detection_matches_bash_patterns():
    assert is_skip_output("Please run `grok login` to continue")
    assert is_skip_output("Status 402 Payment Required")
    assert is_skip_output("usage limit exhausted, upgrade to plus")
    assert is_skip_output("Failed to authenticate: OAuth expired")
    assert is_skip_output("ERROR 401 unauthorized")
    assert not is_skip_output("translated text looks fine")
    assert not is_skip_output("")


def test_prompts_preserve_gengo_style_guide_blocks():
    translate = build_translate_prompt("テスト", "text")
    assert "American spelling" in translate
    assert "[[[example]]]" in translate
    assert "テスト" in translate
    assert "Return ONLY the translation" in translate

    file_prompt = build_translate_prompt("テスト", "file")
    assert "completed translated file content" in file_prompt

    review = build_review_prompt("テスト", "test translation")
    assert "テスト" in review
    assert "test translation" in review
    assert "Return ONLY the revised final" in review


def test_decode_file_bytes_tries_utf8_first():
    assert decode_file_bytes("héllo".encode("utf-8"), 100) == "héllo"
    assert decode_file_bytes(b"\xff\xfe binary?", 100)


def test_start_run_requires_enabled(tmp_path):
    service, _ = _make_service(tmp_path, {("TranslateFanout", "enabled"): False})
    with pytest.raises(PermissionError, match="disabled"):
        service.start_run(text="hello")


def test_start_run_validates_exactly_one_input(tmp_path):
    service, _ = _make_service(tmp_path)
    with pytest.raises(ValueError, match="exactly one"):
        service.start_run(text="a", file_ref="b")
    with pytest.raises(ValueError, match="exactly one"):
        service.start_run()
    with pytest.raises(ValueError, match="must not be empty"):
        service.start_run(text="   ")


def test_start_run_rejects_oversize_and_unknown_models(tmp_path):
    service, _ = _make_service(tmp_path, {("TranslateFanout", "max_chars"): 5})
    with pytest.raises(ValueError, match="max_chars"):
        service.start_run(text="123456")
    with pytest.raises(ValueError, match="Unknown models"):
        service.start_run(text="hi", models="unknown-model")


def test_start_run_writes_run_dir_and_lists(tmp_path):
    service, events = _make_service(tmp_path)
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        run_id = service.start_run(text="こんにちは", models=["opencode"])

    assert run_id
    run_dir = tmp_path / "translate-fanout" / f"{run_id}-gengo"
    assert (run_dir / "original.txt").read_text(encoding="utf-8") == "こんにちは"
    assert (run_dir / "prompts" / "translate.prompt.txt").is_file()
    assert (run_dir / "run.json").is_file()
    run_data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_data["run_id"] == run_id
    assert "source_text" not in run_data  # full source stays in original.txt

    runs = service.list_runs()
    assert len(runs) == 1
    assert runs[0]["run_id"] == run_id
    assert runs[0]["char_count"] == len("こんにちは")
    assert runs[0]["finished"] is False

    detail = service.get_run(run_id)
    assert detail is not None
    assert detail["source_text"] == "こんにちは"  # retain-all: detail keeps full text

    assert events and events[0][0] == "translate.run.started"
    assert events[0][1]["run_id"] == run_id


def test_get_run_rejects_traversal(tmp_path):
    service, _ = _make_service(tmp_path)
    assert service.get_run("../config") is None
    assert service.get_run("") is None
    assert service.get_run("no-such-run") is None


def test_file_ref_requires_valid_storage_entry(tmp_path):
    storage = MagicMock()
    storage.is_valid_stored_name.return_value = False
    config = _make_config(tmp_path)
    service = TranslateFanoutService(
        config, logging.getLogger("test"), file_storage=storage
    )
    with pytest.raises(ValueError, match="Invalid file_ref"):
        service.start_run(file_ref="../escape")


def test_file_ref_reads_stored_file(tmp_path):
    storage_dir = tmp_path / "files"
    storage_dir.mkdir()
    stored = storage_dir / "note.txt"
    stored.write_text("ファイル内容", encoding="utf-8")
    storage = MagicMock()
    storage.is_valid_stored_name.side_effect = lambda name: name == "note.txt"
    storage.get_file_path.side_effect = lambda name: (
        stored if name == "note.txt" else None
    )
    storage.get_file_entry.return_value = MagicMock(original_name="orig.txt")

    config = _make_config(tmp_path)
    service = TranslateFanoutService(
        config, logging.getLogger("test"), file_storage=storage
    )
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        run_id = service.start_run(file_ref="note.txt", models="opencode")
    detail = service.get_run(run_id)
    assert detail is not None
    assert detail["kind"] == "file"
    assert detail["source_text"] == "ファイル内容"
    assert detail["original_name"] == "orig.txt"


def test_file_ref_rejects_binary_unless_allowed(tmp_path):
    storage_dir = tmp_path / "files"
    storage_dir.mkdir()
    stored = storage_dir / "blob.bin"
    stored.write_bytes(b"hello\x00world")
    storage = MagicMock()
    storage.is_valid_stored_name.return_value = True
    storage.get_file_path.return_value = stored
    storage.get_file_entry.return_value = None

    config = _make_config(tmp_path)
    service = TranslateFanoutService(
        config, logging.getLogger("test"), file_storage=storage
    )
    with pytest.raises(ValueError, match="Binary"):
        service.start_run(file_ref="blob.bin")


def test_run_one_model_marks_missing_binary_skipped(tmp_path):
    service, _ = _make_service(tmp_path)
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        run_id = service.start_run(text="hello", models=["grok"])
    asyncio.run(service._run_one_model(run_id, "grok", "hello", None, 5.0, True))
    detail = service.get_run(run_id)
    assert detail is not None
    assert detail["per_model"]["grok"]["status"] == "skipped"
    run_dir = tmp_path / "translate-fanout" / f"{run_id}-gengo"
    assert "SKIPPED" in (run_dir / "grok.final.txt").read_text(encoding="utf-8")


def test_run_one_model_ok_path_with_review(tmp_path):
    service, _ = _make_service(tmp_path)
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        run_id = service.start_run(text="テスト", models=["opencode"])
    calls = {"count": 0}

    async def fake_execute(argv, stdin_bytes, timeout_s):
        calls["count"] += 1
        if calls["count"] == 1:
            return 0, "translated text".encode(), b"", False
        return 0, "reviewed text".encode(), b"", False

    with patch.object(service, "_execute_phase", side_effect=fake_execute):
        asyncio.run(
            service._run_one_model(
                run_id, "opencode", "テスト", "/usr/bin/opencode", 5.0, True
            )
        )
    detail = service.get_run(run_id)
    assert detail is not None
    assert detail["per_model"]["opencode"]["status"] == "ok"
    assert detail["results"]["opencode"]["final"] == "reviewed text"
    assert detail["results"]["opencode"]["translation"] == "translated text"


def test_run_one_model_skips_on_auth_failure(tmp_path):
    service, _ = _make_service(tmp_path)
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        run_id = service.start_run(text="テスト", models=["claude"])
    fake = AsyncMock(return_value=(1, b"", b"Failed to authenticate", False))
    with patch.object(service, "_execute_phase", fake):
        asyncio.run(
            service._run_one_model(
                run_id, "claude", "テスト", "/usr/bin/claude", 5.0, True
            )
        )
    detail = service.get_run(run_id)
    assert detail is not None
    assert detail["per_model"]["claude"]["status"] == "skipped"
    assert "SKIPPED" in detail["results"]["claude"]["final"]


def test_translation_mentioning_quota_is_not_skipped(tmp_path):
    service, _ = _make_service(tmp_path)
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        run_id = service.start_run(text="テスト", models=["grok"], with_review=False)
    stdout = "The quarterly quota report shows billing increased.".encode()
    fake = AsyncMock(return_value=(0, stdout, b"", False))
    with patch.object(service, "_execute_phase", fake):
        asyncio.run(
            service._run_one_model(
                run_id, "grok", "テスト", "/usr/bin/grok", 5.0, False
            )
        )
    detail = service.get_run(run_id)
    assert detail is not None
    assert detail["per_model"]["grok"]["status"] == "ok"
    assert "quota" in detail["results"]["grok"]["final"]


def test_stdout_skip_pattern_with_nonzero_exit_still_skips(tmp_path):
    service, _ = _make_service(tmp_path)
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        run_id = service.start_run(text="テスト", models=["grok"], with_review=False)
    fake = AsyncMock(return_value=(1, b"quota exhausted", b"", False))
    with patch.object(service, "_execute_phase", fake):
        asyncio.run(
            service._run_one_model(
                run_id, "grok", "テスト", "/usr/bin/grok", 5.0, False
            )
        )
    detail = service.get_run(run_id)
    assert detail is not None
    assert detail["per_model"]["grok"]["status"] == "skipped"


def test_opencode_prompt_goes_through_stdin_not_argv(tmp_path):
    service, _ = _make_service(tmp_path)
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        run_id = service.start_run(text="テスト", models=["opencode"])
    run_dir = tmp_path / "translate-fanout" / f"{run_id}-gengo"
    argv, stdin_bytes = service._build_phase_argv(
        "opencode",
        "/usr/bin/opencode",
        run_dir / "prompts" / "translate.prompt.txt",
        run_dir,
        phase="translate",
    )
    assert argv == ["/usr/bin/opencode", "run"]
    assert stdin_bytes is not None
    assert "テスト" in stdin_bytes.decode("utf-8")


def test_start_run_rejects_when_max_active_runs_reached(tmp_path):
    service, _ = _make_service(tmp_path, {("TranslateFanout", "max_active_runs"): 1})
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        service.start_run(text="first", models=["opencode"])
        with pytest.raises(TranslateBusyError, match="Too many active"):
            service.start_run(text="second", models=["opencode"])


def test_disabled_service_does_not_create_out_dir(tmp_path):
    out_dir = tmp_path / "translate-fanout"
    _make_service(tmp_path, {("TranslateFanout", "enabled"): False})
    assert not out_dir.exists()


def test_run_one_model_marks_timeout_and_keeps_partial(tmp_path):
    service, _ = _make_service(tmp_path)
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        run_id = service.start_run(text="テスト", models=["grok"])
    fake = AsyncMock(return_value=(124, b"partial", b"", True))
    with patch.object(service, "_execute_phase", fake):
        asyncio.run(
            service._run_one_model(run_id, "grok", "テスト", "/usr/bin/grok", 5.0, True)
        )
    detail = service.get_run(run_id)
    assert detail is not None
    assert detail["per_model"]["grok"]["status"] == "skipped"


def test_run_one_model_fails_on_empty_output(tmp_path):
    service, _ = _make_service(tmp_path)
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        run_id = service.start_run(text="テスト", models=["grok"])
    fake = AsyncMock(return_value=(0, b"   ", b"", False))
    with patch.object(service, "_execute_phase", fake):
        asyncio.run(
            service._run_one_model(run_id, "grok", "テスト", "/usr/bin/grok", 5.0, True)
        )
    detail = service.get_run(run_id)
    assert detail is not None
    assert detail["per_model"]["grok"]["status"] == "failed"


def test_run_one_model_skips_review_when_disabled(tmp_path):
    service, _ = _make_service(tmp_path)
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        run_id = service.start_run(text="テスト", models=["grok"], with_review=False)
    fake = AsyncMock(return_value=(0, b"translated", b"", False))
    with patch.object(service, "_execute_phase", fake) as mocked:
        asyncio.run(
            service._run_one_model(
                run_id, "grok", "テスト", "/usr/bin/grok", 5.0, False
            )
        )
        assert mocked.await_count == 1
    detail = service.get_run(run_id)
    assert detail is not None
    assert detail["results"]["grok"]["final"] == "translated"


def _make_web_api(tmp_path, monkeypatch):
    import tempfile as tf

    config = MagicMock()
    out_dir = tmp_path / "translate-fanout"
    storage_dir = tmp_path / "files"
    storage_dir.mkdir(exist_ok=True)
    config.get.side_effect = lambda s, k, **kw: {
        ("TranslateFanout", "enabled"): True,
        ("TranslateFanout", "models"): "opencode",
        ("TranslateFanout", "timeout_s"): 300,
        ("TranslateFanout", "out_dir"): str(out_dir),
        ("TranslateFanout", "max_chars"): 50000,
        ("TranslateFanout", "max_concurrency"): 2,
        ("TranslateFanout", "allow_binary"): False,
        ("TranslateFanout", "preview_chars"): 500,
        ("Paths", "file_storage_dir"): str(storage_dir),
        ("WebServer", "auth_token"): "test-token",
    }.get((s, k), kw.get("fallback", ""))
    config.config = {"TranslateFanout": {}, "WebServer": {}}
    state = MagicMock()
    state.get_recent_jobs.return_value = []
    logger = logging.getLogger("test-web")
    watcher = MagicMock()
    watcher.start_time = time.time()
    watcher.websocket_status = "Live"
    watcher.rss_action = "Checking"
    watcher.last_check_time = time.time()
    watcher.next_check_time = time.time() + 60
    watcher.session_new_entries = 0
    watcher.session_total_value = 0.0
    watcher.failure_count = 0
    watcher.shutdown_event = MagicMock()
    watcher.shutdown_event.is_set.return_value = False
    watcher.PAUSE_FILE = f"{tf.gettempdir()}/test_pause_translate"
    watcher.get_cancellation_stats.return_value = {}
    with patch("gengowatcher.web.GengoWatcher", return_value=watcher):
        api = WebAPI(config, state, logger, watcher=watcher, start_watcher_thread=False)
    monkeypatch.setattr("gengowatcher.web.api_instance", api)
    return api


def test_webapi_start_list_get_round_trip(tmp_path, monkeypatch):
    api = _make_web_api(tmp_path, monkeypatch)
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        run_id = api.start_translate_run(
            TranslateStartRequest(text="こんにちは", models=["opencode"])
        )
    assert run_id
    summaries = api.list_translate_runs()
    assert len(summaries) == 1
    assert summaries[0].run_id == run_id
    detail = api.get_translate_run(run_id)
    assert detail is not None
    assert detail.source_text == "こんにちは"
    assert api.get_translate_run("missing") is None


def test_translate_endpoints_require_auth_and_validate(tmp_path, monkeypatch):
    _make_web_api(tmp_path, monkeypatch)
    client = TestClient(app)

    response = client.post("/api/translate", json={"text": "hello"})
    assert response.status_code == 401

    headers = {"Authorization": f"Bearer {authenticator.get_api_key()}"}
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        created = client.post("/api/translate", json={"text": "hello"}, headers=headers)
    assert created.status_code == 202
    run_id = created.json()["run_id"]

    listed = client.get("/api/translate", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()["runs"]) == 1

    detail = client.get(f"/api/translate/{run_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["source_text"] == "hello"

    missing = client.get("/api/translate/nope", headers=headers)
    assert missing.status_code == 404

    bad = client.post(
        "/api/translate",
        json={"text": "hi", "models": ["unknown"]},
        headers=headers,
    )
    assert bad.status_code == 422

    both = client.post(
        "/api/translate",
        json={"text": "hi", "file_ref": "note.txt"},
        headers=headers,
    )
    assert both.status_code == 400


def test_translate_start_returns_403_when_disabled(tmp_path, monkeypatch):
    api = _make_web_api(tmp_path, monkeypatch)
    api.translate_fanout.config.get.side_effect = lambda s, k, **kw: {
        ("TranslateFanout", "enabled"): False,
    }.get((s, k), kw.get("fallback", ""))
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {authenticator.get_api_key()}"}
    response = client.post("/api/translate", json={"text": "hello"}, headers=headers)
    assert response.status_code == 403


def test_translate_start_returns_429_when_busy(tmp_path, monkeypatch):
    api = _make_web_api(tmp_path, monkeypatch)
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        with patch.object(api.translate_fanout, "_max_active_runs", return_value=1):
            api.start_translate_run(
                TranslateStartRequest(text="first", models=["opencode"])
            )
            client = TestClient(app)
            headers = {"Authorization": f"Bearer {authenticator.get_api_key()}"}
            response = client.post(
                "/api/translate", json={"text": "second"}, headers=headers
            )
    assert response.status_code == 429


def test_existing_runs_are_reloaded_from_disk(tmp_path):
    service, _ = _make_service(tmp_path)
    with patch.object(
        TranslateFanoutService, "_background_entry", lambda self, run_id: None
    ):
        run_id = service.start_run(text="retain me", models=["opencode"])
    # New instance over the same out_dir must see the retained run (no GC).
    reloaded, _ = _make_service(tmp_path)
    assert reloaded.get_run(run_id) is not None
    assert len(reloaded.list_runs()) == 1
