from gengowatcher import tui_store
from gengowatcher.tui_store import TuiStore


def test_countdown_pruning_keeps_most_recent_entries(monkeypatch):
    ticks = iter(range(1000, 1100))
    monkeypatch.setattr(tui_store.time, "time", lambda: next(ticks))

    store = TuiStore()

    store.update_from_event(
        {
            "type": "browser.workbench.status",
            "payload": {"collection_id": "z-old", "seconds_left": 999},
        }
    )
    for index in range(50):
        store.update_from_event(
            {
                "type": "browser.workbench.status",
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
