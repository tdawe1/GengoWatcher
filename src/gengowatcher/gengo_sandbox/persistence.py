"""Versioned JSON persistence primitives for the local Gengo sandbox.

This module deliberately has no dependency on :mod:`gengo_sandbox.app`.  It
validates plain dictionaries so the runtime can adopt persistence without a
serialization/import cycle.
"""

from __future__ import annotations

import base64
import binascii
import copy
import functools
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Callable, TypeVar

try:  # pragma: no cover - platform dependent
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:  # pragma: no cover - platform dependent
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None


DOCUMENT_FORMAT = "gengowatcher.gengo-sandbox"
SCHEMA_VERSION = 1
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_SANDBOX_FILE_BYTES = 2 * 1024 * 1024
MAX_SANDBOX_FILENAME_BYTES = 255

_PAYLOAD_FIELDS = {
    "collections",
    "suggestion_flags",
    "next_suggestion_flag_id",
}
_COLLECTION_FIELDS = {
    "collection_id",
    "job_id",
    "order_id",
    "customer_id",
    "source",
    "purpose",
    "reward",
    "unit_count",
    "comment",
    "comment_id",
    "comment_time",
    "status",
    "target_content",
    "started_at",
    "countdown_seconds_left",
    "allotted_seconds",
    "translator_id",
    "flag_id",
    "has_flag",
    "segment_states",
    "job_activities",
    "glossary_entries",
    "tm_matches",
    "mt_translation",
    # File fixtures contain JSON-safe metadata and encoded/text content only.
    "source_files",
    "target_files",
}
_COLLECTION_LIST_FIELDS = {
    "segment_states",
    "job_activities",
    "glossary_entries",
    "tm_matches",
}
_FILE_FIELDS = {"source_files", "target_files"}
_FILE_FIXTURE_FIELDS = {
    "filename",
    "content_type",
    "content_base64",
    "content_text",
}
_VALID_STATUSES = {"available", "incomplete", "reviewable", "complete", "declined"}


def sanitize_file_filename(value: Any) -> str:
    """Validate and canonicalize a fixture filename for runtime downloads."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("file filename is required")
    if len(value.encode("utf-8")) > MAX_SANDBOX_FILENAME_BYTES:
        raise ValueError("file filename is too long")
    basename = value.replace("\\", "/").rsplit("/", 1)[-1]
    basename = re.sub(r"[\x00-\x1f\x7f]+", "", basename)
    basename = re.sub(r"[^A-Za-z0-9_ .()\-]+", "_", basename)
    while ".." in basename:
        basename = basename.replace("..", ".")
    basename = basename.strip(" .-_")
    if not basename:
        raise ValueError("file filename has no safe basename")
    return basename


class SandboxDocumentError(ValueError):
    """Raised when a sandbox scenario or snapshot is invalid."""


class SandboxStoreLockedError(RuntimeError):
    """Raised when another store already owns a state file's sidecar lock."""


_PublicResult = TypeVar("_PublicResult")


def _normalize_recursion_error(
    function: Callable[..., _PublicResult],
) -> Callable[..., _PublicResult]:
    """Expose excessive nesting as the module's documented validation error."""

    @functools.wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> _PublicResult:
        try:
            return function(*args, **kwargs)
        except RecursionError as exc:
            raise SandboxDocumentError("document nesting is too deep") from exc

    return wrapped


def _fail(path: str, message: str) -> None:
    raise SandboxDocumentError(f"{path}: {message}")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_int(value: Any, path: str, *, minimum: int | None = None) -> int:
    if not _is_int(value):
        _fail(path, "must be an integer")
    if minimum is not None and value < minimum:
        _fail(path, f"must be at least {minimum}")
    return value


def _require_number(value: Any, path: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "must be a number")
    number = float(value)
    if not math.isfinite(number):
        _fail(path, "must be finite")
    if minimum is not None and number < minimum:
        _fail(path, f"must be at least {minimum}")
    return number


def _require_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(path, "must be an object")
    if any(not isinstance(key, str) for key in value):
        _fail(path, "object keys must be strings")
    return value


def _check_fields(
    value: dict[str, Any],
    path: str,
    *,
    allowed: set[str],
    required: set[str] = frozenset(),
) -> None:
    unknown = set(value) - allowed
    if unknown:
        _fail(path, f"unknown field(s): {', '.join(sorted(unknown))}")
    missing = required - set(value)
    if missing:
        _fail(path, f"missing field(s): {', '.join(sorted(missing))}")


