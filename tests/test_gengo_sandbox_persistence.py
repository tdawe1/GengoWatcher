from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from unittest.mock import patch

import pytest

from gengowatcher.gengo_sandbox.persistence import (
    AtomicJSONStore,
    DOCUMENT_FORMAT,
    MAX_DOCUMENT_BYTES,
    SandboxDocumentError,
    SandboxStoreLockedError,
    build_scenario_document,
    build_snapshot_document,
    decode_document,
    encode_document,
    scenario_digest,
    validate_document,
    validate_payload,
)


def payload(collections: list[dict] | None = None) -> dict:
    return {
        "collections": collections or [],
        "suggestion_flags": [],
        "next_suggestion_flag_id": 1,
    }


def full_collection() -> dict:
    return {
        "collection_id": 10,
        "job_id": 20,
        "order_id": 30,
        "customer_id": 40,
        "source": "現代ロシア — café",
        "purpose": "Generic Content",
        "reward": 1.25,
        "unit_count": 4,
        "comment": "顧客 comment",
        "comment_id": 50,
        "comment_time": "2026-01-01T00:00:00Z",
        "status": "incomplete",
        "target_content": "A translation",
        "started_at": 1000.5,
        "allotted_seconds": 3600,
        "translator_id": 60,
        "flag_id": 2,
        "has_flag": True,
        "segment_states": [{"segment_id": "20", "is_edited": True}],
        "job_activities": [{"id": 1, "body": "note"}],
        "glossary_entries": [{"term": "家", "translations": []}],
        "tm_matches": [{"score": 95, "target": "house"}],
        "mt_translation": "machine translation",
        "source_files": [
            {
                "filename": "source.txt",
                "content_type": "text/plain",
                "content_text": "こんにちは",
            }
        ],
        "target_files": [
            {
                "filename": "target.bin",
                "content_type": "application/octet-stream",
                "content_base64": "AAEC",
            }
        ],
    }


def test_scenario_and_snapshot_round_trip_all_supported_fields() -> None:
    baseline = payload([full_collection()])
    scenario = build_scenario_document(baseline)
    assert scenario["format"] == DOCUMENT_FORMAT
    assert validate_document(scenario) == scenario
    assert decode_document(encode_document(scenario)) == scenario

    current = payload([full_collection()])
    current["suggestion_flags"] = [{"id": 4, "payload": {"text": "日本語"}}]
    current["next_suggestion_flag_id"] = 5
    snapshot = build_snapshot_document(baseline, current)
    assert decode_document(encode_document(snapshot)) == snapshot


def test_digest_is_deterministic_but_sensitive_to_collection_order() -> None:
    first = payload([{"collection_id": 1}, {"collection_id": 2}])
    reordered_keys = {
        "next_suggestion_flag_id": 1,
        "suggestion_flags": [],
        "collections": [{"collection_id": 1}, {"collection_id": 2}],
    }
    reversed_collections = payload([{"collection_id": 2}, {"collection_id": 1}])
    assert scenario_digest(first) == scenario_digest(reordered_keys)
    assert scenario_digest(first) != scenario_digest(reversed_collections)


@pytest.mark.parametrize(
    "change, match",
    [
        (lambda doc: doc.update(schema_version=99), "unsupported version"),
        (lambda doc: doc.update(extra=True), "unknown field"),
        (lambda doc: doc.update(scenario_digest="bad"), "does not match"),
        (lambda doc: doc.update(document_type="other"), "scenario or snapshot"),
    ],
)
def test_document_rejects_future_unknown_corrupt_metadata(change, match: str) -> None:
    document = build_scenario_document(payload())
    change(document)
    with pytest.raises(SandboxDocumentError, match=match):
        validate_document(document)


@pytest.mark.parametrize(
    "collections, match",
    [
        ([{"collection_id": True}], "must be an integer"),
        (
            [{"collection_id": 1}, {"collection_id": 1}],
            "duplicate collection_id",
        ),
        (
            [{"collection_id": 1, "job_id": 7}, {"collection_id": 2, "job_id": 7}],
            "duplicate job_id",
        ),
        (
            [
                {"collection_id": 1, "order_id": 8},
                {"collection_id": 2, "order_id": 8},
            ],
            "duplicate order_id",
        ),
        ([{"collection_id": 1, "status": "mystery"}], "unsupported value"),
        (
            [
                {
                    "collection_id": 1,
                    "status": "incomplete",
                    "allotted_seconds": 5,
                    "countdown_seconds_left": 6,
                }
            ],
            "exceeds allotted",
        ),
        ([{"collection_id": 1, "segment_states": {}}], "must be a list"),
        (
            [
                {
                    "collection_id": 1,
                    "source_files": [
                        {
                            "filename": "x",
                            "content_type": "text/plain",
                            "content_text": "x",
                            "content_base64": "eA==",
                        }
                    ],
                }
            ],
            "exactly one",
        ),
    ],
)
def test_payload_rejects_invalid_collections(collections, match: str) -> None:
    with pytest.raises(SandboxDocumentError, match=match):
        validate_payload(payload(collections))


