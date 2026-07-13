import json
import os
import tempfile
import threading
import pathlib
from typing import Any, List
import logging
import collections
import time
import datetime


class AppState:
    STATE_FILE = "state.json"
    MAX_STORED_JOBS = 5000
    MAX_SEEN_JOB_IDS = 50000
    SENSITIVE_PERSISTED_JOB_KEYS = {
        "_raw",
        "source_text",
        "accepted_source_text",
        "segments",
    }

    def __init__(
        self,
        logger: logging.Logger,
        state_file_path: str | pathlib.Path | None = None,
    ):
        self.logger = logger
        self._lock = threading.RLock()  # Reentrant lock for better safety
        self.state_file_path = pathlib.Path(state_file_path or self.STATE_FILE)

        self.last_seen_rss_link = None  # New variable for RSS tracking
        self.last_seen_link = None  # General last job (for display, optional)
        self.total_new_entries_found = 0
        self.seen_job_ids = collections.deque(maxlen=self.MAX_SEEN_JOB_IDS)
        self._sparkline_data = []

        # Job storage for web API
        self._jobs: List[dict[str, Any]] = []
        self._job_ids: set[str] = set()
        self._job_lookup: dict[tuple[str, str], dict[str, Any]] = {}
        self._jobs_lock = threading.RLock()

        self._load_state()

    @property
    def sparkline_data(self) -> List:
        with self._lock:
            return self._sparkline_data.copy()

    @sparkline_data.setter
    def sparkline_data(self, value: List):
        with self._lock:
            self._sparkline_data = list(value)

    def _load_state(self):
        try:
            if self.state_file_path.is_file():
                with open(self.state_file_path, "r", encoding="utf-8") as f:
                    state_data = json.load(f)
                    with self._lock:
                        self.last_seen_rss_link = state_data.get("last_seen_rss_link")
                        self.last_seen_link = state_data.get("last_seen_link")
                        self.total_new_entries_found = state_data.get(
                            "total_new_entries_found", 0
                        )
                        self.seen_job_ids = collections.deque(
                            state_data.get("seen_job_ids", []),
                            maxlen=self.MAX_SEEN_JOB_IDS,
                        )
                        # Persist sparkline data across sessions
                        self._sparkline_data = state_data.get("sparkline_data", [])

                        # Load stored jobs
                        stored_jobs = state_data.get("jobs", [])
                        with self._jobs_lock:
                            self._jobs = (
                                stored_jobs if isinstance(stored_jobs, list) else []
                            )
                            # Sort by timestamp descending (newest first)
                            self._jobs.sort(
                                key=lambda x: x.get("timestamp", 0), reverse=True
                            )
                            self._prune_jobs_unlocked()
                            self._rebuild_job_ids_unlocked()
        except (json.JSONDecodeError, IOError) as e:
            self.logger.exception(
                f"Could not load state file. Starting fresh. Error: {e}"
            )

    def load_jobs_from_csv(self, csv_path: str):
        """Load jobs from CSV file if state is empty or user requests history."""
        import csv
        import re

        try:
            path = pathlib.Path(csv_path)
            if not path.exists():
                return

            with open(path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    return

                new_jobs = []
                for row in reader:
                    if len(row) < 4:
                        continue
                    try:
                        timestamp_str = row[0]
                        try:
                            dt = datetime.datetime.fromisoformat(timestamp_str)
                            ts = dt.timestamp()
                        except ValueError:
                            ts = time.time()

                        title = row[1]
                        # Handle "$ 12.34" or "12.34"
                        reward_str = (
                            str(row[2]).replace("$", "").replace("US", "").strip()
                        )
                        reward = float(reward_str) if reward_str else 0.0
                        url = row[3]

                        match = re.search(r"/jobs/details/(\d+)", url)
                        job_id = match.group(1) if match else f"csv_{int(ts)}"

                        job = {
                            "timestamp": ts,
                            "id": job_id,
                            "title": title,
                            "source": "History",
                            "lang_pair": (
                                title.split("|")[0].strip()
                                if "|" in title
                                else "Unknown"
                            ),
                            "reward": reward,
                            "currency": "USD",
                            "url": url,
                        }
                        new_jobs.append(job)
                    except (ValueError, IndexError):
                        continue

                with self._jobs_lock:
                    for job in new_jobs:
                        self.add_job(job)

            self.logger.info(f"Loaded {len(new_jobs)} jobs from CSV history.")
        except Exception as e:
            self.logger.error(f"Error loading jobs from CSV: {e}")

    def save_state(self):
        """Save state atomically - write to temp file then rename."""
        try:
            with self._lock:
                with self._jobs_lock:
                    state_data = {
                        "last_seen_rss_link": self.last_seen_rss_link,
                        "last_seen_link": self.last_seen_link,
                        "total_new_entries_found": self.total_new_entries_found,
                        "sparkline_data": self._sparkline_data.copy(),
                        "seen_job_ids": list(self.seen_job_ids),
                        "jobs": [
                            self._redact_job_for_persistence(job) for job in self._jobs
                        ],
                    }

                # Atomic write: write to temp file, then rename
                dir_path = self.state_file_path.parent
                fd, temp_path = tempfile.mkstemp(
                    suffix=".tmp", prefix="state_", dir=dir_path
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(state_data, f, indent=4)
                    # Atomic rename (on POSIX systems)
                    os.replace(temp_path, self.state_file_path)
                except Exception:
                    # Clean up temp file on error
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
                    raise
        except IOError as e:
            self.logger.exception(f"Error saving state to {self.STATE_FILE}: {e}")

    @classmethod
    def _redact_job_for_persistence(cls, value: Any) -> Any:
        """Remove customer content while retaining workflow metadata."""
        if isinstance(value, dict):
            return {
                key: cls._redact_job_for_persistence(item)
                for key, item in value.items()
                if key not in cls.SENSITIVE_PERSISTED_JOB_KEYS
            }
        if isinstance(value, list):
            return [cls._redact_job_for_persistence(item) for item in value]
        return value

    def get_recent_jobs(self, limit: int = 50) -> List[dict[str, Any]]:
        """Get recent jobs from storage."""
        with self._jobs_lock:
            now = time.time()
            return [
                self._with_dynamic_accepted_fields(job.copy(), now=now)
                for job in self._jobs[:limit]
            ]

    @staticmethod
    def _primary_job_id(job: dict[str, Any]) -> str:
        return str(job.get("id") or "").strip()

    def _rebuild_job_ids_unlocked(self) -> None:
        self._job_ids = {
            job_id
            for job_id in (self._primary_job_id(job) for job in self._jobs)
            if job_id
        }
        self._job_lookup = {}
        for job in self._jobs:
            self._track_job_unlocked(job)

    def _track_job_unlocked(self, job: dict[str, Any]) -> None:
        job_id = self._primary_job_id(job)
        if job_id:
            self._job_ids.add(job_id)
        for identifier in self._job_identifier_keys(job):
            self._job_lookup[identifier] = job

    def _refresh_job_index_unlocked(
        self,
        job: dict[str, Any],
        old_identifiers: set[tuple[str, str]] | None = None,
    ) -> None:
        for identifier in old_identifiers or self._job_identifier_keys(job):
            if self._job_lookup.get(identifier) is job:
                del self._job_lookup[identifier]
        self._track_job_unlocked(job)

    @classmethod
    def _job_identifier_keys(cls, job: dict[str, Any]) -> set[tuple[str, str]]:
        identifiers: set[tuple[str, str]] = set()
        for key in ("id", "order_id", "accepted_order_id"):
            value = job.get(key)
            if value is not None and value != "":
                identifiers.add((key, str(value)))
        for key in ("job_ids", "accepted_job_ids"):
            values = job.get(key)
            if not isinstance(values, list):
                continue
            identifiers.update(
                (key, str(value)) for value in values if value not in (None, "")
            )
        return identifiers

    def _find_job_unlocked(self, job_id: str) -> dict[str, Any] | None:
        return self._find_by_identifier_keys_unlocked(
            self._any_identifier_lookup_keys(job_id)
        )

    @staticmethod
    def _any_identifier_lookup_keys(job_id: str) -> list[tuple[str, str]]:
        candidate = str(job_id)
        return [
            ("id", candidate),
            ("order_id", candidate),
            ("accepted_order_id", candidate),
            ("job_ids", candidate),
            ("accepted_job_ids", candidate),
        ]

    def _find_by_identifier_keys_unlocked(
        self,
        keys: list[tuple[str, str]],
    ) -> dict[str, Any] | None:
        for key in keys:
            job = self._job_lookup.get(key)
            if job is not None:
                return job
        return None

    @staticmethod
    def _order_identifier_lookup_keys(order_id: str) -> list[tuple[str, str]]:
        candidate = str(order_id)
        return [
            ("order_id", candidate),
            ("accepted_order_id", candidate),
        ]

    @staticmethod
    def _subjob_identifier_lookup_keys(job_id: str) -> list[tuple[str, str]]:
        candidate = str(job_id)
        return [
            ("job_ids", candidate),
            ("accepted_job_ids", candidate),
        ]

    def _find_by_workbench_ids_unlocked(
        self,
        *,
        collection_id: str | None = None,
        order_id: str | None = None,
        job_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        lookup_keys: list[tuple[str, str]] = []
        if collection_id:
            lookup_keys.extend(self._any_identifier_lookup_keys(str(collection_id)))
        if order_id:
            lookup_keys.extend(self._order_identifier_lookup_keys(str(order_id)))
        if job_ids:
            for job_id in job_ids:
                if job_id:
                    lookup_keys.extend(self._subjob_identifier_lookup_keys(str(job_id)))
        return self._find_by_identifier_keys_unlocked(lookup_keys)

    def _find_mark_accepted_job_unlocked(
        self,
        *,
        job_id: str,
        order_id: str | None = None,
        payload_job_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        lookup_keys = self._any_identifier_lookup_keys(str(job_id))
        if order_id:
            lookup_keys.extend(self._order_identifier_lookup_keys(str(order_id)))
        if payload_job_ids:
            for payload_job_id in payload_job_ids:
                if payload_job_id:
                    lookup_keys.extend(
                        self._subjob_identifier_lookup_keys(str(payload_job_id))
                    )
        return self._find_by_identifier_keys_unlocked(lookup_keys)

    def _prune_jobs_unlocked(self) -> None:
        limit = max(1, int(self.MAX_STORED_JOBS))
        if len(self._jobs) <= limit:
            return
        del self._jobs[limit:]
        self._rebuild_job_ids_unlocked()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Return a copy of a stored job by id or accepted workbench ids."""
        with self._jobs_lock:
            now = time.time()
            job = self._find_job_unlocked(job_id)
            if job is not None:
                return self._with_dynamic_accepted_fields(job.copy(), now=now)
        return None

    def update_job(self, job_id: str, updates: dict[str, Any]) -> bool:
        """Merge changed fields into a stored job by id.

        Returns True when the job exists, including no-op duplicate updates.
        """
        if not isinstance(updates, dict):
            return False
        with self._jobs_lock:
            job = self._find_job_unlocked(job_id)
            if job is None:
                return False
            changed = self._changed_fields(job, updates)
            if not changed:
                return True
            old_identifiers = self._job_identifier_keys(job)
            job.update(changed)
            self._refresh_job_index_unlocked(job, old_identifiers)
            self.logger.debug("Updated job %s fields: %s", job.get("id"), changed)
            return True
        return False

    @staticmethod
    def _changed_fields(
        job: dict[str, Any],
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        return {key: value for key, value in updates.items() if job.get(key) != value}

    @staticmethod
    def _job_matches_id(job: dict[str, Any], job_id: str) -> bool:
        candidate = str(job_id)
        return any(
            value == candidate for _key, value in AppState._job_identifier_keys(job)
        )

    def mark_job_accepted(
        self,
        job_id: str,
        *,
        accepted_workbench: dict[str, Any] | None = None,
        workbench_url: str | None = None,
    ) -> bool:
        """Mark a stored job accepted and attach optional workbench metadata."""
        accepted_at = time.time()
        payload = self._extract_workbench_payload(accepted_workbench)
        summary = self._workbench_summary(payload) if payload else {}
        summary_order_id = self._first_present(summary, "order_id", "id", "order")
        summary_order_id_text = None
        if summary_order_id is not None:
            summary_order_id_text = str(summary_order_id)
        payload_job_ids: list[str] = []
        if payload:
            for item in payload.get("jobs", []):
                if not isinstance(item, dict):
                    continue
                workbench_job_id = self._first_present(item, "id", "job_id")
                if workbench_job_id is not None:
                    payload_job_id = str(workbench_job_id)
                    payload_job_ids.append(payload_job_id)

        with self._jobs_lock:
            job = self._find_mark_accepted_job_unlocked(
                job_id=str(job_id),
                order_id=summary_order_id_text,
                payload_job_ids=payload_job_ids,
            )
            if job is not None:
                old_identifiers = self._job_identifier_keys(job)
                job["accepted"] = True
                job["accepted_at"] = accepted_at
                job["acceptance_state"] = "accepted"
                job["lifecycle_state"] = "accepted"
                if workbench_url:
                    job["workbench_url"] = workbench_url
                if accepted_workbench:
                    job["accepted_workbench"] = accepted_workbench
                if payload:
                    self._apply_workbench_summary(job, summary, accepted_at)
                    self._apply_workbench_jobs(job, payload)
                    self.logger.info(
                        (
                            "Parsed accepted workbench payload for job %s: "
                            "%s jobs, %s segments, %s source chars"
                        ),
                        job.get("id"),
                        job.get("accepted_workbench_job_count", 0),
                        job.get("accepted_segment_count", 0),
                        job.get("accepted_source_char_count", 0),
                    )
                self.logger.debug("Marked job %s as accepted", job.get("id"))
                self._refresh_job_index_unlocked(job, old_identifiers)
                return True
        return False

    @staticmethod
    def _extract_workbench_payload(
        accepted_workbench: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(accepted_workbench, dict):
            return {}
        payload = accepted_workbench.get("payload")
        if isinstance(payload, dict):
            return payload
        normalized = accepted_workbench.get("normalized")
        if isinstance(normalized, dict):
            raw = normalized.get("_raw")
            if isinstance(raw, dict):
                return raw
            raw_segments = normalized.get("segments")
            segments = raw_segments if isinstance(raw_segments, list) else []
            raw_job_ids = normalized.get("job_ids")
            job_ids = raw_job_ids if isinstance(raw_job_ids, list) else []
            jobs = []
            if segments:
                jobs.append(
                    {
                        "id": job_ids[0] if job_ids else normalized.get("order_id"),
                        "segments": segments,
                    }
                )
            return {"summary": normalized, "jobs": jobs}
        raw = accepted_workbench.get("_raw")
        if isinstance(raw, dict):
            return raw
        if isinstance(accepted_workbench.get("summary"), dict):
            return accepted_workbench
        if isinstance(accepted_workbench.get("order"), dict):
            return accepted_workbench
        if (
            accepted_workbench.get("order_id") is not None
            or accepted_workbench.get("jobs") is not None
        ):
            jobs = accepted_workbench.get("jobs")
            return {
                "summary": accepted_workbench,
                "jobs": jobs if isinstance(jobs, list) else [],
            }
        return {}

    @staticmethod
    def _workbench_summary(payload: dict[str, Any]) -> dict[str, Any]:
        summary = payload.get("summary")
        if isinstance(summary, dict):
            return summary
        order = payload.get("order")
        if isinstance(order, dict):
            return order
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _first_present(source: dict[str, Any], *keys: str) -> Any:
        if not isinstance(source, dict):
            return None
        for key in keys:
            value = source.get(key)
            if value is not None and value != "":
                return value
        return None

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            if value is None or value == "":
                return None
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _apply_workbench_summary(
        self,
        job: dict[str, Any],
        summary: dict[str, Any],
        accepted_at: float,
    ) -> None:
        job["accepted_payload_captured_at"] = accepted_at
        field_map = {
            "accepted_order_id": ("order_id", "id", "order"),
            "accepted_expire_time_ms": ("expire_time", "deadline"),
            "accepted_allotted_seconds": ("allotted_seconds",),
            "accepted_seconds_left_at_capture": ("seconds_left", "left"),
            "accepted_unit_count": ("unit_count", "units"),
            "accepted_customer_id": ("customer_id", "customer"),
            "accepted_auto_approve_time": ("auto_approve_time",),
        }
        for target, sources in field_map.items():
            value = self._coerce_int(self._first_present(summary, *sources))
            if value is not None:
                job[target] = value

        reward_total = self._coerce_float(
            self._first_present(summary, "rewards_total", "reward")
        )
        if reward_total is not None:
            job["accepted_reward_total"] = reward_total

        for target, sources in {
            "accepted_lc_src": ("lc_src", "source_language"),
            "accepted_lc_tgt": ("lc_tgt", "target_language"),
            "accepted_lc_src_name": ("lc_src_name",),
            "accepted_lc_tgt_name": ("lc_tgt_name",),
            "accepted_tier": ("tier", "quality_tier"),
            "accepted_tier_string": ("tier_string",),
            "accepted_status": ("status",),
            "accepted_status_name": ("status_name",),
            "accepted_purpose": ("purpose",),
            "accepted_service": ("service",),
        }.items():
            value = self._first_present(summary, *sources)
            if value is not None:
                job[target] = str(value)

    def _apply_workbench_jobs(
        self,
        job: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        raw_jobs = payload.get("jobs")
        workbench_jobs = raw_jobs if isinstance(raw_jobs, list) else []

        accepted_job_ids: list[str] = []
        segments: list[dict[str, Any]] = []
        source_parts: list[str] = []
        target_parts: list[str] = []

        for workbench_job in workbench_jobs:
            if not isinstance(workbench_job, dict):
                continue

            workbench_job_id = self._first_present(workbench_job, "id", "job_id")
            normalized_job_id = (
                str(workbench_job_id) if workbench_job_id is not None else ""
            )
            if normalized_job_id:
                accepted_job_ids.append(normalized_job_id)

            raw_segments = workbench_job.get("segments")
            workbench_segments = raw_segments if isinstance(raw_segments, list) else []
            for segment in workbench_segments:
                if not isinstance(segment, dict):
                    continue

                source_content = str(
                    self._first_present(
                        segment, "source_content", "text", "source_text", "source"
                    )
                    or ""
                )
                target_content = str(
                    self._first_present(
                        segment, "target_content", "target_text", "target"
                    )
                    or ""
                )
                normalized_segment: dict[str, Any] = {
                    "job_id": normalized_job_id,
                    "segment_id": str(segment.get("segment_id") or ""),
                    "source_content": source_content,
                    "target_content": target_content,
                    "has_errors": bool(
                        segment.get("hasErrors") or segment.get("has_errors")
                    ),
                    "has_warnings": bool(
                        segment.get("hasWarnings") or segment.get("has_warnings")
                    ),
                }

                glossary = segment.get("glossary")
                if isinstance(glossary, list):
                    normalized_segment["glossary"] = glossary

                segments.append(normalized_segment)
                if source_content:
                    source_parts.append(source_content)
                if target_content:
                    target_parts.append(target_content)

        if not accepted_job_ids:
            existing_job_ids = job.get("accepted_job_ids")
            if isinstance(existing_job_ids, list):
                accepted_job_ids = [str(value) for value in existing_job_ids if value]

        job["accepted_job_ids"] = accepted_job_ids
        job["accepted_workbench_job_count"] = len(workbench_jobs)
        source_text = "\n\n".join(source_parts)
        target_text = "\n\n".join(target_parts)
        job["accepted_segments"] = segments
        job["accepted_segment_count"] = len(segments)
        job["accepted_source_text"] = source_text
        job["accepted_source_char_count"] = len(source_text)
        job["accepted_target_text"] = target_text
        job["accepted_target_char_count"] = len(target_text)

    def _with_dynamic_accepted_fields(
        self, job: dict[str, Any], *, now: float
    ) -> dict[str, Any]:
        seconds_left = self._calculate_accepted_seconds_left(job, now=now)
        if seconds_left is not None:
            job["accepted_seconds_left"] = seconds_left
            job["accepted_time_left"] = self._format_duration(seconds_left)
            job["accepted_expired"] = seconds_left <= 0
        return job

    def _calculate_accepted_seconds_left(
        self, job: dict[str, Any], *, now: float
    ) -> int | None:
        raw_expire = job.get("accepted_expire_time_ms")
        if raw_expire is None:
            payload = self._extract_workbench_payload(job.get("accepted_workbench"))
            summary = self._workbench_summary(payload) if payload else {}
            raw_expire = self._first_present(summary, "expire_time", "deadline")
        expire_value = self._coerce_float(raw_expire)
        if expire_value is not None and expire_value > 0:
            if expire_value > 10_000_000_000:
                expire_epoch = expire_value / 1000.0
                return max(0, int(expire_epoch - now))
            return max(0, int(expire_value - now))

        captured_left = self._coerce_float(job.get("accepted_seconds_left_at_capture"))
        captured_at = self._coerce_float(job.get("accepted_payload_captured_at"))
        if captured_left is None or captured_at is None:
            return None
        return max(0, int(captured_left - max(0.0, now - captured_at)))

    @staticmethod
    def _format_duration(seconds: int) -> str:
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes:02d}m"
        return f"{minutes}m {secs:02d}s"

    def add_job(self, job_data: dict[str, Any]) -> bool:
        """Add a new job to storage.

        Returns:
            bool: True if the job was inserted, False if it already existed.
        """
        with self._jobs_lock:
            job_id = self._primary_job_id(job_data)
            if job_id and job_id in self._job_ids:
                return False  # Job already exists

            # Add new job
            self._jobs.insert(0, job_data)  # Add to beginning for newest first
            self._track_job_unlocked(job_data)
            self._prune_jobs_unlocked()

            self.logger.debug(f"Added job {job_data.get('id')} to storage")
            return True

    def get_job_count(self) -> int:
        """Get total number of stored jobs."""
        with self._jobs_lock:
            return len(self._jobs)

    def upsert_browser_observation(
        self,
        collection_id: str | None,
        updates: dict[str, Any],
    ) -> bool:
        """Insert or update a browser-observed job without marking it accepted.

        Returns True only when a row was inserted or at least one field changed.
        """
        if not collection_id or not isinstance(updates, dict):
            return False

        normalized_id = str(collection_id)
        with self._jobs_lock:
            job = self._find_job_unlocked(normalized_id)
            if job is not None:
                changed = self._changed_fields(job, updates)
                if not changed:
                    return False
                old_identifiers = self._job_identifier_keys(job)
                job.update(changed)
                self._refresh_job_index_unlocked(job, old_identifiers)
                self.logger.debug("Updated job %s fields: %s", job.get("id"), changed)
                return True

            now = time.time()
            job_data: dict[str, Any] = {
                "id": normalized_id,
                "title": f"Workbench {normalized_id}",
                "reward": 0.0,
                "currency": "USD",
                "url": updates.get("workbench_url")
                or f"https://gengo.com/t/workbench/{normalized_id}",
                "timestamp": now,
                "source": "Browser",
                "accepted": False,
                "lifecycle_state": "observed",
            }
            job_data.update(
                {key: value for key, value in updates.items() if value is not None}
            )
            self._jobs.insert(0, job_data)
            self._track_job_unlocked(job_data)
            self._prune_jobs_unlocked()
            self.logger.debug("Added browser-observed job %s to storage", normalized_id)
            return True

    def upsert_browser_job_details(
        self,
        *,
        collection_id: str | None = None,
        order_id: str | None = None,
        job_ids: list[str] | None = None,
        workbench_payload: dict[str, Any] | None = None,
        workbench_url: str | None = None,
    ) -> bool:
        """Insert or update job from browser observation (manual accept).

        Matches by: collection_id, order_id, job_ids list.
        Creates job if not found, updates if exists.
        """
        if not collection_id:
            return False

        accepted_at = time.time()
        payload = self._extract_workbench_payload(workbench_payload)
        summary = self._workbench_summary(payload) if payload else {}
        summary_order_id = self._first_present(summary, "order_id", "id", "order")
        if order_id is None and summary_order_id is not None:
            order_id = str(summary_order_id)

        if payload:
            raw_jobs = payload.get("jobs")
            workbench_jobs = raw_jobs if isinstance(raw_jobs, list) else []
            payload_job_ids = []
            for workbench_job in workbench_jobs:
                if not isinstance(workbench_job, dict):
                    continue
                workbench_job_id = self._first_present(workbench_job, "id", "job_id")
                if workbench_job_id is not None:
                    payload_job_ids.append(str(workbench_job_id))
            if payload_job_ids:
                if job_ids is None:
                    job_ids = payload_job_ids

        with self._jobs_lock:
            # Try to find existing job
            job = self._find_by_workbench_ids_unlocked(
                collection_id=collection_id,
                order_id=order_id,
                job_ids=job_ids,
            )
            if job is not None:
                old_identifiers = self._job_identifier_keys(job)
                updates = self._browser_acceptance_updates(
                    job=job,
                    accepted_at=accepted_at,
                    workbench_payload=workbench_payload,
                    workbench_url=workbench_url,
                    order_id=order_id,
                    job_ids=job_ids,
                )
                changed = self._changed_fields(job, updates)
                if changed:
                    job.update(changed)
                metadata_changed = False
                if payload:
                    before = job.copy()
                    self._apply_workbench_summary(job, summary, accepted_at)
                    self._apply_workbench_jobs(job, payload)
                    metadata_changed = any(
                        before.get(key) != value for key, value in job.items()
                    )
                self._refresh_job_index_unlocked(job, old_identifiers)
                return bool(changed or metadata_changed)

            # Create new job
            job_data: dict[str, Any] = {
                "id": str(collection_id),
                "accepted": True,
                "accepted_at": accepted_at,
                "acceptance_state": "accepted",
                "lifecycle_state": "accepted",
                "source": "browser_manual",
                "timestamp": accepted_at,
            }
            if workbench_url:
                job_data["workbench_url"] = workbench_url
            if workbench_payload:
                job_data["accepted_workbench"] = workbench_payload
            if order_id:
                coerced_order_id = self._coerce_int(order_id)
                job_data["accepted_order_id"] = (
                    coerced_order_id if coerced_order_id is not None else str(order_id)
                )
            if job_ids:
                job_data["accepted_job_ids"] = [
                    str(job_id) for job_id in job_ids if job_id
                ]
            if payload:
                self._apply_workbench_summary(job_data, summary, accepted_at)
                self._apply_workbench_jobs(job_data, payload)

            self._jobs.insert(0, job_data)
            self._track_job_unlocked(job_data)
            self._prune_jobs_unlocked()
            return True

    def _browser_acceptance_updates(
        self,
        *,
        job: dict[str, Any],
        accepted_at: float,
        workbench_payload: dict[str, Any] | None,
        workbench_url: str | None,
        order_id: str | None,
        job_ids: list[str] | None,
    ) -> dict[str, Any]:
        updates: dict[str, Any] = {
            "accepted": True,
            "acceptance_state": "accepted",
            "lifecycle_state": "accepted",
        }
        if not job.get("accepted_at"):
            updates["accepted_at"] = accepted_at
        if workbench_url:
            updates["workbench_url"] = workbench_url
        if workbench_payload:
            updates["accepted_workbench"] = workbench_payload
        if order_id:
            coerced_order_id = self._coerce_int(order_id)
            updates["accepted_order_id"] = (
                coerced_order_id if coerced_order_id is not None else str(order_id)
            )
        if job_ids:
            updates["accepted_job_ids"] = [str(job_id) for job_id in job_ids if job_id]
        return updates

    def mark_browser_job_accepted(
        self, collection_id: str, workbench_payload: dict | None = None
    ) -> bool:
        """Mark job as accepted from browser action. Uses same logic as mark_job_accepted."""
        return self.mark_job_accepted(
            collection_id, accepted_workbench=workbench_payload
        )

    def update_browser_job_status(
        self, collection_id: str, status: str, seconds_left: int | None = None
    ) -> bool:
        """Update browser-observed status for a job."""
        updates: dict[str, Any] = {"acceptance_state": status}
        if seconds_left is not None:
            updates["accepted_seconds_left"] = seconds_left
        return self.update_job(collection_id, updates)
