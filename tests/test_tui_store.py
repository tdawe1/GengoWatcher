from gengowatcher import tui_store
from gengowatcher.tui_store import TuiStore


def test_countdown_pruning_keeps_most_recent_entries(monkeypatch):
    ticks = iter(range(1000, 1100))
    monkeypatch.setattr(tui_store.time, "time", lambda: next(ticks))

    store = TuiStore()

    store.update_from_event(
        {
            "type": "job.status",
            "payload": {"collection_id": "z-old", "seconds_left": 999},
        }
    )
    for index in range(50):
        store.update_from_event(
            {
                "type": "job.status",
                "payload": {
                    "collection_id": f"a-new-{index:02d}",
                    "seconds_left": index,
                },
            }
        )

    assert store.get_countdown("z-old") is None
    assert store.get_countdown("a-new-00") == 0
    assert store.get_countdown("a-new-49") == 49
    assert len(store._countdowns) == 50


def test_canonical_job_events_update_browser_health_and_countdown(monkeypatch):
    ticks = iter([2000, 2001])
    monkeypatch.setattr(tui_store.time, "time", lambda: next(ticks))

    store = TuiStore()

    store.update_from_event(
        {
            "type": "job.visible",
            "payload": {
                "collection_id": "123",
                "url": "https://gengo.com/t/workbench/123",
                "status": "visible",
            },
        }
    )
    store.update_from_event(
        {
            "type": "job.status",
            "payload": {
                "collection_id": "123",
                "seconds_left": 42,
                "status": "timed",
            },
        }
    )

    assert store.get_browser_health() == {
        "last_seen": 2000,
        "collection_id": "123",
        "status": "visible",
    }
    assert store.get_countdown("123") == 42
    assert store.get_workflow_state()["123"]["status"] == "timed"
    assert store.get_recent_jobs() == []


def test_accepted_jobs_use_collection_id_when_order_id_missing():
    store = TuiStore()

    store.update_from_event(
        {
            "type": "job.accepted",
            "collection_id": "collection-1",
            "payload": {"collection_id": "collection-1", "accepted": True},
        }
    )
    store.update_from_event(
        {
            "type": "job.accepted",
            "collection_id": "collection-2",
            "payload": {"collection_id": "collection-2", "accepted": True},
        }
    )

    active = {job["collection_id"] for job in store.get_active_jobs()}
    assert active == {"collection-1", "collection-2"}
