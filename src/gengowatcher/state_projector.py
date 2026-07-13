"""State projector - consumes browser/workflow events and mutates AppState.

Input events:
- workbench.visible → emits job.visible, upserts state
- workbench.details → emits job.details, stores normalized
- workbench.start_response → emits job.accepted, marks accepted
- workbench.status → emits job.status, updates countdown
- workbench.file_seen → emits job.file_pending/ready

Key rule: details alone does NOT mark accepted. Only start_response does.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from .events import EventEnvelope
from .event_bus import publish_event

if TYPE_CHECKING:
    from .state import AppState

logger = logging.getLogger(__name__)

ONE_HOUR_SECONDS = 3600
LOW_TIME_SECONDS = 600


def _clean_updates(updates: dict[str, Any]) -> dict[str, Any]:
    """Drop empty browser fields that should not overwrite known job data."""
    cleaned: dict[str, Any] = {}
    for key, value in updates.items():
        if value is None or value == "":
            continue
        if key == "reward":
            try:
                if float(value) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
        if key in {"job_ids", "segments"} and value == []:
            continue
        cleaned[key] = value
    return cleaned


def _browser_lang_pair(normalized: dict[str, Any]) -> str | None:
    src = str(normalized.get("lc_src") or "").strip().upper()
    tgt = str(normalized.get("lc_tgt") or "").strip().upper()
    if src and tgt:
        return f"{src}->{tgt}"
    return None


def _browser_details_updates(normalized: dict[str, Any]) -> dict[str, Any]:
    source_text = str(normalized.get("source_text") or "")
    segments = normalized.get("segments")
    segment_count = len(segments) if isinstance(segments, list) else None
    job_ids = normalized.get("job_ids")
    normalized_job_ids = (
        [str(job_id) for job_id in job_ids if job_id]
        if isinstance(job_ids, list)
        else None
    )
    return _clean_updates(
        {
            "workbench_payload": normalized,
            "reward": normalized.get("reward"),
            "lc_src": normalized.get("lc_src"),
            "lc_tgt": normalized.get("lc_tgt"),
            "lang_pair": _browser_lang_pair(normalized),
            "source_text": source_text,
            "source_char_count": len(source_text) if source_text else None,
            "segments": segments,
            "segment_count": segment_count,
            "unit_count": normalized.get("unit_count"),
            "allotted_seconds": normalized.get("allotted_seconds"),
            "word_count": normalized.get("unit_count"),
            "order_id": normalized.get("order_id"),
            "job_ids": normalized_job_ids,
            "tier": normalized.get("tier"),
            "purpose": normalized.get("purpose"),
            "seconds_left": normalized.get("seconds_left"),
        }
    )


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s"


def _countdown_total_seconds(job: dict[str, Any], seconds_left: int) -> int:
    for key in (
        "allotted_seconds",
        "accepted_allotted_seconds",
        "countdown_total_seconds",
        "countdown_initial_seconds",
    ):
        value = _coerce_int(job.get(key))
        if value is not None and value > 0:
            return max(value, seconds_left)
    return max(seconds_left, 0)


def _countdown_alerts_due(
    job: dict[str, Any],
    *,
    seconds_left: int,
    total_seconds: int,
) -> list[str]:
    fired = {
        str(value)
        for value in (job.get("countdown_alerts") or [])
        if str(value).strip()
    }
    due: list[str] = []
    elapsed = max(0, total_seconds - seconds_left)
    low_threshold = max(LOW_TIME_SECONDS, int(total_seconds * 0.1))

    if total_seconds > 0 and seconds_left <= total_seconds / 2:
        due.append("half_complete")
    if elapsed >= ONE_HOUR_SECONDS:
        due.append("one_hour_elapsed")
    if seconds_left <= low_threshold:
        due.append("running_low")

    return [label for label in due if label not in fired]


def _alert_message(
    label: str, collection_id: str, seconds_left: int
) -> tuple[str, str]:
    remaining = _format_duration(seconds_left)
    if label == "half_complete":
        return (
            "GengoWatcher Workbench 50%",
            f"Job {collection_id} is 50% complete. {remaining} left.",
        )
    if label == "one_hour_elapsed":
        return (
            "GengoWatcher Workbench 1h",
            f"Job {collection_id} has been open for 1 hour. {remaining} left.",
        )
    return (
        "GengoWatcher Workbench Low Time",
        f"Job {collection_id} is running low on time. {remaining} left.",
    )


def _notify_countdown_alert(
    notifier: object | None,
    *,
    label: str,
    collection_id: str,
    job: dict[str, Any],
    seconds_left: int,
) -> None:
    notify = getattr(notifier, "show_notification", None)
    if not callable(notify):
        return
    title, message = _alert_message(label, collection_id, seconds_left)
    try:
        notify(
            message=message,
            title=title,
            play_sound=True,
            open_link=False,
            url=job.get("workbench_url") or job.get("url"),
        )
    except Exception:
        logger.warning("Countdown alert notification failed", exc_info=True)


class StateProjector:
    """Projects events into persistent state + emits canonical job.* events."""

    def __init__(self, state: "AppState", notifier: object | None = None):
        self.state = state
        self.notifier = notifier

    def project(self, event: EventEnvelope) -> None:
        """Project event into state + emit canonical events to bus. Must be fast."""
        etype = event.type if isinstance(event.type, str) else str(event.type)
        if etype == "browser.workbench.visible":
            self._project_workbench_visible(event)
        elif etype == "browser.workbench.details":
            self._project_workbench_details(event)
        elif etype == "browser.workbench.start_response":
            self._project_workbench_start(event)
        elif etype == "browser.workbench.status":
            self._project_workbench_status(event)
        elif etype == "browser.workbench.file_seen":
            self._project_workbench_file(event)

    def _project_workbench_visible(self, event: EventEnvelope) -> None:
        workbench_visible(event, self.state)

    def _project_workbench_details(self, event: EventEnvelope) -> None:
        workbench_details(event, self.state)

    def _project_workbench_start(self, event: EventEnvelope) -> None:
        workbench_start(event, self.state)

    def _project_workbench_status(self, event: EventEnvelope) -> None:
        workbench_status(event, self.state, notifier=self.notifier)

    def _project_workbench_file(self, event: EventEnvelope) -> None:
        workbench_file(event, self.state)


def workbench_visible(event: EventEnvelope, state: "AppState") -> None:
    """Handle workbench becoming visible — update state + emit job.visible.

    Does NOT create/accept job yet — just records that workbench is visible.
    """
    payload = event.payload or {}
    collection_id = event.collection_id
    if not collection_id:
        return

    current = state.get_job(collection_id) or {}
    updates = {
        "workbench_visible": True,
        "workbench_url": payload.get("url"),
    }
    if current.get("acceptance_state") not in (
        "accepted",
        "details_visible",
        "requested",
    ):
        updates["acceptance_state"] = "visible"
    changed = state.upsert_browser_observation(collection_id, _clean_updates(updates))
    if not changed:
        return

    # Emit canonical job.visible event to bus
    publish_event(
        EventEnvelope(
            type="job.visible",
            source="state_projector",
            payload={
                "collection_id": collection_id,
                "url": payload.get("url"),
                "status": "visible",
            },
            collection_id=collection_id,
        )
    )


def workbench_details(event: EventEnvelope, state: "AppState") -> None:
    """Handle workbench details — store normalized payload, emit job.details.

    NOTE: details alone does NOT mark the job as accepted. Only
    browser.workbench.start_response evidence triggers acceptance.
    """
    payload = event.payload or {}
    collection_id = event.collection_id
    if not collection_id:
        return

    normalized = payload.get("normalized") or {}
    order_id = normalized.get("order_id")

    current = state.get_job(collection_id) or {}
    updates = _browser_details_updates(normalized)
    if current.get("acceptance_state") not in (
        "accepted",
        "details_visible",
        "requested",
    ):
        updates["acceptance_state"] = "details_visible"
    changed = state.upsert_browser_observation(collection_id, updates)
    if not changed:
        return

    # Emit canonical job.details event to bus
    reward = normalized.get("reward")
    lc_src = normalized.get("lc_src")
    lc_tgt = normalized.get("lc_tgt")
    source_text = normalized.get("source_text")
    seconds_left = normalized.get("seconds_left")
    publish_event(
        EventEnvelope(
            type="job.details",
            source="state_projector",
            payload={
                "collection_id": collection_id,
                "order_id": order_id,
                "reward": reward,
                "lc_src": lc_src,
                "lc_tgt": lc_tgt,
                "source_text": source_text,
                "seconds_left": seconds_left,
            },
            collection_id=collection_id,
        )
    )


def workbench_start(event: EventEnvelope, state: "AppState") -> None:
    """Handle workbench start response — this is the ONLY acceptance trigger.

    Emits job.accepted to the bus.
    """
    payload = event.payload or {}
    collection_id = event.collection_id
    if not collection_id:
        return

    current = state.get_job(collection_id) or {}
    changed = state.upsert_browser_job_details(
        collection_id=collection_id,
        workbench_payload=payload,
    )
    if not changed:
        return
    refreshed = state.get_job(collection_id) or current
    accepted_at = refreshed.get("accepted_at") or time.time()

    # Emit canonical job.accepted event to bus
    publish_event(
        EventEnvelope(
            type="job.accepted",
            source="state_projector",
            payload={
                "collection_id": collection_id,
                "accepted": True,
                "accepted_at": accepted_at,
            },
            collection_id=collection_id,
        )
    )


def workbench_status(
    event: EventEnvelope,
    state: "AppState",
    *,
    notifier: object | None = None,
) -> None:
    """Handle workbench status countdown — emit job.status."""
    payload = event.payload or {}
    collection_id = event.collection_id

    if collection_id and "seconds_left" in payload:
        seconds_left = _coerce_int(payload.get("seconds_left"))
        if seconds_left is None:
            return

        current = state.get_job(collection_id)
        if not current:
            return
        total_seconds = _countdown_total_seconds(current, seconds_left)
        elapsed_seconds = max(0, total_seconds - seconds_left)
        fired_alerts = {
            str(value)
            for value in (current.get("countdown_alerts") or [])
            if str(value).strip()
        }
        due_alerts = _countdown_alerts_due(
            current,
            seconds_left=seconds_left,
            total_seconds=total_seconds,
        )
        previous_seconds_left = _coerce_int(current.get("seconds_left"))
        if previous_seconds_left is None:
            previous_seconds_left = _coerce_int(current.get("accepted_seconds_left"))
        previous_total_seconds = _coerce_int(current.get("countdown_total_seconds"))
        if (
            previous_seconds_left == seconds_left
            and previous_total_seconds == total_seconds
            and not due_alerts
        ):
            return
        updated_alerts = sorted(fired_alerts.union(due_alerts))
        first_seen = current.get("countdown_started_at") or time.time()
        initial_seconds = (
            _coerce_int(current.get("countdown_initial_seconds")) or total_seconds
        )

        changed = state.upsert_browser_observation(
            collection_id,
            {
                "acceptance_state": (
                    "accepted"
                    if current.get("accepted")
                    else current.get("acceptance_state") or "visible"
                ),
                "seconds_left": seconds_left,
                "accepted_seconds_left": seconds_left,
                "accepted_seconds_left_at_capture": seconds_left,
                "accepted_payload_captured_at": time.time(),
                "countdown_started_at": first_seen,
                "countdown_initial_seconds": initial_seconds,
                "countdown_total_seconds": total_seconds,
                "countdown_elapsed_seconds": elapsed_seconds,
                "countdown_alerts": updated_alerts,
            },
        )
        if not changed:
            return

        refreshed_job = state.get_job(collection_id) or current
        for label in due_alerts:
            _notify_countdown_alert(
                notifier,
                label=label,
                collection_id=collection_id,
                job=refreshed_job,
                seconds_left=seconds_left,
            )

        # Emit canonical job.status event to bus
        publish_event(
            EventEnvelope(
                type="job.status",
                source="state_projector",
                payload={
                    "collection_id": collection_id,
                    "seconds_left": seconds_left,
                    "time_left": _format_duration(seconds_left),
                    "elapsed_seconds": elapsed_seconds,
                    "total_seconds": total_seconds,
                    "alerts": due_alerts,
                    "status": "timed",
                },
                collection_id=collection_id,
            )
        )


def workbench_file(event: EventEnvelope, state: "AppState") -> None:
    """Handle file operations — emit job.file_pending/ready."""
    payload = event.payload or {}
    collection_id = event.collection_id
    if not collection_id:
        return

    downloaded = payload.get("downloaded", False)
    # Use upsert_browser_observation to create job if missing (create-on-miss flow)
    changed = state.upsert_browser_observation(
        collection_id,
        {
            "file_pending": True,
            "file_ready": downloaded,
        },
    )
    if not changed:
        # Try update_job in case the job exists but nothing changed
        changed = state.update_job(
            collection_id,
            {
                "file_pending": True,
                "file_ready": downloaded,
            },
        )
    if not changed:
        return

    # Emit canonical file event
    file_type = "job.file_ready" if downloaded else "job.file_pending"
    publish_event(
        EventEnvelope(
            type=file_type,
            source="state_projector",
            payload={
                "collection_id": collection_id,
                "downloaded": downloaded,
            },
            collection_id=collection_id,
        )
    )
