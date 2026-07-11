"""WebSocket debug and browser-worker telemetry helpers from GengoWatcher.

Owns the raw-message capture buffer and the small telemetry-event
fan-out. The watcher keeps thin delegators for backward compat with
tests that patch the GengoWatcher.<method> name, but the actual
implementations live here.
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import TYPE_CHECKING

from .watcher_debug import (
    redact_raw_ws_text as _redact_raw_ws_text,
    redact_raw_ws_value as _redact_raw_ws_value,
)

if TYPE_CHECKING:
    from .watcher import GengoWatcher


def capture_raw_ws_message(
    watcher: "GengoWatcher",
    message: str,
    direction: str = "recv",
) -> None:
    """Capture one raw WebSocket message into the watcher's debug buffer.

    Pretty-formats JSON when possible, falls back to ``str(message)``
    after applying the redactor, and prepends an HH:MM:SS.mmm timestamp
    + an arrow indicating send (\u2192) or recv (\u2190).
    """
    # Only capture when the raw debug category is enabled.
    if not watcher.config.get("DebugCategories", "raw"):
        return
    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    prefix = "→" if direction == "send" else "←"

    try:
        parsed = json.loads(message)
        parsed = _redact_raw_ws_value(parsed)
        formatted = json.dumps(parsed, indent=2)
    except (json.JSONDecodeError, TypeError):
        formatted = _redact_raw_ws_text(str(message))

    entry = f"[{timestamp}] {prefix} {formatted}"

    lock = getattr(watcher, "_raw_ws_lock", None)
    buffer = getattr(watcher, "_raw_ws_messages", None)
    if lock is None or buffer is None:
        return
    with lock:
        buffer.append(entry)


def get_raw_ws_messages(watcher: "GengoWatcher") -> list:
    """Return a snapshot copy of the raw WebSocket message buffer."""
    lock = getattr(watcher, "_raw_ws_lock", None)
    buffer = getattr(watcher, "_raw_ws_messages", None)
    if lock is None or buffer is None:
        return []
    with lock:
        return list(buffer)


def clear_raw_ws_messages(watcher: "GengoWatcher") -> None:
    """Clear the raw WebSocket message buffer in place."""
    lock = getattr(watcher, "_raw_ws_lock", None)
    buffer = getattr(watcher, "_raw_ws_messages", None)
    if lock is None or buffer is None:
        return
    with lock:
        buffer.clear()


def handle_browser_worker_telemetry_line(
    watcher: "GengoWatcher",
    line: str,
) -> None:
    """Parse one NDJSON line of browser-worker telemetry.

    Silently ignores lines that cannot be parsed. Dispatches dict
    payloads to :func:`handle_browser_worker_telemetry_payload`.
    """
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        if watcher.logger.isEnabledFor(logging.DEBUG):
            watcher.logger.debug(
                "Ignoring malformed browser worker telemetry line"
            )
        return
    if isinstance(payload, dict):
        handle_browser_worker_telemetry_payload(watcher, payload)


def handle_browser_worker_telemetry_payload(
    watcher: "GengoWatcher",
    event_payload: dict,
) -> None:
    """Fan-out a parsed browser-worker telemetry event.

    Calls ``state.mark_job_accepted`` for accepted workbench payloads
    and emits the corresponding ``job.accepted`` webhook/api events.
    Other event names are ignored.
    """
    event = event_payload.get("event")
    if not isinstance(event, dict):
        return
    if event.get("name") != "accepted_workbench_payload":
        return

    payload = event_payload.get("payload")
    if not isinstance(payload, dict):
        return

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    job_id = str(
        event_payload.get("job_id") or summary.get("order_id") or ""
    ).strip()
    if not job_id:
        return

    accepted_workbench = {
        "source": str(event_payload.get("source") or "browser_worker"),
        "payload": payload,
    }
    updated = watcher.state.mark_job_accepted(
        job_id,
        accepted_workbench=accepted_workbench,
        workbench_url=event_payload.get("url"),
    )
    if updated:
        watcher.state.save_state()
        current_job = watcher.state.get_job(job_id)
        accepted_job = (
            current_job
            if isinstance(current_job, dict)
            else {
                "id": job_id,
                "workbench_url": event_payload.get("url"),
                "accepted_workbench": accepted_workbench,
                "source": "browser_worker",
            }
        )
        watcher.logger.info(
            "Browser worker captured accepted job %s; countdown tracking updated",
            job_id,
        )
        watcher._emit_webhook_event(
            "job.accepted",
            {
                "id": job_id,
                "workbench_url": event_payload.get("url"),
                "accepted_workbench": accepted_workbench,
                "source": "browser_worker",
            },
        )
        watcher._emit_api_event("job.accepted", accepted_job)
    else:
        watcher.logger.debug(
            "Browser worker captured accepted job %s but no stored job matched",
            job_id,
        )


__all__ = [
    "capture_raw_ws_message",
    "get_raw_ws_messages",
    "clear_raw_ws_messages",
    "handle_browser_worker_telemetry_line",
    "handle_browser_worker_telemetry_payload",
]
