from queue import Empty

import pytest

from gengowatcher import event_bus
from gengowatcher.events import EventEnvelope


def test_status_coalescing_keeps_countdown_changes():
    consumer_name = "test-status-coalescing"
    event_bus.unregister_consumer(consumer_name)
    queue = event_bus.register_consumer(consumer_name)

    try:
        event_bus.publish_event(
            EventEnvelope(
                type="job.status",
                source="test",
                collection_id="123",
                payload={"collection_id": "123", "seconds_left": 60},
            ),
            coalesce=True,
        )
        event_bus.publish_event(
            EventEnvelope(
                type="job.status",
                source="test",
                collection_id="123",
                payload={"collection_id": "123", "seconds_left": 60},
            ),
            coalesce=True,
        )
        event_bus.publish_event(
            EventEnvelope(
                type="job.status",
                source="test",
                collection_id="123",
                payload={"collection_id": "123", "seconds_left": 59},
            ),
            coalesce=True,
        )

        assert queue.get_nowait()["payload"]["seconds_left"] == 60
        assert queue.get_nowait()["payload"]["seconds_left"] == 59
        with pytest.raises(Empty):
            queue.get_nowait()
    finally:
        event_bus.unregister_consumer(consumer_name)


def test_native_status_events_coalesce_exact_duplicates():
    while not event_bus._NATIVE_EVENTS_QUEUE.empty():
        event_bus._NATIVE_EVENTS_QUEUE.get_nowait()
    event_bus._NATIVE_STATUS_LAST_SEEN.clear()

    event = EventEnvelope(
        type="browser.workbench.status",
        source="test",
        collection_id="123",
        payload={"seconds_left": 60, "status": "timed"},
    )
    event_bus.publish_native_event(event)
    event_bus.publish_native_event(event)

    assert event_bus._NATIVE_EVENTS_QUEUE.qsize() == 1


def test_clear_all_consumers_releases_registered_queues():
    event_bus.register_consumer("one")
    event_bus.register_consumer("two")

    event_bus.clear_all_consumers()

    assert event_bus._CONSUMERS == {}
    assert event_bus._coalesce_last_seen == {}
