"""Alerting, API event dispatch, and JSON-safety helpers from GengoWatcher.

Helpers extracted from the god class so the orchestration logic in
``watcher.py`` doesn't absorb every side effect. Each function takes the
``watcher`` as its first argument and reads the bits it needs (``config``,
``logger``, ``_browser_jobs_refresh_event``, ``on_api_event_callback``)
directly from the instance.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..watcher import GengoWatcher


# Event types that should wake the BrowserJobs event-driven monitor.
_BROWSER_JOBS_REFRESH_EVENTS: frozenset[str] = frozenset(
    {"job.visible", "job.details", "job.discovered"}
)


def emit_api_event(
    watcher: "GengoWatcher",
    event_type: str,
    payload: dict,
) -> None:
    """Emit an in-process API websocket event without blocking monitors.

    Triggers the BrowserJobs event-driven refresh on workbench-visible
    events, then forwards the event to ``watcher.on_api_event_callback``
    if one was attached.
    """
    if event_type in _BROWSER_JOBS_REFRESH_EVENTS:
        trigger = getattr(watcher, "_browser_jobs_refresh_event", None)
        if trigger is not None:
            trigger.set()
    callback = getattr(watcher, "on_api_event_callback", None)
    if not callable(callback):
        return
    try:
        callback(event_type, dict(payload))
    except Exception:
        watcher.logger.exception(
            "Failed to publish API event %s for job %s",
            event_type,
            payload.get("id", payload.get("job_id", "unknown")),
        )


def json_safe(value):
    """Best-effort JSON-safe coercion of an arbitrary value.

    Used by watcher code that needs to embed untrusted job metadata into
    structured logs, webhook payloads, or queued alerts.
    """
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


__all__ = ["emit_api_event", "json_safe"]
