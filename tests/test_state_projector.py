import logging
from unittest.mock import MagicMock, patch

from gengowatcher.events import EventEnvelope
from gengowatcher.state import AppState
from gengowatcher.state_projector import (
    StateProjector,
    workbench_details,
    workbench_start,
    workbench_status,
    workbench_visible,
)


def _state(tmp_path):
    return AppState(
        logger=logging.getLogger("test_state_projector"),
        state_file_path=tmp_path / "state.json",
    )


def test_workbench_visible_publishes_only_on_change(tmp_path):
    app_state = _state(tmp_path)
    event = EventEnvelope(
        type="browser.workbench.visible",
        source="native_browser_listener",
        payload={"url": "https://gengo.com/t/workbench/123#!/"},
        collection_id="123",
    )

    with patch("gengowatcher.state_projector.publish_event") as publish:
        workbench_visible(event, app_state)
        workbench_visible(event, app_state)

    publish.assert_called_once()
    job = app_state.get_job("123")
    assert job["workbench_visible"] is True
    assert job["acceptance_state"] == "visible"


def test_workbench_details_exposes_collected_browser_data(tmp_path):
    app_state = _state(tmp_path)
    event = EventEnvelope(
        type="browser.workbench.details",
        source="native_browser_listener",
        payload={
            "normalized": {
                "order_id": 98765,
                "reward": 8.13,
                "lc_src": "ja",
                "lc_tgt": "en",
                "unit_count": 263,
                "allotted_seconds": 7200,
                "seconds_left": 7190,
                "job_ids": [111, 222],
                "segments": [{"source_content": "Source text"}],
                "source_text": "Source text",
            }
        },
        collection_id="123",
    )

    with patch("gengowatcher.state_projector.publish_event") as publish:
        workbench_details(event, app_state)
        workbench_details(event, app_state)

    publish.assert_called_once()
    job = app_state.get_job("123")
    assert job["order_id"] == 98765
    assert job["reward"] == 8.13
    assert job["lang_pair"] == "JA->EN"
    assert job["word_count"] == 263
    assert job["allotted_seconds"] == 7200
    assert job["source_char_count"] == len("Source text")
    assert job["segment_count"] == 1
    assert job["job_ids"] == ["111", "222"]


def test_workbench_status_updates_countdown_and_notifies_thresholds_once(tmp_path):
    app_state = _state(tmp_path)
    notifier = MagicMock()
    projector = StateProjector(app_state, notifier=notifier)

    projector.project(
        EventEnvelope(
            type="browser.workbench.details",
            source="native_browser_listener",
            payload={
                "normalized": {
                    "allotted_seconds": 7200,
                    "seconds_left": 7200,
                }
            },
            collection_id="123",
        )
    )

    status = EventEnvelope(
        type="browser.workbench.status",
        source="native_browser_listener",
        payload={"seconds_left": 3600},
        collection_id="123",
    )
    with patch("gengowatcher.state_projector.publish_event") as publish:
        workbench_status(status, app_state, notifier=notifier)
        workbench_status(status, app_state, notifier=notifier)

    publish.assert_called_once()
    assert notifier.show_notification.call_count == 2
    job = app_state.get_job("123")
    assert job["seconds_left"] == 3600
    assert job["countdown_elapsed_seconds"] == 3600
    assert job["countdown_alerts"] == ["half_complete", "one_hour_elapsed"]
    # Regression: workbench_status should not downgrade acceptance_state
    assert job["acceptance_state"] == "details_visible"

    low_status = EventEnvelope(
        type="browser.workbench.status",
        source="native_browser_listener",
        payload={"seconds_left": 600},
        collection_id="123",
    )
    workbench_status(low_status, app_state, notifier=notifier)
    assert notifier.show_notification.call_count == 3
    assert "running_low" in app_state.get_job("123")["countdown_alerts"]


def test_workbench_start_event_uses_persisted_accepted_at(tmp_path):
    app_state = _state(tmp_path)
    event = EventEnvelope(
        type="browser.workbench.start_response",
        source="native_browser_listener",
        payload={"order_id": "123"},
        collection_id="123",
    )

    with patch("gengowatcher.state_projector.publish_event") as publish:
        workbench_start(event, app_state)

    stored = app_state.get_job("123")
    published = publish.call_args.args[0]
    assert published.payload["accepted_at"] == stored["accepted_at"]
