"""Compact read model for TUI rendering.

Contains ONLY:
- recent jobs
- active accepted jobs
- deadline/countdown
- workflow state
- file state
- browser listener health

No full raw JSON in hot render path - optimized for TUI.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .event_bus import register_consumer

logger = logging.getLogger(__name__)


class TuiStore:
    """Compact in-memory store for TUI rendering.

    Updated by event bus consumer thread - no blocking reads.
    """

    _instance: "TuiStore | None" = None
    _lock = threading.Lock()

    def __init__(self):
        self._recent_jobs: list[dict] = []
        self._active_jobs: dict[str, dict] = {}  # job_id -> job
        self._countdowns: dict[str, int] = {}  # job_id -> seconds_left
        self._countdown_updated_at: dict[str, float] = {}
        self._workflow_state: dict[str, Any] = {}
        self._file_state: dict[str, Any] = {}
        self._browser_health: dict[str, Any] = {"last_seen": None, "status": "unknown"}

        # Register as consumer on the event bus
        self._consumer_queue = register_consumer("tui")

    def update_from_event(self, event: dict) -> None:
        """Update store from event envelope.

        Called by event bus consumer thread - must be fast.
        """
        event_type = event.get("type")
        payload = event.get("payload", {})

        if event_type == "job.visible":
            self._update_browser_visible(payload)
            if self._is_recent_job_payload(payload):
                self._add_recent_job(payload)
        elif event_type == "job.accepted":
            job_id = str(payload.get("id") or payload.get("order_id", ""))
            self._active_jobs[job_id] = payload
            # Prune stale active jobs (keep max 50)
            if len(self._active_jobs) > 50:
                oldest = sorted(
                    self._active_jobs.items(), key=lambda x: x[1].get("timestamp", 0)
                )
                self._active_jobs = dict(oldest[-50:])
        elif event_type == "browser.workbench.visible":
            self._update_browser_visible(payload)
        elif event_type == "browser.workbench.status":
            self._update_countdown(payload)
        elif event_type == "job.file_pending" or event_type == "job.file_ready":
            coll_id = str(payload.get("collection_id") or payload.get("job_id") or "")
            if coll_id:
                self._file_state[coll_id] = payload
        elif event_type == "job.status":
            coll_id = str(payload.get("collection_id") or "")
            if coll_id:
                self._workflow_state[coll_id] = payload
            self._update_countdown(payload)

    def _is_recent_job_payload(self, payload: dict) -> bool:
        return any(key in payload for key in ("id", "title", "reward", "source"))

    def _update_browser_visible(self, payload: dict) -> None:
        coll_id = payload.get("collection_id")
        if coll_id:
            self._browser_health = {
                "last_seen": time.time(),
                "collection_id": coll_id,
                "status": "visible",
            }

    def _update_countdown(self, payload: dict) -> None:
        coll_id = str(payload.get("collection_id") or "")
        if coll_id and "seconds_left" in payload:
            self._countdowns[coll_id] = payload["seconds_left"]
            self._countdown_updated_at[coll_id] = time.time()
            self._prune_countdowns()

    def _add_recent_job(self, job: dict) -> None:
        """Add job to recent list - maintains 50 most recent, deduplicated by id."""
        job_id = job.get("id")
        # Remove existing entry with same id (dedup)
        if job_id is not None:
            self._recent_jobs = [j for j in self._recent_jobs if j.get("id") != job_id]
        self._recent_jobs.insert(
            0,
            {
                "id": job_id,
                "title": job.get("title", ""),
                "reward": job.get("reward", 0),
                "source": job.get("source", ""),
                "timestamp": job.get("timestamp", time.time()),
            },
        )
        self._recent_jobs = self._recent_jobs[:50]  # Keep only 50

    def _prune_countdowns(self, limit: int = 50) -> None:
        if len(self._countdowns) <= limit:
            return
        newest_ids = {
            coll_id
            for coll_id, _updated_at in sorted(
                self._countdown_updated_at.items(),
                key=lambda item: item[1],
            )[-limit:]
        }
        self._countdowns = {
            coll_id: seconds
            for coll_id, seconds in self._countdowns.items()
            if coll_id in newest_ids
        }
        self._countdown_updated_at = {
            coll_id: updated_at
            for coll_id, updated_at in self._countdown_updated_at.items()
            if coll_id in newest_ids
        }

    def get_recent_jobs(self, limit: int = 50) -> list[dict]:
        return self._recent_jobs[:limit]

    def get_active_jobs(self) -> list[dict]:
        return list(self._active_jobs.values())

    def get_countdown(self, job_id: str) -> int | None:
        return self._countdowns.get(job_id)

    def get_workflow_state(self) -> dict[str, Any]:
        return self._workflow_state.copy()

    def get_file_state(self) -> dict[str, Any]:
        return self._file_state.copy()

    def get_browser_health(self) -> dict[str, Any]:
        return self._browser_health.copy()

    @classmethod
    def get_instance(cls) -> "TuiStore":
        """Get singleton TUI store instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def drain_events(self, app_call_from_thread: Any | None = None) -> int:
        """Drain pending events from queue and update store.

        Called by TUI main loop periodically.
        Returns count of events processed.
        """
        from queue import Empty

        count = 0
        while True:
            try:
                event_dict = self._consumer_queue.get_nowait()
                self.update_from_event(event_dict)
                count += 1
            except Empty:
                break
            except Exception as e:
                logger.warning(f"TUI store drain error: {e}")

        return count
