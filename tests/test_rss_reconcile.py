import logging

from gengowatcher.orchestration.watcher_feed import (
    process_feed_entries,
    reconcile_rss_available_jobs,
)
from gengowatcher.state import AppState


class _FeedWatcher:
    def __init__(self, state, logger):
        self.state = state
        self.logger = logger
        self.processed = []

    def _log_all_entries(self, entries):
        return None

    def _extract_reward(self, entry):
        return 1.0

    def _process_new_job(self, job_id, title, reward, url, source="RSS", source_meta=None):
        self.processed.append(job_id)
        self.state.add_job(
            {
                "id": str(job_id),
                "title": title,
                "reward": reward,
                "currency": "USD",
                "url": url,
                "timestamp": 1.0,
                "source": source,
                "lifecycle_state": "detected",
                "workflow_state": "new",
            }
        )


def _state(tmp_path, logger):
    return AppState(logger=logger, state_file_path=tmp_path / "state.json")


def test_empty_feed_marks_stale_rss_jobs_gone(tmp_path):
    logger = logging.getLogger("test_rss_reconcile")
    state = _state(tmp_path, logger)
    state.add_job(
        {
            "id": "34132577",
            "title": "Old RSS job",
            "reward": 0.98,
            "currency": "USD",
            "url": "https://gengo.com/t/jobs/details/34132577?referral=rss",
            "timestamp": 1.0,
            "source": "RSS",
        }
    )
    watcher = _FeedWatcher(state, logger)

    changed = reconcile_rss_available_jobs(watcher, [])

    assert changed == 1
    job = state.get_job("34132577")
    assert job["lifecycle_state"] == "gone"
    assert job["workflow_state"] == "gone"


def test_live_feed_keeps_current_rss_job_and_drops_missing(tmp_path):
    logger = logging.getLogger("test_rss_reconcile")
    state = _state(tmp_path, logger)
    for job_id in ("100", "200"):
        state.add_job(
            {
                "id": job_id,
                "title": f"Job {job_id}",
                "reward": 1.0,
                "currency": "USD",
                "url": f"https://gengo.com/t/jobs/details/{job_id}",
                "timestamp": 1.0,
                "source": "RSS",
                "lifecycle_state": "detected",
                "workflow_state": "new",
            }
        )
    watcher = _FeedWatcher(state, logger)
    state.last_seen_rss_link = "https://gengo.com/t/jobs/details/100"

    process_feed_entries(
        watcher,
        [{"title": "Job 100", "link": "https://gengo.com/t/jobs/details/100"}],
    )

    assert state.get_job("100")["lifecycle_state"] == "detected"
    assert state.get_job("200")["lifecycle_state"] == "gone"
    assert watcher.processed == []


def test_reconcile_does_not_mark_accepted_or_browser_jobs(tmp_path):
    logger = logging.getLogger("test_rss_reconcile")
    state = _state(tmp_path, logger)
    state.add_job(
        {
            "id": "300",
            "title": "Accepted RSS",
            "reward": 5.0,
            "currency": "USD",
            "url": "https://gengo.com/t/jobs/details/300",
            "timestamp": 1.0,
            "source": "RSS",
            "accepted": True,
            "lifecycle_state": "accepted",
        }
    )
    state.add_job(
        {
            "id": "400",
            "title": "Browser job",
            "reward": 5.0,
            "currency": "USD",
            "url": "https://gengo.com/t/workbench/400",
            "timestamp": 1.0,
            "source": "Browser",
            "lifecycle_state": "observed",
        }
    )
    watcher = _FeedWatcher(state, logger)

    assert reconcile_rss_available_jobs(watcher, []) == 0
    assert state.get_job("300")["lifecycle_state"] == "accepted"
    assert state.get_job("400")["lifecycle_state"] == "observed"


def test_gone_rss_job_returns_when_it_reappears(tmp_path):
    logger = logging.getLogger("test_rss_reconcile")
    state = _state(tmp_path, logger)
    state.add_job(
        {
            "id": "500",
            "title": "Returned job",
            "reward": 2.0,
            "currency": "USD",
            "url": "https://gengo.com/t/jobs/details/500",
            "timestamp": 1.0,
            "source": "RSS",
            "lifecycle_state": "gone",
            "workflow_state": "gone",
        }
    )
    watcher = _FeedWatcher(state, logger)

    reconcile_rss_available_jobs(
        watcher,
        [{"title": "Returned job", "link": "https://gengo.com/t/jobs/details/500"}],
    )

    job = state.get_job("500")
    assert job["lifecycle_state"] == "detected"
    assert job["workflow_state"] == "new"