def test_payload_rejects_invalid_suggestion_flag_counter() -> None:
    value = payload()
    value["suggestion_flags"] = [{"id": 2, "payload": {}}]
    value["next_suggestion_flag_id"] = 2
    with pytest.raises(SandboxDocumentError, match="greater than every"):
        validate_payload(value)


@pytest.mark.parametrize(
    "raw, match",
    [
        (b"{not-json", "not valid JSON"),
        (b"\xff", "not valid UTF-8"),
        (b'{"x":NaN}', "invalid numeric constant"),
        (b'{"x":Infinity}', "invalid numeric constant"),
        (b'{"x":1,"x":2}', "duplicate JSON key"),
    ],
)
def test_decode_rejects_corruption_nonfinite_and_duplicate_keys(
    raw: bytes, match: str
) -> None:
    with pytest.raises(SandboxDocumentError, match=match):
        decode_document(raw)


def test_atomic_store_unicode_permissions_and_load(tmp_path: Path) -> None:
    path = tmp_path / "sandbox.json"
    document = build_scenario_document(payload([full_collection()]))
    with AtomicJSONStore(path) as store:
        store.write(document)
        assert store.load() == document
    assert "現代ロシア" in path.read_text(encoding="utf-8")
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_atomic_replace_failure_preserves_previous_file_and_cleans_temp(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sandbox.json"
    first = build_scenario_document(payload([{"collection_id": 1}]))
    second = build_scenario_document(payload([{"collection_id": 2}]))
    with AtomicJSONStore(path) as store:
        store.write(first)
        original = path.read_bytes()
        with patch(
            "gengowatcher.gengo_sandbox.persistence.os.replace",
            side_effect=OSError("replace failed"),
        ):
            with pytest.raises(OSError, match="replace failed"):
                store.write(second)
        assert path.read_bytes() == original
        assert list(tmp_path.glob(".sandbox.json.*.tmp")) == []


def test_lifetime_sidecar_lock_excludes_second_store(tmp_path: Path) -> None:
    path = tmp_path / "sandbox.json"
    first = AtomicJSONStore(path)
    try:
        with pytest.raises(SandboxStoreLockedError, match="already locked"):
            AtomicJSONStore(path)
    finally:
        first.close()
    with AtomicJSONStore(path):
        pass


def test_closed_store_rejects_operations(tmp_path: Path) -> None:
    store = AtomicJSONStore(tmp_path / "sandbox.json")
    store.close()
    store.close()
    with pytest.raises(RuntimeError, match="closed"):
        store.write(build_scenario_document(payload()))


def test_size_limit_is_enforced_for_decode_and_encode() -> None:
    with pytest.raises(SandboxDocumentError, match="size limit"):
        decode_document(b" " * (MAX_DOCUMENT_BYTES + 1))
    document = build_scenario_document(
        payload([{"collection_id": 1, "source": "x" * MAX_DOCUMENT_BYTES}])
    )
    with pytest.raises(SandboxDocumentError, match="size limit"):
        encode_document(document)


def test_load_failure_does_not_modify_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "sandbox.json"
    raw = b"not valid JSON"
    path.write_bytes(raw)
    with AtomicJSONStore(path) as store:
        with pytest.raises(SandboxDocumentError, match="not valid JSON"):
            store.load()
    assert path.read_bytes() == raw


def test_snapshot_requires_state_and_scenario_forbids_it() -> None:
    scenario = build_scenario_document(payload())
    scenario["state"] = payload()
    with pytest.raises(SandboxDocumentError, match="unknown field"):
        validate_document(scenario)

    snapshot = {
        key: value
        for key, value in build_snapshot_document(payload(), payload()).items()
        if key != "state"
    }
    with pytest.raises(SandboxDocumentError, match="missing field"):
        validate_document(snapshot)


def test_json_file_is_interoperable_with_standard_decoder(tmp_path: Path) -> None:
    path = tmp_path / "sandbox.json"
    document = build_snapshot_document(payload(), payload())
    with AtomicJSONStore(path) as store:
        store.write(document)
    assert json.loads(path.read_text(encoding="utf-8")) == document
