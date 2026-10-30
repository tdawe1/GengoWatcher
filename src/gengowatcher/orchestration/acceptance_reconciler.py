"""Reconcile Gengo dashboard "Incomplete jobs" with locally recorded acceptances.

GengoWatcher normally learns about an acceptance from the browser worker's
workbench ``/start`` response. That misses file jobs (accepted on
``/t/jobs/details/{cid}``), jobs accepted from another device, and anything
accepted while the watcher was down. ``AcceptanceReconciler`` periodically
lists the translator dashboard's in-progress collections and replays a
``job.accepted`` (``acceptance_source = "dashboard_reconcile"``) for every
collection the app state does not already record as accepted.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Mapping

from gengowatcher.workbench_client import WorkbenchSessionDeadError

ACCEPTANCE_SOURCE = "dashboard_reconcile"
DEFAULT_WORKBENCH_BASE_URL = "https://gengo.com"
DEFAULT_INITIAL_DELAY_SEC = 5.0


def _is_accepted(job: Mapping[str, Any] | None) -> bool:
    if not isinstance(job, Mapping):
        return False
    return bool(job.get("accepted")) or job.get("acceptance_state") == "accepted"


class AcceptanceReconciler:
    """Poll the Gengo dashboard and emit acceptances GengoWatcher did not see."""

    def __init__(
        self,
        logger: logging.Logger,
        *,
        client_provider: Callable[[], Any],
        state: Any,
        on_accepted: Callable[[dict[str, Any]], None],
        interval_sec: float,
        workbench_base_url: str = DEFAULT_WORKBENCH_BASE_URL,
        initial_delay_sec: float = DEFAULT_INITIAL_DELAY_SEC,
    ) -> None:
        self.logger = logger
        self._client_provider = client_provider
        self._state = state
        self._on_accepted = on_accepted
        self.interval_sec = max(1.0, float(interval_sec))
        self.initial_delay_sec = max(0.0, float(initial_delay_sec))
        self._workbench_base_url = (
            workbench_base_url or DEFAULT_WORKBENCH_BASE_URL
        ).rstrip("/")
        self._lock = threading.RLock()
        self._reconciled: set[str] = set()
        self._session_dead = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ run

    def run_once(self) -> list[str]:
        """Reconcile one dashboard listing; return newly reconciled collection ids.

        Client errors (including ``WorkbenchSessionDeadError``) propagate to the
        caller; the background loop handles them.
        """
        with self._lock:
            client = self._client_provider()
            collections = client.list_incomplete_collections()
            base_url = self._base_url_for(client)
            reconciled: list[str] = []
            for item in collections:
                collection_id = str(getattr(item, "collection_id", "") or "").strip()
                if not collection_id or collection_id in self._reconciled:
                    continue
                if _is_accepted(self._state.get_job(collection_id)):
                    continue
                job_data = self._job_data(item, collection_id, base_url)
                try:
                    self._on_accepted(job_data)
                except Exception:
                    self.logger.exception(
                        "Acceptance reconciler failed to record collection %s; "
                        "retrying next round",
                        collection_id,
                    )
                    continue
                self._reconciled.add(collection_id)
                self._persist_acceptance(collection_id, job_data["workbench_url"])
                reconciled.append(collection_id)
                self.logger.info(
                    "Reconciled dashboard acceptance for collection %s",
                    collection_id,
                )
            return reconciled

    def _base_url_for(self, client: Any) -> str:
        client_base = getattr(client, "base_url", None)
        if isinstance(client_base, str) and client_base.strip():
            return client_base.strip().rstrip("/")
        return self._workbench_base_url

    @staticmethod
    def _job_data(item: Any, collection_id: str, base_url: str) -> dict[str, Any]:
        return {
            "id": collection_id,
            "collection_id": collection_id,
            # The dashboard "contents" column previews customer source text,
            # which must not travel in job.accepted events (webhooks, Matrix).
            "title": getattr(item, "lang_pair", "") or f"Collection {collection_id}",
            "reward": getattr(item, "reward", 0.0),
            "unit_count": getattr(item, "unit_count", 0),
            "lang_pair": getattr(item, "lang_pair", ""),
            "tier": getattr(item, "tier", ""),
            "url": getattr(item, "url", "")
            or f"{base_url}/t/jobs/details/{collection_id}",
            "workbench_url": f"{base_url}/t/workbench/{collection_id}",
            "accepted": True,
            "acceptance_source": ACCEPTANCE_SOURCE,
        }

    def _persist_acceptance(self, collection_id: str, workbench_url: str) -> None:
        """Record collections unknown to state so a restart does not replay them.

        ``on_accepted`` (``watcher._on_job_accepted``) only marks jobs that are
        already stored; dashboard-only collections would otherwise be emitted
        again by every new process.
        """
        try:
            if _is_accepted(self._state.get_job(collection_id)):
                return
            upsert = getattr(self._state, "upsert_browser_job_details", None)
            if not callable(upsert):
                return
            upsert(collection_id=collection_id, workbench_url=workbench_url)
            save = getattr(self._state, "save_state", None)
            if callable(save):
                save()
        except Exception:
            self.logger.exception(
                "Failed to persist reconciled acceptance for collection %s",
                collection_id,
            )

    # ------------------------------------------------------------ lifecycle

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="AcceptanceReconciler"
        )
        self._thread.start()
        self.logger.info(
            "Acceptance reconciler started (interval %.0fs)", self.interval_sec
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
        self.logger.info("Acceptance reconciler stopped.")

    def _run_guarded(self) -> None:
        try:
            self.run_once()
        except WorkbenchSessionDeadError as exc:
            if not self._session_dead:
                self._session_dead = True
                self.logger.warning(
                    "Acceptance reconciler: Gengo session is not valid (%s); "
                    "will keep retrying silently until it recovers",
                    exc,
                )
            return
        except Exception as exc:
            self.logger.warning("Acceptance reconciler run failed: %s", exc)
            return
        if self._session_dead:
            self._session_dead = False
            self.logger.info("Acceptance reconciler: Gengo session recovered")


__all__ = ["ACCEPTANCE_SOURCE", "AcceptanceReconciler"]
