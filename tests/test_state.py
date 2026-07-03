import pytest
from gengowatcher import state
import logging
import os
import collections
import time


def pytest_configure(config):
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler()],
    )
    logging.getLogger().setLevel(logging.DEBUG)


@pytest.fixture(autouse=True)
def debug_test_start_and_end(request):
    logging.debug(f"\n--- START TEST: {request.node.name} ---")
    yield
    logging.debug(f"--- END TEST: {request.node.name} ---\n")


@pytest.fixture
def temp_state_file(tmp_path):
    """Provides a temporary file path for state tests."""
    return tmp_path / "state.json"


def test_appstate_initialization(temp_state_file):
    """Test that AppState initializes with default values."""
    assert hasattr(state, "AppState")
    app_state = state.AppState(
        logger=logging.getLogger("test"), state_file_path=temp_state_file
    )
    assert hasattr(app_state, "save_state")
    assert hasattr(app_state, "_load_state")
    assert app_state.last_seen_link is None
    assert app_state.total_new_entries_found == 0


def test_save_and_load_state(temp_state_file):
    """Test that state is correctly saved to and loaded from a file."""
    logger = logging.getLogger("test")
    app_state = state.AppState(logger=logger, state_file_path=temp_state_file)
    app_state.last_seen_link = "http://example.com/job1"
    app_state.total_new_entries_found = 42
    app_state.seen_job_ids.extend([101, 102, 103])
    app_state.save_state()

    app_state2 = state.AppState(logger=logger, state_file_path=temp_state_file)
    assert app_state2.last_seen_link == "http://example.com/job1"
    assert app_state2.total_new_entries_found == 42
    assert isinstance(app_state2.seen_job_ids, collections.deque)
    assert list(app_state2.seen_job_ids) == [101, 102, 103]


def test_corrupted_state_file(temp_state_file):
    """Test that the app handles a corrupted or invalid state file gracefully."""
    with open(temp_state_file, "w", encoding="utf-8") as f:
        f.write("this is not valid json")
    logger = logging.getLogger("test")
    app_state = state.AppState(logger=logger, state_file_path=temp_state_file)
    assert app_state.last_seen_link is None
    assert app_state.total_new_entries_found == 0


def test_mark_job_accepted_stores_workbench_payload_and_countdown(temp_state_file):
    logger = logging.getLogger("test")
    app_state = state.AppState(logger=logger, state_file_path=temp_state_file)
    app_state.add_job(
        {
            "id": "8012055",
            "title": "Japanese > English",
            "reward": 12.62,
            "url": "https://gengo.com/t/jobs/details/8012055",
            "timestamp": time.time(),
            "source": "rss",
        }
    )
    expire_ms = int((time.time() + 600) * 1000)
    accepted_workbench = {
        "source": "window.__GENGO_WORKBENCH_DATA__",
        "payload": {
            "summary": {
                "order_id": 8012055,
                "expire_time": expire_ms,
                "seconds_left": 600,
                "allotted_seconds": 6360,
                "rewards_total": 12.62,
                "unit_count": 263,
                "lc_src": "ja",
                "lc_tgt": "en",
            },
            "jobs": [
                {
                    "id": 98936958,
                    "segments": [
                        {
                            "segment_id": "98936958",
                            "source_content": "First paragraph.\nSecond paragraph.",
                            "target_content": "",
                            "hasErrors": False,
                            "hasWarnings": True,
                            "glossary": [],
                        }
                    ],
                }
            ],
        },
    }

    assert app_state.mark_job_accepted(
        "8012055",
        accepted_workbench=accepted_workbench,
        workbench_url="https://gengo.com/t/workbench/8012055",
    )

    [job] = app_state.get_recent_jobs(limit=1)
    assert job["accepted"] is True
    assert job["accepted_order_id"] == 8012055
    assert job["accepted_unit_count"] == 263
    assert job["accepted_reward_total"] == 12.62
    assert 0 < job["accepted_seconds_left"] <= 600
    assert job["accepted_time_left"]
    assert job["workbench_url"] == "https://gengo.com/t/workbench/8012055"
    assert job["accepted_job_ids"] == ["98936958"]
    assert job["accepted_workbench_job_count"] == 1
    assert job["accepted_segment_count"] == 1
    assert job["accepted_segments"][0]["source_content"] == (
        "First paragraph.\nSecond paragraph."
    )
    assert job["accepted_segments"][0]["has_warnings"] is True
    assert job["accepted_source_text"] == "First paragraph.\nSecond paragraph."
    assert job["accepted_source_char_count"] == len(job["accepted_source_text"])
    assert job["accepted_target_text"] == ""
    assert job["accepted_target_char_count"] == 0


