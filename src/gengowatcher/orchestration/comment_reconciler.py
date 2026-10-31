"""Poll tracked pipeline jobs for new customer comments and auto-revise.

After a job reaches ``ready_for_review`` (or is submitted/archived), the
customer can still post comments on the Gengo details page asking for fixes.
``CommentReconciler`` periodically asks ``JobPipelineService.check_comments``
about every watchable job; new comments trigger a patch + full-review
revision that lands back at ``ready_for_review`` and holds for approval.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from gengowatcher.orchestration.job_pipeline import REVISION_WATCH_STATES
from gengowatcher.workbench_client import WorkbenchSessionDeadError

DEFAULT_INITIAL_DELAY_SEC = 10.0


class CommentReconciler:
    """Background poller that starts revisions for new customer comments."""

    def __init__(
        self,
        logger: logging.Logger,
        *,
        pipeline: Any,
        interval_sec: float,
        initial_delay_sec: float = DEFAULT_INITIAL_DELAY_SEC,
    ) -> None:
        self.logger = logger
        self._pipeline = pipeline
        self.interval_sec = max(1.0, float(interval_sec))
        self.initial_delay_sec = max(0.0, float(initial_delay_sec))
        self._session_dead = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> list[str]:
        """Check every watchable job once; return ids that started revising."""
        revised: list[str] = []
        for job in self._pipeline.list_jobs():
            collection_id = str(job.get("collection_id") or "").strip()
            if not collection_id:
                continue
            if str(job.get("state") or "") not in REVISION_WATCH_STATES:
                continue
            # Only submitted archives are revision candidates; work filed as
            # Unsubmitted was never delivered to the customer.
            if job.get("state") == "archived" and (
                job.get("archive_outcome") not in ("Submitted", "Submitted-Auto")
            ):
                continue
            try:
                result = self._pipeline.check_comments(
                    collection_id, background=True
                )
            except WorkbenchSessionDeadError:
                raise
            except Exception:
                self.logger.exception(
                    "Comment check failed for collection %s", collection_id
                )
                continue
            if int(result.get("new_comments") or 0) > 0:
                revised.append(collection_id)
                self.logger.info(
                    "Started comment revision for collection %s", collection_id
                )
        return revised

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="CommentReconciler"
        )
        self._thread.start()
        self.logger.info(
            "Comment reconciler started (interval %.0fs)", self.interval_sec
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        self._thread = None

    def _loop(self) -> None:
        if self._stop_event.wait(self.initial_delay_sec):
            return
        while not self._stop_event.is_set():
            self._run_guarded()
            if self._stop_event.wait(self.interval_sec):
                break
        self.logger.info("Comment reconciler stopped.")

    def _run_guarded(self) -> None:
        try:
            self.run_once()
        except WorkbenchSessionDeadError as exc:
            if not self._session_dead:
                self._session_dead = True
                self.logger.warning(
                    "Comment reconciler: Gengo session is not valid (%s); "
                    "will keep retrying silently until it recovers",
                    exc,
                )
            return
        except Exception as exc:
            self.logger.warning("Comment reconciler run failed: %s", exc)
            return
        if self._session_dead:
            self._session_dead = False
            self.logger.info("Comment reconciler: Gengo session recovered")


__all__ = ["CommentReconciler"]
