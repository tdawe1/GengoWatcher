from __future__ import annotations

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Optional
import unicodedata

from pydantic import BaseModel

from .config import AppConfig


class StoredFileEntry(BaseModel):
    stored_name: str
    original_name: str
    size_bytes: int
    content_type: Optional[str] = None
    modified_at: float
    download_url: str
    job_id: Optional[str] = None
    tier: Optional[str] = None
    word_count: Optional[int] = None
    value: Optional[float] = None


class StoredFileUploadResponse(BaseModel):
    status: str
    file: StoredFileEntry


class WebFileStorage:
    """Persist and resolve uploaded files for the web API."""

    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger

    def get_storage_dir(self) -> Path:
        raw_path = (
            self.config.get("Paths", "file_storage_dir", fallback="data/files")
            or "data/files"
        )
        storage_dir = Path(str(raw_path))
        storage_dir.mkdir(parents=True, exist_ok=True)
        return storage_dir

    def cleanup_expired_files(self) -> int:
        """Delete stored files and metadata older than configured retention."""
        try:
            retention_days = int(
                self.config.get(
                    "TranslationWorkflow",
                    "file_retention_days",
                    fallback=30,
                )
                or 0
            )
        except (TypeError, ValueError):
            retention_days = 30
        if retention_days <= 0:
            return 0

        cutoff = time.time() - retention_days * 86400
        removed = 0
        storage_dir = self.get_storage_dir()
        for path in storage_dir.iterdir():
            if (
                not path.is_file()
                or path.is_symlink()
                or path.name.startswith(".")
                or path.name.endswith(".meta.json")
            ):
                continue
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
                path.unlink()
                removed += 1
                metadata_path = self.metadata_path(path)
                if metadata_path.is_file() and not metadata_path.is_symlink():
                    metadata_path.unlink()
                    removed += 1
            except OSError as exc:
                self.logger.warning("Failed removing expired file %s: %s", path, exc)

        for metadata_path in storage_dir.glob(".*.meta.json"):
            if not metadata_path.is_file() or metadata_path.is_symlink():
                continue
            primary_name = metadata_path.name[1 : -len(".meta.json")]
            primary_path = storage_dir / primary_name
            if primary_path.exists():
                continue
            try:
                metadata_path.unlink()
                removed += 1
            except OSError as exc:
                self.logger.warning(
                    "Failed removing orphaned file metadata %s: %s",
                    metadata_path,
                    exc,
                )
        return removed

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        base_name = Path(str(filename or "upload.bin")).name.strip()
        normalized = unicodedata.normalize("NFKD", base_name)
        ascii_name = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        safe_name = re.sub(r"[\x00-\x1f\x7f]+", "", ascii_name)
        safe_name = safe_name.replace("/", "_").replace("\\", "_")
        safe_name = re.sub(r"[^A-Za-z0-9_ .()_-]+", "-", safe_name)
        safe_name = re.sub(r"\s+", " ", safe_name)
        safe_name = re.sub(r"-{2,}", "-", safe_name)
        while ".." in safe_name:
            safe_name = safe_name.replace("..", ".")
        safe_name = safe_name.strip(" .-_")
        original_suffix = Path(base_name).suffix.lstrip(".")
        if original_suffix and "." not in safe_name:
            safe_suffix = re.sub(r"[^A-Za-z0-9]+", "", original_suffix) or "bin"
            if safe_name.lower() == safe_suffix.lower():
                safe_name = f"upload.{safe_suffix}"
            else:
                safe_name = f"{safe_name}.{safe_suffix}"
        return safe_name or "upload.bin"

    @staticmethod
    def sanitize_file_component(value: str, fallback: str) -> str:
        text = str(value or "").strip()
        text = text.replace("/", "_").replace("\\", "_")
        text = re.sub(r"[^A-Za-z0-9._-]+", "-", text)
        text = text.strip("-._")
        return text or fallback

    def ensure_within_storage_dir(self, path: Path) -> Path:
        storage_dir = self.get_storage_dir().resolve(strict=True)

        candidate_path = Path(path)
        candidate_name = candidate_path.name
        if candidate_name in {"", ".", ".."}:
            raise ValueError("Invalid stored filename")

        try:
            if candidate_path.is_absolute():
                resolved = candidate_path.resolve(strict=False)
            else:
                if candidate_path != Path(candidate_name):
                    raise ValueError("Invalid stored filename")
                resolved = (storage_dir / candidate_name).resolve(strict=False)
        except OSError as exc:
            raise ValueError("Invalid path in configured storage directory") from exc

        try:
            resolved.relative_to(storage_dir)
        except ValueError as exc:
            raise ValueError("Path escapes configured storage directory") from exc
        if resolved == storage_dir:
            raise ValueError("Invalid stored filename")
        return resolved

    def is_valid_stored_name(self, stored_name: str) -> bool:
        name = str(stored_name or "").strip()
        if not name or name in {".", ".."}:
            return False
        if "/" in name or "\\" in name or "\x00" in name:
            return False
        if ".." in name:
            return False
        if self.sanitize_filename(name) != name:
            return False
        return re.fullmatch(r"[A-Za-z0-9_ .()_-]+", name) is not None

    def build_file_entry(
        self,
        path: Path,
        *,
        original_name: str | None = None,
        content_type: str | None = None,
    ) -> StoredFileEntry:
        stored_name = path.name
        if not self.is_valid_stored_name(stored_name):
            raise ValueError("Invalid stored file path")
        safe_path = self.get_file_path(stored_name)
        if safe_path is None:
            raise ValueError("Invalid stored file path")
        metadata = self.load_file_metadata(safe_path)
        stats = safe_path.stat()
        return StoredFileEntry(
            stored_name=safe_path.name,
            original_name=original_name
            or metadata.get("original_name")
            or safe_path.name,
            size_bytes=stats.st_size,
            content_type=content_type or metadata.get("content_type"),
            modified_at=float(metadata.get("uploaded_at") or stats.st_mtime),
            download_url=f"/api/files/{safe_path.name}",
            job_id=metadata.get("job_id"),
            tier=metadata.get("tier"),
            word_count=metadata.get("word_count"),
            value=metadata.get("value"),
        )

    def metadata_path(self, path: Path) -> Path:
        safe_path = self.ensure_within_storage_dir(path)
        storage_dir = self.get_storage_dir().resolve()
        metadata_name = f".{safe_path.name}.meta.json"
        metadata_path = storage_dir / metadata_name
        return self.ensure_within_storage_dir(metadata_path)

    def load_file_metadata(self, path: Path) -> dict[str, Any]:
        metadata_path = self.metadata_path(path)
        if not metadata_path.is_file():
            return {}
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.warning(
                "Failed to read file metadata for %s: %s",
                path.name,
                exc,
            )
            return {}
        if isinstance(data, dict):
            return data
        return {}

    @staticmethod
    def _stage_atomic_file(path: Path, content: bytes) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(content)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            return temp_path
        except Exception:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
            raise

    @staticmethod
    def _cleanup_staged_file(path: Path | None) -> None:
        if path is None:
            return
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def list_files(self) -> list[StoredFileEntry]:
        self.cleanup_expired_files()
        storage_dir = self.get_storage_dir()
        entries: list[StoredFileEntry] = []
        for path in sorted(
            storage_dir.glob("*"),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        ):
            if (
                not path.is_file()
                or path.name.startswith(".")
                or path.name.endswith(".meta.json")
            ):
                continue
            entries.append(self.build_file_entry(path))
        return entries

    def save_uploaded_file(
        self,
        filename: str,
        content: bytes,
        *,
        content_type: str | None = None,
        job_id: str | None = None,
        tier: str | None = None,
        word_count: int | None = None,
        value: float | None = None,
    ) -> StoredFileEntry:
        self.cleanup_expired_files()
        if job_id is not None:
            job_id = str(job_id).strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", job_id):
                raise ValueError("Invalid job id")
        storage_dir = self.get_storage_dir()
        safe_name = self.build_stored_filename(
            filename=filename,
            job_id=job_id,
            tier=tier,
            word_count=word_count,
            value=value,
        )
        if not self.is_valid_stored_name(safe_name):
            raise ValueError("Invalid stored filename")
        destination = self.ensure_within_storage_dir(storage_dir / safe_name)
        counter = 1
        while destination.exists():
            stem = Path(safe_name).stem
            suffix = Path(safe_name).suffix
            candidate_name = f"{stem}-{counter}{suffix}"
            if not self.is_valid_stored_name(candidate_name):
                raise ValueError("Invalid stored filename")
            destination = self.ensure_within_storage_dir(storage_dir / candidate_name)
            counter += 1
        metadata = {
            "original_name": filename or destination.name,
            "content_type": content_type,
            "uploaded_at": time.time(),
            "job_id": str(job_id).strip() if job_id else None,
            "tier": self.normalize_tier(tier, word_count=word_count, value=value),
            "word_count": int(word_count) if word_count is not None else None,
            "value": float(value) if value is not None else None,
        }
        metadata_path = self.metadata_path(destination)
        content_temp = self._stage_atomic_file(destination, content)
        metadata_temp = self._stage_atomic_file(
            metadata_path,
            json.dumps(metadata, indent=2, sort_keys=True).encode("utf-8"),
        )
        metadata_published = False
        try:
            metadata_temp.replace(metadata_path)
            metadata_published = True
            content_temp.replace(destination)
        except Exception:
            self._cleanup_staged_file(content_temp)
            self._cleanup_staged_file(metadata_temp)
            if metadata_published:
                self._cleanup_staged_file(metadata_path)
            raise
        entry = self.build_file_entry(
            destination,
            original_name=filename or destination.name,
            content_type=content_type,
        )
        self.logger.info(
            "Stored uploaded file %s at %s", entry.stored_name, destination
        )
        return entry

    def resolve_stored_file_path(self, stored_name: str) -> Path | None:
        if not self.is_valid_stored_name(stored_name):
            return None
        storage_dir = self.get_storage_dir().resolve()
        candidate = storage_dir / stored_name
        try:
            return self.ensure_within_storage_dir(candidate)
        except ValueError:
            return None

    def get_file_path(self, stored_name: str) -> Path | None:
        if not self.is_valid_stored_name(stored_name):
            return None
        stored_path = Path(stored_name)
        if stored_path.is_absolute() or stored_path.name != stored_name:
            return None
        storage_dir = self.get_storage_dir().resolve()
        try:
            for candidate in storage_dir.iterdir():
                if candidate.name != stored_name:
                    continue
                if not candidate.is_file() or candidate.is_symlink():
                    return None
                safe_path = self.ensure_within_storage_dir(candidate)
                if (
                    not safe_path.exists()
                    or not safe_path.is_file()
                    or safe_path.is_symlink()
                ):
                    return None
                return safe_path
        except (OSError, ValueError):
            return None
        return None

    def get_file_entry(self, stored_name: str) -> StoredFileEntry | None:
        path = self.get_file_path(stored_name)
        if path is None:
            return None
        return self.build_file_entry(path)

    @staticmethod
    def normalize_tier(
        tier: str | None,
        *,
        word_count: int | None = None,
        value: float | None = None,
    ) -> str | None:
        normalized = str(tier or "").strip().lower()
        if normalized in ("pro", "standard"):
            return normalized
        if word_count is not None and value is not None:
            rate = value / word_count if word_count > 0 else 0.0
            if rate >= 0.05:
                return "pro"
        return "standard"

    def build_stored_filename(
        self,
        filename: str,
        *,
        job_id: str | None = None,
        tier: str | None = None,
        word_count: int | None = None,
        value: float | None = None,
    ) -> str:
        safe_original = self.sanitize_filename(filename)
        suffix = Path(safe_original).suffix or ".bin"
        if not suffix.startswith("."):
            suffix = f".{suffix}"

        if job_id is None and tier is None and word_count is None and value is None:
            return safe_original

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        normalized_tier = (
            self.normalize_tier(
                tier,
                word_count=word_count,
                value=value,
            )
            or "standard"
        )
        normalized_job_id = self.sanitize_file_component(
            str(job_id or "job"),
            fallback="job",
        )
        normalized_word_count = max(int(word_count or 0), 0)
        normalized_value = max(float(value or 0.0), 0.0)
        value_component = f"{normalized_value:.2f}"
        generated = (
            f"{timestamp}_{normalized_job_id}_{normalized_tier}_"
            f"{normalized_word_count}w_{value_component}{suffix}"
        )
        return self.sanitize_filename(generated)