def test_get_and_update_job_match_accepted_sub_job_ids(temp_state_file):
    logger = logging.getLogger("test")
    app_state = state.AppState(logger=logger, state_file_path=temp_state_file)
    app_state.add_job(
        {
            "id": "collection-1",
            "title": "Japanese > English",
            "job_ids": ["api-sub-job"],
            "accepted_job_ids": ["accepted-sub-job"],
            "timestamp": time.time(),
        }
    )

    assert app_state.get_job("accepted-sub-job")["id"] == "collection-1"
    assert app_state.update_job("accepted-sub-job", {"acceptance_state": "accepted"})
    assert app_state.get_job("collection-1")["acceptance_state"] == "accepted"


def test_upsert_browser_job_details_merges_by_order_or_job_id(temp_state_file):
    logger = logging.getLogger("test")
    app_state = state.AppState(logger=logger, state_file_path=temp_state_file)
    app_state.add_job(
        {
            "id": "api-row",
            "order_id": "341",
            "job_ids": ["989"],
            "title": "Japanese > English",
            "timestamp": time.time(),
            "source": "api",
        }
    )

    workbench_payload = {
        "source": "window.__INITIAL_STATE__",
        "payload": {
            "summary": {
                "order_id": 341,
                "seconds_left": 120,
                "allotted_seconds": 600,
            },
            "jobs": [{"id": "989", "segments": [{"text": "hello"}]}],
        },
    }

    assert app_state.upsert_browser_job_details(
        collection_id="workbench-341",
        order_id="341",
        job_ids=["989"],
        workbench_payload=workbench_payload,
        workbench_url="https://gengo.com/t/workbench/workbench-341",
    )

    assert app_state.get_job_count() == 1
    job = app_state.get_job("api-row")
    assert job["accepted"] is True
    assert job["lifecycle_state"] == "accepted"
    assert job["accepted_order_id"] == 341
    assert job["accepted_job_ids"] == ["989"]
    assert job["accepted_source_text"] == "hello"
    assert app_state.get_job("989")["id"] == "api-row"


def test_upsert_browser_job_details_creates_accepted_row_with_metadata(
    temp_state_file,
):
    logger = logging.getLogger("test")
    app_state = state.AppState(logger=logger, state_file_path=temp_state_file)
    workbench_payload = {
        "source": "window.__INITIAL_STATE__",
        "payload": {
            "order": {
                "order": "341",
                "left": 120,
                "allotted_seconds": 600,
            },
            "jobs": [{"id": "989", "segments": [{"text": "hello"}]}],
        },
    }

    assert app_state.upsert_browser_job_details(
        collection_id="workbench-341",
        workbench_payload=workbench_payload,
        workbench_url="https://gengo.com/t/workbench/workbench-341",
    )

    job = app_state.get_job("workbench-341")
    assert job["accepted"] is True
    assert job["accepted_at"] > 0
    assert job["lifecycle_state"] == "accepted"
    assert job["accepted_order_id"] == 341
    assert job["accepted_seconds_left_at_capture"] == 120
    assert 0 < job["accepted_seconds_left"] <= 120
    assert job["accepted_time_left"]
    assert job["accepted_job_ids"] == ["989"]
    assert job["accepted_workbench_job_count"] == 1
    assert job["accepted_segment_count"] == 1
    assert job["accepted_source_text"] == "hello"
    assert job["accepted_source_char_count"] == len("hello")


def test_update_job_returns_false_when_fields_are_unchanged(temp_state_file):
    logger = logging.getLogger("test")
    app_state = state.AppState(logger=logger, state_file_path=temp_state_file)
    app_state.add_job(
        {
            "id": "8012055",
            "title": "Japanese > English",
            "reward": 12.62,
            "url": "https://gengo.com/t/jobs/details/8012055",
            "timestamp": time.time(),
            "source": "rss",
            "acceptance_state": "visible",
        }
    )

    assert app_state.update_job("8012055", {"acceptance_state": "visible"}) is False
    assert app_state.update_job("8012055", {"acceptance_state": "accepted"}) is True


def test_upsert_browser_observation_creates_visible_job(temp_state_file):
    logger = logging.getLogger("test")
    app_state = state.AppState(logger=logger, state_file_path=temp_state_file)

    assert app_state.upsert_browser_observation(
        "34178123",
        {
            "workbench_visible": True,
            "workbench_url": "https://gengo.com/t/workbench/34178123#!/",
            "acceptance_state": "visible",
        },
    )
    assert not app_state.upsert_browser_observation(
        "34178123",
        {
            "workbench_visible": True,
            "workbench_url": "https://gengo.com/t/workbench/34178123#!/",
            "acceptance_state": "visible",
        },
    )

    job = app_state.get_job("34178123")
    assert job["source"] == "Browser"
    assert job["workbench_visible"] is True
    assert job["acceptance_state"] == "visible"
