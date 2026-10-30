"""Tests for the customer-comment auto-revision poller."""

from __future__ import annotations

import logging

from gengowatcher.orchestration.comment_reconciler import CommentReconciler


class FakePipeline:
    def __init__(self, jobs: list[dict], new_comments: int = 1) -> None:
        self._jobs = jobs
        self._new_comments = new_comments
        self.checked: list[str] = []

    def list_jobs(self) -> list[dict]:
        return list(self._jobs)

    def check_comments(self, collection_id: str, *, background: bool = True) -> dict:
        self.checked.append(collection_id)
        return {"collection_id": collection_id, "new_comments": self._new_comments}


def _reconciler(pipeline: FakePipeline) -> CommentReconciler:
    return CommentReconciler(
        logging.getLogger("test-comment-reconciler"),
        pipeline=pipeline,
        interval_sec=60,
    )


def test_poller_checks_watchable_states_only() -> None:
    pipeline = FakePipeline(
        [
            {"collection_id": "1", "state": "ready_for_review"},
            {"collection_id": "2", "state": "translating"},
            {"collection_id": "3", "state": "archived", "archive_outcome": "Submitted"},
            {"collection_id": "4", "state": "archived", "archive_outcome": "Unsubmitted"},
            {"collection_id": "5", "state": "submitted"},
        ]
    )
    revised = _reconciler(pipeline).run_once()
    assert pipeline.checked == ["1", "3", "5"]
    assert revised == ["1", "3", "5"]


def test_poller_reports_nothing_without_new_comments() -> None:
    pipeline = FakePipeline(
        [{"collection_id": "1", "state": "ready_for_review"}], new_comments=0
    )
    assert _reconciler(pipeline).run_once() == []
    assert pipeline.checked == ["1"]
