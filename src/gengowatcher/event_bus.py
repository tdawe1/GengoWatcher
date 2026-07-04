"""Nonblocking event bus for GengoWatcher.

Consumers: state, api, tui, workflow, audit
Rules:
- publish() never blocks browser listening
- Queues are bounded
- Noisy job.status events coalesced by collection_id
- Slow API/TUI consumers cannot stall watcher/browser threads
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable

from .events import EventEnvelope

logger = logging.getLogger(__name__)

# Bounded queues - prevent memory exhaustion
MAX_QUEUE_SIZE = 1000

# Consumer registry
_CONSUMERS: dict[str, queue.Queue] = {}
_CONSUMER_LOCK = threading.Lock()
_coalesce_last_seen: dict[str, dict[str, Any]] = {}


def publish_event(event: EventEnvelope, coalesce: bool = False) -> None:
    """Publish event to all registered consumers.

    Args:
        event: The event envelope to publish
        coalesce: If True, drop duplicate events by collection_id for status events
    """
    with _CONSUMER_LOCK:
        consumers = list(_CONSUMERS.items())

    event_dict = event.to_dict()

    for name, q in consumers:
        if coalesce and event.type == "job.status" and event.collection_id:
            # Use bus-owned state to check for recent duplicate
            # instead of peeking at queue internals
            should_skip = False
            with _CONSUMER_LOCK:
                last_seen = _coalesce_last_seen.get(name)
                if last_seen and last_seen.get("type") == event.type and last_seen.get("collection_id") == event.collection_id:
                    should_skip = True

            if should_skip:
                continue

        try:
            q.put_nowait(event_dict)
            with _CONSUMER_LOCK:
                _coalesce_last_seen[name] = {"type": event.type, "collection_id": event.collection_id}
        except queue.Full:
            logger.warning(f"Event queue full for consumer '{name}' - dropping event")


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
            logger.info(f"Unregistered event consumer: {name}")


def get_event_count(name: str | None = None) -> int:
    """Get event count for specific consumer or total."""
    with _CONSUMER_LOCK:
        if name:
            return _CONSUMERS.get(name, queue.Queue()).qsize()
        return sum(q.qsize() for q in _CONSUMERS.values())


def get_native_events_queue() -> queue.Queue:
    """Get the native browser listener internal queue (separate from consumer queues)."""
    return _NATIVE_EVENTS_QUEUE


# Internal queue for NativeBrowserListener -> StateProjector
_NATIVE_EVENTS_QUEUE: queue.Queue = queue.Queue(maxsize=100)


def publish_native_event(event: EventEnvelope) -> None:
    """Publish event to internal native browser queue (for state projector only)."""
    try:
        _NATIVE_EVENTS_QUEUE.put_nowait(event.to_dict())
    except queue.Full:
        logger.warning("Native events queue full - dropping event")