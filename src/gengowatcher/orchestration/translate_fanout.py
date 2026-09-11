"""Translate fan-out orchestration ported from scripts/translate-gengo.sh.

Python owns subprocess orchestration; the Rust TUI is a loopback API
consumer and must never shell out to LLM CLIs directly.

Fan-out: translate per Gengo Style Guide, then an optional review pass,
one directory per run under ``data/translate-fanout/<run-id>/`` with
``*.translation.txt``, ``*.review.txt``, ``*.final.txt``, ``*.status``,
``COMBINED.md``. Missing binary / auth / quota / timeout records
``SKIPPED`` and continues instead of failing hard.

Retention: all runs are retained (no GC). List summaries carry a truncated
``input_preview``; detail reads the full retained source from disk.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

SUPPORTED_MODELS = ("grok", "opencode", "codex", "claude")
DEFAULT_MODELS_STR = "grok,opencode,codex,claude"

TRANSLATE_INSTRUCTIONS = """You are a professional Japanese-to-English translator following the Gengo.com Style Guide (American English).
MUST follow:
- American spelling (Gengo default).
- Numbers 0-9 spelled out; larger than 9 numeric; comma as thousands separator (3,000); over one million shortened ($3.5 billion). If numbers both smaller and larger than 9 are in the SAME sentence, use numeric for all.
- Dates as Month Dayth, Year with ordinal suffix and comma after day (June 7th, 2010). Time 12-hour (3:00 p.m.).
- Oxford/serial comma (bananas, apples, and oranges).
- Headlines: capitalize only first letter, except proper nouns.
- Double quotation marks (" ") for quotes; single only for quotes-within-quotes. Periods/commas inside closing quotes; colons/semicolons outside.
- Avoid contractions in formal writing (cannot not can't; Street not St.; It is not it's).
- Avoid hyphenating nouns (eye shadow, breakdown); hyphen only to clarify meaning (man-eating shark).
- Triple brackets [[[example]]] are DO-NOT-TRANSLATE: copy EXACTLY including brackets, never translate inside, never drop brackets.
- Preserve structure: same paragraph breaks/line breaks as source. Do not turn a list into a paragraph or vice versa. Use appropriate English punctuation, do not copy Japanese punctuation blindly.
- En dash (-) for ranges (Ages 18-21), em dash (—) for abrupt break.
- Accurately reflect meaning and style (formal/informal) of source."""

REVIEW_INSTRUCTION = (
    "You are a professional editor. Review the translation for naturalness "
    "whilst still ensuring Gengo.com Style Guide compliance (American spelling, "
    "numbers 0-9 spelled out unless mixed with larger numbers in same sentence, "
    "dates Month Dayth, Year, Oxford comma, headline capitalize only first letter, "
    "double quotes with periods inside, no contractions in formal text, "
    "triple brackets [[[x]]] preserved exactly, paragraph/line breaks match "
    "original, en dash for ranges)."
)

# Ported from is_auth_or_quota_failure() in scripts/translate-gengo.sh.
_SKIP_PATTERN = (
    r"not logged in|not signed in|please run .*login|failed to authenticate|"
    r"oauth .*expired|invalid.*api.?key|no api key|api key.*missing|"
    r"payment required|status 402|usage balance exhausted|usage limit|"
    r"upgrade to plus|quota|credit.*exhaust|subscription.*not active|"
    r"no .*subscription|billing|unauthorized| 401 | 403 |forbidden|"
    r"access denied|CMPUnknownError|error.*auth"
)
SKIP_RE = re.compile(_SKIP_PATTERN, re.IGNORECASE)

RUN_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")
SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

EventCallback = Callable[[str, Mapping[str, Any]], None]


def parse_models(value: Any, fallback: str = DEFAULT_MODELS_STR) -> list[str]:
    """Parse a model allowlist, preserving order and dropping unknowns."""
    if value is None:
        value = fallback
    if isinstance(value, str):
        candidates = [item.strip().lower() for item in value.split(",")]
    elif isinstance(value, (list, tuple)):
        candidates = [str(item).strip().lower() for item in value]
    else:
        candidates = []
    seen: set[str] = set()
    models: list[str] = []
    for candidate in candidates:
        if candidate in SUPPORTED_MODELS and candidate not in seen:
            seen.add(candidate)
            models.append(candidate)
    return models


def truncate_preview(text: str, limit: int = 500) -> str:
    """Truncate long source text for list summaries (detail keeps full text)."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def source_hash_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def is_skip_output(combined_output: str) -> bool:
    """Detect auth/quota/subscription failures that should SKIP, not fail."""
    if not combined_output:
        return False
    return SKIP_RE.search(combined_output) is not None


