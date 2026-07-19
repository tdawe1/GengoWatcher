"""Nonblocking event bus for GengoWatcher.

Consumers: state, api, tui, workflow, audit
Rules:
- publish() never blocks browser listening
- Queues are bounded
- Noisy job.status events coalesced by collection_id/status payload
- Slow API/TUI consumers cannot stall watcher/browser threads
"""

from __future__ import annotations

import logging
import queue
import threading
from collections import OrderedDict
from typing import Any

from .events import EventEnvelope

logger = logging.getLogger(__name__)

# Bounded queues - prevent memory exhaustion
MAX_QUEUE_SIZE = 1000
CRITICAL_EVENT_TYPES = {"job.accepted", "job.discovered", "job.details"}

# Internal queue for NativeBrowserListener -> StateProjector.
_NATIVE_EVENTS_QUEUE: queue.Queue = queue.Queue(maxsize=100)
_NATIVE_STATUS_LOCK = threading.Lock()
_NATIVE_STATUS_LAST_SEEN: OrderedDict[str, tuple[Any, ...]] = OrderedDict()

# Consumer registry
_CONSUMERS: dict[str, queue.Queue] = {}
_CONSUMER_LOCK = threading.Lock()
_coalesce_last_seen: dict[str, tuple[Any, ...]] = {}


def _coalesce_identity(event: EventEnvelope) -> tuple[Any, ...]:
    payload = event.payload or {}
    identity: list[Any] = [event.type, event.collection_id]
    if event.type == "job.status":
        identity.extend(
            [
                payload.get("seconds_left"),
                payload.get("elapsed_seconds"),
                payload.get("total_seconds"),
                tuple(payload.get("alerts") or ()),
                payload.get("status"),
            ]
        )
    return tuple(identity)


def publish_event(event: EventEnvelope, coalesce: bool = False) -> None:
    """Publish event to all registered consumers.

    Args:
        event: The event envelope to publish
        coalesce: If True, drop duplicate status events by collection/status payload
    """
    with _CONSUMER_LOCK:
        consumers = list(_CONSUMERS.items())

    event_dict = event.to_dict()

    coalesce_identity = _coalesce_identity(event)

    for name, q in consumers:
        if coalesce and event.type == "job.status" and event.collection_id:
            # Use bus-owned state to check for recent duplicate
            # instead of peeking at queue internals
            should_skip = False
            with _CONSUMER_LOCK:
                last_seen = _coalesce_last_seen.get(name)
                if last_seen == coalesce_identity:
                    should_skip = True

            if should_skip:
                continue

        try:
            if event.type in CRITICAL_EVENT_TYPES:
                q.put(event_dict, timeout=0.05)
            else:
                q.put_nowait(event_dict)
            with _CONSUMER_LOCK:
                _coalesce_last_seen[name] = coalesce_identity
        except queue.Full:
            logger.error(
                "Event queue full for consumer '%s' - dropping %s event",
                name,
                event.type,
            )


def register_consumer(name: str) -> queue.Queue:
    """Register a consumer and get its queue."""
    with _CONSUMER_LOCK:
        if name not in _CONSUMERS:
            _CONSUMERS[name] = queue.Queue(maxsize=MAX_QUEUE_SIZE)
            logger.info(f"Registered event consumer: {name}")
        return _CONSUMERS[name]


def unregister_consumer(name: str) -> None:
    """Unregister a consumer."""
    with _CONSUMER_LOCK:
        if name in _CONSUMERS:
            del _CONSUMERS[name]
            _coalesce_last_seen.pop(name, None)
            logger.info(f"Unregistered event consumer: {name}")


def clear_all_consumers() -> None:
    """Clear registered consumers and coalescing state for shutdown/tests."""
    with _CONSUMER_LOCK:
        _CONSUMERS.clear()
        _coalesce_last_seen.clear()


def get_event_count(name: str | None = None) -> int:
    """Get event count for specific consumer or total."""
    with _CONSUMER_LOCK:
        if name:
            return _CONSUMERS.get(name, queue.Queue()).qsize()
        return sum(q.qsize() for q in _CONSUMERS.values())


def get_native_events_queue() -> queue.Queue:
    """Get the native browser listener internal queue (separate from consumer queues)."""
    return _NATIVE_EVENTS_QUEUE


def publish_native_event(event: EventEnvelope) -> None:
    """Publish event to internal native browser queue (for state projector only)."""
    if event.type == "browser.workbench.status" and event.collection_id:
        payload = event.payload or {}
        identity = (
            payload.get("seconds_left"),
            payload.get("total_seconds"),
            payload.get("status"),
        )
        with _NATIVE_STATUS_LOCK:
            if _NATIVE_STATUS_LAST_SEEN.get(event.collection_id) == identity:
                return
            _NATIVE_STATUS_LAST_SEEN[event.collection_id] = identity
            _NATIVE_STATUS_LAST_SEEN.move_to_end(event.collection_id)
            while len(_NATIVE_STATUS_LAST_SEEN) > MAX_QUEUE_SIZE:
                _NATIVE_STATUS_LAST_SEEN.popitem(last=False)
    try:
        if event.type in {
            "browser.workbench.start_response",
            "browser.workbench.details",
        }:
            _NATIVE_EVENTS_QUEUE.put(event.to_dict(), timeout=0.05)
        else:
            _NATIVE_EVENTS_QUEUE.put_nowait(event.to_dict())
    except queue.Full:
        logger.error("Native events queue full - dropping %s event", event.type)
