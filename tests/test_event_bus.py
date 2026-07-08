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