def contains_binary(content: bytes) -> bool:
    return b"\x00" in content


def decode_file_bytes(content: bytes, max_chars: int) -> str:
    """Decode uploaded/stored file bytes the same way as the workflow path."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)[:max_chars]
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")[:max_chars]


def build_translate_prompt(source_content: str, kind: str) -> str:
    if kind == "file":
        task = (
            "Task: Translate the file below (return the completed translated "
            "file content, same formatting/line breaks/paragraphs as the "
            "original) to English per above. Return ONLY the translation, "
            "no explanations, no notes."
        )
    else:
        task = (
            "Task: Translate the text below (return the completed translation, "
            "same formatting/line breaks as the original) to English per above. "
            "Return ONLY the translation, no explanations, no notes."
        )
    return (
        f"{TRANSLATE_INSTRUCTIONS}\n\n{task}\n"
        f"---SOURCE START---\n{source_content}\n---SOURCE END---\n"
    )


def build_review_prompt(source_content: str, translation: str) -> str:
    return (
        f"{REVIEW_INSTRUCTION}\n\nOriginal source (Japanese):\n"
        f"---SOURCE START---\n{source_content}\n---SOURCE END---\n\n"
        f"Current translation to review:\n---TRANSLATION START---\n{translation}\n"
        f"---TRANSLATION END---\n\nTask: Return ONLY the revised final "
        f"translation (same formatting/line breaks as original), no explanations. "
        f"If already perfect, return it unchanged.\n"
    )


def utc_run_id() -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


@dataclass
class PerModelState:
    status: str = "queued"
    bytes: int = 0
    ms: int = 0
    error: str = ""


@dataclass
class TranslateRunRecord:
    run_id: str
    kind: str
    char_count: int
    source_hash: str
    original_name: str = ""
    with_review: bool = True
    models: list[str] = field(default_factory=list)
    created_at: float = 0.0
    finished_at: float | None = None
    per_model: dict[str, PerModelState] = field(default_factory=dict)
    input_preview: str = ""

    def to_summary(self, include_text: bool = False) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "run_id": self.run_id,
            "kind": self.kind,
            "char_count": self.char_count,
            "with_review": self.with_review,
            "models": list(self.models),
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "finished": self.finished_at is not None,
            "per_model": {
                name: {
                    "status": state.status,
                    "bytes": state.bytes,
                    "ms": state.ms,
                    "error": state.error,
                }
                for name, state in self.per_model.items()
            },
            "input_preview": self.input_preview,
        }
        if include_text:
            summary["input_preview"] = self.input_preview
        return summary


class TranslateFanoutService:
    """Owns translate fan-out runs: validation, persistence, subprocess."""

    def __init__(
        self,
        config: Any,
        logger: logging.Logger,
        file_storage: Any | None = None,
        event_callback: EventCallback | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.file_storage = file_storage
        self._event_callback = event_callback
        self._lock = threading.RLock()
        self._runs: dict[str, TranslateRunRecord] = {}
        self._out_dir = self._resolve_out_dir()
        self._out_dir.mkdir(parents=True, exist_ok=True)
        self._load_existing_runs()

    # -- config ---------------------------------------------------------

    def _cfg(self, key: str, fallback: Any) -> Any:
        getter = getattr(self.config, "get", None)
        if not callable(getter):
            return fallback
        try:
            value = getter("TranslateFanout", key, fallback=fallback)
        except TypeError:
            try:
                value = getter("TranslateFanout", key)
            except Exception:
                return fallback
        return fallback if value is None else value

    def is_enabled(self) -> bool:
        value = self._cfg("enabled", False)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
        return False

    def _default_models(self) -> list[str]:
        raw = self._cfg("models", DEFAULT_MODELS_STR)
        models = parse_models(raw, fallback=DEFAULT_MODELS_STR)
        return models or list(SUPPORTED_MODELS)

    def _timeout_s(self) -> float:
        try:
            timeout = float(self._cfg("timeout_s", 300))
        except (TypeError, ValueError):
            timeout = 300.0
        return max(1.0, timeout)

    def _max_chars(self) -> int:
        try:
            limit = int(self._cfg("max_chars", 50000))
        except (TypeError, ValueError):
            limit = 50000
        return max(1, limit)

    def _max_concurrency(self) -> int:
        try:
            limit = int(self._cfg("max_concurrency", 2))
        except (TypeError, ValueError):
            limit = 2
        return max(1, min(limit, len(SUPPORTED_MODELS)))

    def _allow_binary(self) -> bool:
        value = self._cfg("allow_binary", False)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _preview_chars(self) -> int:
        try:
            limit = int(self._cfg("preview_chars", 500))
        except (TypeError, ValueError):
            limit = 500
        return max(0, limit)

    def _resolve_out_dir(self) -> Path:
        raw = self._cfg("out_dir", "data/translate-fanout")
        return Path(str(raw or "data/translate-fanout"))

    def resolve_binaries(self) -> dict[str, str | None]:
        resolved: dict[str, str | None] = {}
        for model in SUPPORTED_MODELS:
            resolved[model] = shutil.which(model)
        return resolved

    # -- public API -----------------------------------------------------

    def start_run(
        self,
        *,
        text: str | None = None,
        file_ref: str | None = None,
        models: list[str] | str | None = None,
        with_review: bool = True,
    ) -> str:
        if not self.is_enabled():
            raise PermissionError(
                "Translate fan-out is disabled (enable [TranslateFanout])"
            )
        max_chars = self._max_chars()
        kind = ""
        source_text = ""
        original_name = ""
        if text is not None and file_ref is not None:
            raise ValueError("Provide exactly one of text or file_ref")
        if text is not None:
            kind = "text"
            source_text = str(text)
            if not source_text.strip():
                raise ValueError("Text must not be empty")
            if "\x00" in source_text and not self._allow_binary():
                raise ValueError("Binary content is not allowed")
            if len(source_text) > max_chars:
                raise ValueError(f"Text exceeds max_chars={max_chars}")
        elif file_ref is not None:
            kind = "file"
            source_text, original_name = self._read_file_ref(file_ref, max_chars)
        else:
            raise ValueError("Provide exactly one of text or file_ref")

        if models is None:
            selected = self._default_models()
        elif isinstance(models, str):
            selected = parse_models(models, fallback="")
            if not selected:
                raise ValueError(f"Unknown models: {models}")
        else:
            selected = parse_models(list(models), fallback="")
            if not selected:
                raise ValueError("No supported models selected")

        run_id = utc_run_id()
        run_dir = self._run_dir_for_id(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "prompts").mkdir(parents=True, exist_ok=True)

        content_bytes = source_text.encode("utf-8")
        (run_dir / "original.txt").write_bytes(content_bytes)
        translate_prompt = build_translate_prompt(source_text, kind)
        (run_dir / "prompts" / "translate.prompt.txt").write_text(
            translate_prompt, encoding="utf-8"
        )
        (run_dir / "prompts" / "translate.instructions.txt").write_text(
            TRANSLATE_INSTRUCTIONS + "\n", encoding="utf-8"
        )

        record = TranslateRunRecord(
            run_id=run_id,
            kind=kind,
            char_count=len(source_text),
            source_hash=source_hash_hex(content_bytes),
            original_name=original_name,
            with_review=bool(with_review),
            models=selected,
            created_at=time.time(),
            per_model={name: PerModelState() for name in selected},
            input_preview=truncate_preview(source_text, self._preview_chars()),
        )
        with self._lock:
            self._runs[run_id] = record
        self._write_run_json(record)
        self._emit(
            "translate.run.started",
            {
                "run_id": run_id,
                "kind": kind,
                "char_count": record.char_count,
                "models": selected,
                "with_review": record.with_review,
            },
        )
        self.logger.info(
            "Translate fan-out started run_id=%s kind=%s chars=%d models=%s",
            run_id,
            kind,
            record.char_count,
            ",".join(selected),
        )
        thread = threading.Thread(
            target=self._background_entry,
            args=(run_id,),
            daemon=True,
            name=f"TranslateFanout-{run_id}",
        )
        thread.start()
        return run_id

    def list_runs(self, include_text: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            records = sorted(
                self._runs.values(), key=lambda item: item.created_at, reverse=True
            )
            return [item.to_summary(include_text=include_text) for item in records]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        cleaned = str(run_id or "").strip()
        if not SAFE_RUN_ID_RE.fullmatch(cleaned):
            return None
        with self._lock:
            record = self._runs.get(cleaned)
        if record is None:
            return None
        detail = record.to_summary(include_text=True)
        run_dir = self._run_dir_for_id(cleaned)
        try:
            detail["source_text"] = (run_dir / "original.txt").read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            detail["source_text"] = ""
        detail["original_name"] = record.original_name
        results: dict[str, dict[str, str]] = {}
        for model in record.models:
            results[model] = {
                "status": record.per_model.get(model, PerModelState()).status,
                "translation": self._read_text_file(
                    run_dir / f"{model}.translation.txt"
                ),
                "final": self._read_text_file(run_dir / f"{model}.final.txt"),
                "error": record.per_model.get(model, PerModelState()).error,
            }
        detail["results"] = results
        return detail

    # -- internals ------------------------------------------------------

    def _read_file_ref(self, file_ref: str, max_chars: int) -> tuple[str, str]:
        name = str(file_ref or "").strip()
        if not name:
            raise ValueError("file_ref must not be empty")
        if self.file_storage is None:
            raise ValueError("file_ref is not supported without file storage")
        is_valid = getattr(self.file_storage, "is_valid_stored_name", None)
        get_path = getattr(self.file_storage, "get_file_path", None)
        if not callable(is_valid) or not callable(get_path):
            raise ValueError("file_ref is not supported without file storage")
        if not bool(is_valid(name)):
            raise ValueError("Invalid file_ref")
        path = get_path(name)
        if path is None:
            raise ValueError("file_ref not found")
        candidate = Path(str(path))
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("file_ref not found")
        try:
            content = candidate.read_bytes()
        except OSError as exc:
            raise ValueError("file_ref not found") from exc
        if contains_binary(content) and not self._allow_binary():
            raise ValueError("Binary files are not allowed")
        text = decode_file_bytes(content, max_chars + 1)
        if len(text) > max_chars:
            raise ValueError(f"File text exceeds max_chars={max_chars}")
        if not text.strip():
            raise ValueError("File text must not be empty")
        entry_getter = getattr(self.file_storage, "get_file_entry", None)
        original_name = name
        if callable(entry_getter):
            try:
                entry = entry_getter(name)
                if entry is not None and getattr(entry, "original_name", None):
                    original_name = str(entry.original_name)
            except Exception:
                self.logger.debug("Failed to read file entry for %s", name)
        return text, original_name

    def _run_dir_for_id(self, run_id: str) -> Path:
        base = self._out_dir.resolve(strict=False)
        candidate = (base / f"{run_id}-gengo").resolve(strict=False)
        try:
            candidate.relative_to(base)
        except ValueError as exc:
            raise ValueError("Invalid run_id") from exc
        if candidate == base:
            raise ValueError("Invalid run_id")
        return candidate

    @staticmethod
    def _read_text_file(path: Path) -> str:
        try:
            if path.is_file() and not path.is_symlink():
                return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return ""

    def _write_run_json(self, record: TranslateRunRecord) -> None:
        try:
            run_dir = self._run_dir_for_id(record.run_id)
            payload = record.to_summary(include_text=False)
            payload.update(
                {
                    "source_hash": record.source_hash,
                    "original_name": record.original_name,
                }
            )
            (run_dir / "run.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
            )
        except (OSError, ValueError) as exc:
            self.logger.warning(
                "Failed to persist translate run %s: %s", record.run_id, exc
            )

    def _load_existing_runs(self) -> None:
        try:
            if not self._out_dir.is_dir():
                return
            for run_file in sorted(self._out_dir.glob("*-gengo/run.json")):
                try:
                    data = json.loads(run_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                run_id = str(data.get("run_id") or "")
                if not SAFE_RUN_ID_RE.fullmatch(run_id):
                    continue
                models = parse_models(data.get("models"), fallback="")
                per_model: dict[str, PerModelState] = {}
                raw_states = data.get("per_model") or {}
                if isinstance(raw_states, dict):
                    for name, state in raw_states.items():
                        if name not in SUPPORTED_MODELS or not isinstance(state, dict):
                            continue
                        per_model[name] = PerModelState(
                            status=str(state.get("status") or "queued"),
                            bytes=int(state.get("bytes") or 0),
                            ms=int(state.get("ms") or 0),
                            error=str(state.get("error") or ""),
                        )
                for name in models:
                    per_model.setdefault(name, PerModelState())
                try:
                    created_at = float(data.get("created_at") or 0.0)
                except (TypeError, ValueError):
                    created_at = 0.0
                finished_at = data.get("finished_at")
                try:
                    finished = float(finished_at) if finished_at is not None else None
                except (TypeError, ValueError):
                    finished = None
                self._runs[run_id] = TranslateRunRecord(
                    run_id=run_id,
                    kind=str(data.get("kind") or "text"),
                    char_count=int(data.get("char_count") or 0),
                    source_hash=str(data.get("source_hash") or ""),
                    original_name=str(data.get("original_name") or ""),
                    with_review=bool(data.get("with_review", True)),
                    models=models,
                    created_at=created_at,
                    finished_at=finished,
                    per_model=per_model,
                    input_preview=str(data.get("input_preview") or ""),
                )
        except OSError as exc:
            self.logger.warning("Failed to load existing translate runs: %s", exc)

    def _emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        callback = self._event_callback
        if callback is None:
            return
        try:
            callback(event_type, dict(payload))
        except Exception:
            self.logger.debug("Translate fan-out event callback failed", exc_info=True)

    def _background_entry(self, run_id: str) -> None:
        try:
            asyncio.run(self._run_fanout(run_id))
        except Exception:
            self.logger.exception("Translate fan-out run %s crashed", run_id)
            with self._lock:
                record = self._runs.get(run_id)
                if record is not None and record.finished_at is None:
                    record.finished_at = time.time()
                    for state in record.per_model.values():
                        if state.status in {"queued", "running"}:
                            state.status = "failed"
                            state.error = state.error or "runner crashed"
                    self._write_run_json(record)
            self._emit("translate.run.completed", {"run_id": run_id})

    async def _run_fanout(self, run_id: str) -> None:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return
            models = list(record.models)
            with_review = record.with_review
        run_dir = self._run_dir_for_id(run_id)
        try:
            source_text = (run_dir / "original.txt").read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            self.logger.error("Translate run %s missing original.txt", run_id)
            return
        binaries = self.resolve_binaries()
        semaphore = asyncio.Semaphore(self._max_concurrency())
        timeout_s = self._timeout_s()

        async def _guarded(model: str) -> None:
            async with semaphore:
                await self._run_one_model(
                    run_id,
                    model,
                    source_text,
                    binaries.get(model),
                    timeout_s,
                    with_review,
                )

        await asyncio.gather(*(_guarded(model) for model in models))
        self._write_collation(run_id, source_text)
        with self._lock:
            record = self._runs.get(run_id)
            if record is not None:
                record.finished_at = time.time()
                self._write_run_json(record)
                per_model = {
                    name: state.status for name, state in record.per_model.items()
                }
        self._emit(
            "translate.run.completed", {"run_id": run_id, "per_model": per_model}
        )
        self.logger.info("Translate fan-out finished run_id=%s", run_id)

    async def _run_one_model(
        self,
        run_id: str,
        model: str,
        source_text: str,
        binary_path: str | None,
        timeout_s: float,
        with_review: bool,
    ) -> None:
        run_dir = self._run_dir_for_id(run_id)
        out_path = run_dir / f"{model}.translation.txt"
        err_path = run_dir / f"{model}.translation.err.log"
        review_out = run_dir / f"{model}.review.txt"
        review_err = run_dir / f"{model}.review.err.log"
        final_path = run_dir / f"{model}.final.txt"
        status_path = run_dir / f"{model}.status"
        self._set_model_state(run_id, model, "running", "")

        if not binary_path:
            out_path.write_text(
                f"SKIPPED: '{model}' not installed (no binary on PATH)\n",
                encoding="utf-8",
            )
            final_path.write_text("SKIPPED not-installed\n", encoding="utf-8")
            status_path.write_text(
                "SKIPPED: 'not installed' not installed\n", encoding="utf-8"
            )
            self._set_model_state(run_id, model, "skipped", "not installed")
            self._emit(
                "translate.run.progress",
                {
                    "run_id": run_id,
                    "model": model,
                    "phase": "translate",
                    "status": "skipped",
                },
            )
            return

        translate_prompt_file = run_dir / "prompts" / "translate.prompt.txt"
        started = time.monotonic()
        argv, stdin_bytes = self._build_phase_argv(
            model, binary_path, translate_prompt_file, run_dir, phase="translate"
        )
        rc, stdout, stderr, timed_out = await self._execute_phase(
            argv, stdin_bytes, timeout_s
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        out_path.write_bytes(stdout)
        err_path.write_bytes(stderr)

        if timed_out:
            status_path.write_text(
                f"SKIPPED/TIMEOUT after {timeout_s:g}s in translate phase "
                f"(see {model}.translation.err.log)\n",
                encoding="utf-8",
            )
            final_path.write_bytes(stdout or b"[no output; timeout]\n")
            self._set_model_state(
                run_id,
                model,
                "skipped",
                f"timeout after {timeout_s:g}s",
                elapsed_ms,
                len(stdout),
            )
            self._write_run_json(self._runs[run_id])
            return

        combined = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")
        if is_skip_output(combined):
            status_path.write_text(
                f"SKIPPED (no active subscription / auth / quota).\nExit code: {rc}\n",
                encoding="utf-8",
            )
            final_path.write_text(
                f"SKIPPED: {model} has no active subscription, is not "
                "authenticated, or quota exhausted.\n",
                encoding="utf-8",
            )
            self._set_model_state(
                run_id,
                model,
                "skipped",
                "no sub / auth / quota",
                elapsed_ms,
                len(stdout),
            )
            self._write_run_json(self._runs[run_id])
            return

        cleaned = self._prefer_clean_output(model, stdout, run_dir, "translation")
        if cleaned is not None:
            out_path.write_bytes(cleaned)
            stdout = cleaned
        if not stdout.strip():
            status_path.write_text(
                f"FAILED translate phase: empty output (exit {rc}). See err log.\n",
                encoding="utf-8",
            )
            final_path.write_text(f"[no output; exit {rc}]\n", encoding="utf-8")
            self._set_model_state(
                run_id,
                model,
                "failed",
                f"empty output (exit {rc})",
                elapsed_ms,
                0,
            )
            self._write_run_json(self._runs[run_id])
            return

        status_path.write_text(
            f"OK translate (exit {rc}, {len(stdout)} bytes)\n", encoding="utf-8"
        )
        if not with_review:
            final_path.write_bytes(stdout)
            review_out.write_bytes(stdout)
            self._set_model_state(run_id, model, "ok", "", elapsed_ms, len(stdout))
            self._write_run_json(self._runs[run_id])
            return

        translation_text = stdout.decode("utf-8", errors="replace")
        review_prompt = build_review_prompt(source_text, translation_text)
        review_prompt_file = run_dir / "prompts" / f"review.{model}.prompt.txt"
        review_prompt_file.write_text(review_prompt, encoding="utf-8")
        self._emit(
            "translate.run.progress",
            {"run_id": run_id, "model": model, "phase": "review", "status": "running"},
        )
        review_argv, review_stdin = self._build_phase_argv(
            model, binary_path, review_prompt_file, run_dir, phase="review"
        )
        review_started = time.monotonic()
        rrc, rstdout, rstderr, rtimed_out = await self._execute_phase(
            review_argv, review_stdin, timeout_s
        )
        review_ms = int((time.monotonic() - review_started) * 1000)
        review_out.write_bytes(rstdout)
        review_err.write_bytes(rstderr)
        total_ms = elapsed_ms + review_ms

        if rtimed_out:
            final_path.write_bytes(stdout)
            status_path.write_text(
                status_path.read_text(encoding="utf-8", errors="replace")
                + f"review TIMEOUT after {timeout_s:g}s; "
                "falling back to translation as final\n",
                encoding="utf-8",
            )
            self._set_model_state(
                run_id,
                model,
                "ok",
                "review timeout; kept translation",
                total_ms,
                len(stdout),
            )
            self._write_run_json(self._runs[run_id])
            return

        rcombined = (rstdout + b"\n" + rstderr).decode("utf-8", errors="replace")
        if is_skip_output(rcombined):
            final_path.write_bytes(stdout)
            status_path.write_text(
                status_path.read_text(encoding="utf-8", errors="replace")
                + "review SKIPPED (auth/quota mid-run); "
                "falling back to translation as final\n",
                encoding="utf-8",
            )
            self._set_model_state(
                run_id,
                model,
                "ok",
                "review skipped; kept translation",
                total_ms,
                len(stdout),
            )
            self._write_run_json(self._runs[run_id])
            return

        cleaned_review = self._prefer_clean_output(model, rstdout, run_dir, "review")
        if cleaned_review is not None:
            review_out.write_bytes(cleaned_review)
            rstdout = cleaned_review
        if rstdout.strip():
            final_path.write_bytes(rstdout)
            status_path.write_text(
                status_path.read_text(encoding="utf-8", errors="replace")
                + f"OK review (exit {rrc})\n",
                encoding="utf-8",
            )
            self._set_model_state(run_id, model, "ok", "", total_ms, len(rstdout))
        else:
            final_path.write_bytes(stdout)
            status_path.write_text(
                status_path.read_text(encoding="utf-8", errors="replace")
                + "review empty; kept translation as final\n",
                encoding="utf-8",
            )
            self._set_model_state(
                run_id,
                model,
                "ok",
                "review empty; kept translation",
                total_ms,
                len(stdout),
            )
        self._write_run_json(self._runs[run_id])
        self._emit(
            "translate.run.progress",
            {"run_id": run_id, "model": model, "phase": "review", "status": "ok"},
        )

    def _set_model_state(
        self,
        run_id: str,
        model: str,
        status: str,
        error: str = "",
        ms: int = 0,
        size: int = 0,
    ) -> None:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return
            state = record.per_model.get(model)
            if state is None:
                state = PerModelState()
                record.per_model[model] = state
            state.status = status
            if error:
                state.error = error
            if ms:
                state.ms = ms
            if size:
                state.bytes = size

    def _build_phase_argv(
        self,
        model: str,
        binary_path: str,
        prompt_file: Path,
        run_dir: Path,
        *,
        phase: str,
    ) -> tuple[list[str], bytes | None]:
        prompt_text = prompt_file.read_text(encoding="utf-8", errors="replace")
        if model == "grok":
            return (
                [
                    binary_path,
                    "--prompt-file",
                    str(prompt_file),
                    "--output-format",
                    "plain",
                ],
                None,
            )
        if model == "opencode":
            return ([binary_path, "run", prompt_text], None)
        if model == "codex":
            suffix = "translation" if phase == "translate" else "review"
            lastmsg = run_dir / f"codex.{suffix}.lastmsg.txt"
            return (
                [
                    binary_path,
                    "exec",
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "--color",
                    "never",
                    "-o",
                    str(lastmsg),
                    "-",
                ],
                prompt_text.encode("utf-8"),
            )
        # claude
        return (
            [
                binary_path,
                "-p",
                prompt_text,
                "--output-format",
                "text",
                "--max-turns",
                "10",
            ],
            None,
        )

    @staticmethod
    def _prefer_clean_output(
        model: str, stdout: bytes, run_dir: Path, phase: str
    ) -> bytes | None:
        if model != "codex":
            return None
        if phase == "translation":
            candidates = [
                run_dir / "codex.translation.lastmsg.txt",
                run_dir / "codex.exec.lastmsg.txt",
            ]
        else:
            candidates = [run_dir / "codex.review.lastmsg.txt"]
        for candidate in candidates:
            try:
                if candidate.is_file() and candidate.stat().st_size > 10:
                    return candidate.read_bytes()
            except OSError:
                continue
        # Fall back to "<out>.lastmsg.txt" written by the CLI wrapper.
        return None

    async def _execute_phase(
        self, argv: list[str], stdin_bytes: bytes | None, timeout_s: float
    ) -> tuple[int, bytes, bytes, bool]:
        """Run one LLM phase without a shell; returns (rc, out, err, timed_out)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            return 127, b"", str(exc).encode("utf-8"), False
        except OSError as exc:
            return 127, b"", str(exc).encode("utf-8"), False
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_bytes), timeout=timeout_s
            )
            return proc.returncode or 0, stdout or b"", stderr or b"", False
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                stdout, stderr = await proc.communicate()
            except Exception:
                stdout, stderr = b"", b""
            return 124, stdout or b"", stderr or b"", True

    def _write_collation(self, run_id: str, source_text: str) -> None:
        try:
            run_dir = self._run_dir_for_id(run_id)
            with self._lock:
                record = self._runs.get(run_id)
                models = list(record.models) if record else list(SUPPORTED_MODELS)
            lines = [
                "# Gengo translation comparison",
                "",
                f"- Input: {record.kind if record else 'text'}",
                f"- Date (UTC): {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
                f"- Run dir: {run_dir}",
                "",
                "## Original",
                "```",
                source_text,
                "```",
                "",
            ]
            for model in SUPPORTED_MODELS:
                if model not in models:
                    continue
                lines += ["---", "", f"## {model}", ""]
                status_file = run_dir / f"{model}.status"
                if status_file.is_file():
                    first = status_file.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()[:3]
                    lines += [f"**Status:** {' '.join(first)}", ""]
                lines += ["### Translation (phase 1)", "```"]
                lines.append(
                    self._read_text_file(run_dir / f"{model}.translation.txt")
                    or "(no file — model not in run or not run)"
                )
                lines += ["```", ""]
                if record is None or record.with_review:
                    lines += ["### Reviewed final (phase 2)", "```"]
                    lines.append(
                        self._read_text_file(run_dir / f"{model}.final.txt")
                        or "(no final)"
                    )
                    lines += ["```", ""]
            lines += [
                "---",
                f"_Per-file outputs in {run_dir} : *.translation.txt, "
                "*.review.txt, *.final.txt, *.status_",
                "",
            ]
            (run_dir / "COMBINED.md").write_text("\n".join(lines), encoding="utf-8")
            summary_lines = [
                f"run_dir={run_dir}",
                f"input_mode={record.kind if record else 'text'}",
            ]
            for model in SUPPORTED_MODELS:
                if model not in models:
                    continue
                status_file = run_dir / f"{model}.status"
                if status_file.is_file():
                    first = status_file.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                    summary_lines.append(f"{model}: {first[0] if first else ''}")
                else:
                    summary_lines.append(f"{model}: not run")
            (run_dir / "summary.txt").write_text(
                "\n".join(summary_lines) + "\n", encoding="utf-8"
            )
        except (OSError, ValueError) as exc:
            self.logger.warning("Failed to collate translate run %s: %s", run_id, exc)


__all__ = [
    "DEFAULT_MODELS_STR",
    "REVIEW_INSTRUCTION",
    "SUPPORTED_MODELS",
    "TRANSLATE_INSTRUCTIONS",
    "TranslateFanoutService",
    "TranslateRunRecord",
    "build_review_prompt",
    "build_translate_prompt",
    "decode_file_bytes",
    "is_skip_output",
    "parse_models",
    "source_hash_hex",
    "truncate_preview",
]