def _validate_json_value(value: Any, path: str) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if _is_int(value):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(path, "must be finite")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            _fail(path, "object keys must be strings")
        for key, item in value.items():
            _validate_json_value(item, f"{path}.{key}")
        return
    _fail(path, f"unsupported JSON value {type(value).__name__}")


def _validate_object_list(value: Any, path: str) -> None:
    if not isinstance(value, list):
        _fail(path, "must be a list")
    for index, item in enumerate(value):
        _require_object(item, f"{path}[{index}]")
        _validate_json_value(item, f"{path}[{index}]")


def _validate_file_fixtures(value: Any, path: str) -> None:
    if not isinstance(value, list):
        _fail(path, "must be a list")
    if len(value) > 1:
        _fail(path, "supports at most one file fixture")
    for index, raw_fixture in enumerate(value):
        item_path = f"{path}[{index}]"
        fixture = _require_object(raw_fixture, item_path)
        _check_fields(
            fixture,
            item_path,
            allowed=_FILE_FIXTURE_FIELDS,
            required={"filename", "content_type"},
        )
        for key in ("filename", "content_type"):
            if not isinstance(fixture[key], str):
                _fail(f"{item_path}.{key}", "must be a string")
        try:
            sanitize_file_filename(fixture["filename"])
        except ValueError as exc:
            _fail(f"{item_path}.filename", str(exc))
        if (
            not fixture["content_type"].strip()
            or len(fixture["content_type"]) > 127
            or any(
                ord(char) < 32 or ord(char) == 127 for char in fixture["content_type"]
            )
        ):
            _fail(f"{item_path}.content_type", "is invalid")
        content_fields = {
            key for key in ("content_base64", "content_text") if key in fixture
        }
        if len(content_fields) != 1:
            _fail(item_path, "must contain exactly one encoded or text content field")
        content_key = next(iter(content_fields))
        content = fixture[content_key]
        if not isinstance(content, str):
            _fail(f"{item_path}.{content_key}", "must be a string")
        if content_key == "content_text":
            size = len(content.encode("utf-8"))
        else:
            max_encoded_size = 4 * ((MAX_SANDBOX_FILE_BYTES + 2) // 3)
            if len(content) > max_encoded_size:
                _fail(item_path, "file fixture exceeds sandbox size limit")
            try:
                size = len(base64.b64decode(content, validate=True))
            except (binascii.Error, ValueError):
                _fail(f"{item_path}.content_base64", "is invalid")
        if size > MAX_SANDBOX_FILE_BYTES:
            _fail(item_path, "file fixture exceeds sandbox size limit")


@_normalize_recursion_error
def validate_collection(value: Any, *, path: str = "collection") -> dict[str, Any]:
    """Validate one collection fixture and return a deep copy."""

    return copy.deepcopy(_validate_collection(value, path))


def _validate_collection(value: Any, path: str) -> dict[str, Any]:
    collection = _require_object(value, path)
    _check_fields(
        collection,
        path,
        allowed=_COLLECTION_FIELDS,
        required={"collection_id"},
    )
    for key in ("collection_id", "job_id", "order_id"):
        if key in collection:
            _require_int(collection[key], f"{path}.{key}", minimum=1)
    for key in (
        "customer_id",
        "unit_count",
        "comment_id",
        "translator_id",
        "flag_id",
    ):
        if key in collection:
            _require_int(collection[key], f"{path}.{key}", minimum=0)
    if "reward" in collection:
        _require_number(collection["reward"], f"{path}.reward", minimum=0)
    for key in (
        "source",
        "purpose",
        "comment",
        "comment_time",
        "target_content",
        "mt_translation",
    ):
        if key in collection and not isinstance(collection[key], str):
            _fail(f"{path}.{key}", "must be a string")
    if "has_flag" in collection and not isinstance(collection["has_flag"], bool):
        _fail(f"{path}.has_flag", "must be a boolean")
    status = collection.get("status", "available")
    if not isinstance(status, str) or status not in _VALID_STATUSES:
        _fail(f"{path}.status", "has an unsupported value")
    allotted_seconds = _require_int(
        collection.get("allotted_seconds", 3600),
        f"{path}.allotted_seconds",
        minimum=1,
    )
    if "started_at" in collection and collection["started_at"] is not None:
        _require_number(collection["started_at"], f"{path}.started_at", minimum=0)
    if "countdown_seconds_left" in collection:
        countdown = _require_int(
            collection["countdown_seconds_left"],
            f"{path}.countdown_seconds_left",
            minimum=0,
        )
        if countdown > allotted_seconds:
            _fail(f"{path}.countdown_seconds_left", "exceeds allotted_seconds")
        if status != "incomplete":
            _fail(f"{path}.countdown_seconds_left", "requires incomplete status")
        if collection.get("started_at") is not None:
            _fail(path, "cannot contain both started_at and countdown_seconds_left")
    for key in _COLLECTION_LIST_FIELDS:
        if key in collection:
            _validate_object_list(collection[key], f"{path}.{key}")
    for key in _FILE_FIELDS:
        if key in collection:
            _validate_file_fixtures(collection[key], f"{path}.{key}")
    return collection


@_normalize_recursion_error
def validate_payload(value: Any, *, path: str = "payload") -> dict[str, Any]:
    """Validate one baseline/current-state payload and return a deep copy."""

    payload = _require_object(value, path)
    _check_fields(
        payload,
        path,
        allowed=_PAYLOAD_FIELDS,
        required=_PAYLOAD_FIELDS,
    )
    collections = payload["collections"]
    if not isinstance(collections, list):
        _fail(f"{path}.collections", "must be a list")
    seen: dict[str, set[int]] = {
        "collection_id": set(),
        "job_id": set(),
        "order_id": set(),
    }
    for index, raw_collection in enumerate(collections):
        collection_path = f"{path}.collections[{index}]"
        collection = _validate_collection(raw_collection, collection_path)
        collection_id = collection["collection_id"]
        effective_ids = {
            "collection_id": collection_id,
            "job_id": collection.get("job_id", collection_id),
            "order_id": collection.get("order_id", collection_id),
        }
        for key, identifier in effective_ids.items():
            if identifier in seen[key]:
                _fail(f"{collection_path}.{key}", f"duplicate {key} {identifier}")
            seen[key].add(identifier)

    flags = payload["suggestion_flags"]
    if not isinstance(flags, list):
        _fail(f"{path}.suggestion_flags", "must be a list")
    flag_ids: set[int] = set()
    for index, raw_flag in enumerate(flags):
        flag_path = f"{path}.suggestion_flags[{index}]"
        flag = _require_object(raw_flag, flag_path)
        _check_fields(
            flag, flag_path, allowed={"id", "payload"}, required={"id", "payload"}
        )
        flag_id = _require_int(flag["id"], f"{flag_path}.id", minimum=1)
        if flag_id in flag_ids:
            _fail(f"{flag_path}.id", f"duplicate suggestion flag id {flag_id}")
        flag_ids.add(flag_id)
        _require_object(flag["payload"], f"{flag_path}.payload")
        _validate_json_value(flag["payload"], f"{flag_path}.payload")
    next_flag_id = _require_int(
        payload["next_suggestion_flag_id"],
        f"{path}.next_suggestion_flag_id",
        minimum=1,
    )
    if flag_ids and next_flag_id <= max(flag_ids):
        _fail(
            f"{path}.next_suggestion_flag_id",
            "must be greater than every existing suggestion flag id",
        )
    return copy.deepcopy(payload)


def scenario_digest(baseline: dict[str, Any]) -> str:
    """Return the stable SHA-256 digest of a validated scenario baseline."""

    validated = validate_payload(baseline, path="baseline")
    encoded = json.dumps(
        validated,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_scenario_document(baseline: dict[str, Any]) -> dict[str, Any]:
    """Build a validated version-one scenario document."""

    validated = validate_payload(baseline, path="baseline")
    return {
        "format": DOCUMENT_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "document_type": "scenario",
        "scenario_digest": scenario_digest(validated),
        "baseline": validated,
    }


def build_snapshot_document(
    baseline: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Build a validated version-one runtime snapshot document."""

    validated_baseline = validate_payload(baseline, path="baseline")
    validated_state = validate_payload(state, path="state")
    return {
        "format": DOCUMENT_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "document_type": "snapshot",
        "scenario_digest": scenario_digest(validated_baseline),
        "baseline": validated_baseline,
        "state": validated_state,
    }


@_normalize_recursion_error
def validate_document(value: Any) -> dict[str, Any]:
    """Strictly validate and copy a scenario or snapshot document."""

    document = _require_object(value, "document")
    document_type = document.get("document_type")
    allowed = {
        "format",
        "schema_version",
        "document_type",
        "scenario_digest",
        "baseline",
    }
    required = set(allowed)
    if document_type == "snapshot":
        allowed.add("state")
        required.add("state")
    elif document_type != "scenario":
        _fail("document.document_type", "must be scenario or snapshot")
    _check_fields(document, "document", allowed=allowed, required=required)
    if document["format"] != DOCUMENT_FORMAT:
        _fail("document.format", "is not a Gengo sandbox document")
    if not _is_int(document["schema_version"]):
        _fail("document.schema_version", "must be an integer")
    if document["schema_version"] != SCHEMA_VERSION:
        _fail(
            "document.schema_version",
            f"unsupported version {document['schema_version']!r}",
        )
    if not isinstance(document["scenario_digest"], str):
        _fail("document.scenario_digest", "must be a string")
    baseline = validate_payload(document["baseline"], path="document.baseline")
    expected_digest = scenario_digest(baseline)
    if document["scenario_digest"] != expected_digest:
        _fail("document.scenario_digest", "does not match the baseline")
    if document_type == "snapshot":
        validate_payload(document["state"], path="document.state")
    return copy.deepcopy(document)


def _reject_json_constant(value: str) -> None:
    raise SandboxDocumentError(f"document: invalid numeric constant {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise SandboxDocumentError(f"document: duplicate JSON key {key!r}")
        value[key] = item
    return value


def decode_document(data: bytes) -> dict[str, Any]:
    """Decode strict UTF-8/JSON bytes and validate the resulting document."""

    if len(data) > MAX_DOCUMENT_BYTES:
        raise SandboxDocumentError(
            f"document exceeds {MAX_DOCUMENT_BYTES} byte size limit"
        )
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SandboxDocumentError(f"document is not valid UTF-8: {exc}") from exc
    try:
        value = json.loads(
            text,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except SandboxDocumentError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise SandboxDocumentError(f"document is not valid JSON: {exc}") from exc
    try:
        return validate_document(value)
    except RecursionError as exc:
        raise SandboxDocumentError("document nesting is too deep") from exc


def encode_document(value: dict[str, Any]) -> bytes:
    """Validate and encode a document deterministically as UTF-8 JSON."""

    validated = validate_document(value)
    try:
        data = (
            json.dumps(
                validated,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise SandboxDocumentError(f"document cannot be encoded: {exc}") from exc
    if len(data) > MAX_DOCUMENT_BYTES:
        raise SandboxDocumentError(
            f"document exceeds {MAX_DOCUMENT_BYTES} byte size limit"
        )
    return data


class AtomicJSONStore:
    """Exclusively locked, atomic storage for validated sandbox documents."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        self._lock_file: Any | None = None
        self._closed = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()

    def _acquire_lock(self) -> None:
        lock_file = self.lock_path.open("a+b")
        try:
            os.chmod(self.lock_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        try:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif msvcrt is not None and sys.platform == "win32":  # pragma: no cover
                if self.lock_path.stat().st_size == 0:
                    lock_file.write(b"\0")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover - unsupported Python platform
                raise SandboxStoreLockedError(
                    "no supported advisory file-lock implementation"
                )
        except (OSError, SandboxStoreLockedError) as exc:
            lock_file.close()
            if isinstance(exc, SandboxStoreLockedError):
                raise
            raise SandboxStoreLockedError(
                f"sandbox state file is already locked: {self.path}"
            ) from exc
        self._lock_file = lock_file

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("sandbox JSON store is closed")

    def load(self) -> dict[str, Any]:
        """Load and validate the current document."""

        self._require_open()
        try:
            with self.path.open("rb") as handle:
                data = handle.read(MAX_DOCUMENT_BYTES + 1)
        except OSError as exc:
            raise SandboxDocumentError(f"cannot read {self.path}: {exc}") from exc
        if len(data) > MAX_DOCUMENT_BYTES:
            raise SandboxDocumentError(
                f"document exceeds {MAX_DOCUMENT_BYTES} byte size limit"
            )
        return decode_document(data)

    def write(self, document: dict[str, Any]) -> None:
        """Atomically replace the file with a validated document."""

        self._require_open()
        data = encode_document(document)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(data)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(temp_path, self.path)
            temp_path = None
            self._fsync_parent_directory()
        except Exception:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
            raise

    def _fsync_parent_directory(self) -> None:
        if os.name != "posix":  # pragma: no cover - Windows
            return
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        try:
            directory_fd = os.open(self.path.parent, flags)
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        except OSError:
            pass
        finally:
            os.close(directory_fd)

    def close(self) -> None:
        """Release the lifetime sidecar lock."""

        if self._closed:
            return
        lock_file = self._lock_file
        self._lock_file = None
        self._closed = True
        if lock_file is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None and sys.platform == "win32":  # pragma: no cover
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            lock_file.close()

    def __enter__(self) -> "AtomicJSONStore":
        self._require_open()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


DocumentValidator = Callable[[Any], dict[str, Any]]
