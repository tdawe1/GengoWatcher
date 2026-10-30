"""Tests for the dashboard acceptance reconciler."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

import pytest

from gengowatcher.orchestration.acceptance_reconciler import AcceptanceReconciler
from gengowatcher.state import AppState
from gengowatcher.workbench_client import WorkbenchError, WorkbenchSessionDeadError


@dataclass(frozen=True)
class FakeCollection:
    collection_id: str
    title: str = "Sample contents"
    lang_pair: str = "ja > en"
    tier: str = "pro"
    unit_count: int = 120
    reward: float = 9.6
    url: str = ""


class FakeClient:
    def __init__(self, items: list[FakeCollection], base_url: str = "http://sandbox"):
        self.items = items
        self.base_url = base_url
        self.error: Exception | None = None
        self.calls = 0

    def list_incomplete_collections(self) -> list[FakeCollection]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.items)


class FakeState:
    def __init__(self, jobs: dict[str, dict[str, Any]] | None = None):
        self.jobs = jobs or {}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(str(job_id))


def _reconciler(client, state, on_accepted, logger=None) -> AcceptanceReconciler:
    return AcceptanceReconciler(
        logger or logging.getLogger("test-reconciler"),
        client_provider=lambda: client,
        state=state,
        on_accepted=on_accepted,
        interval_sec=300,
    )


def test_new_incomplete_collection_is_emitted_once_with_exact_payload():
    client = FakeClient(
        [FakeCollection("101", url="http://sandbox/t/jobs/details/101")]
    )
    accepted: list[dict[str, Any]] = []
    reconciler = _reconciler(client, FakeState(), accepted.append)

    assert reconciler.run_once() == ["101"]
    assert accepted == [
        {
            "id": "101",
            "collection_id": "101",
            # Dashboard "contents" previews customer text: never the title.
            "title": "ja > en",
            "reward": 9.6,
            "unit_count": 120,
            "lang_pair": "ja > en",
            "tier": "pro",
            "url": "http://sandbox/t/jobs/details/101",
            "workbench_url": "http://sandbox/t/workbench/101",
            "accepted": True,
            "acceptance_source": "dashboard_reconcile",
        }
    ]

    assert reconciler.run_once() == []
    assert len(accepted) == 1


@pytest.mark.parametrize(
    "stored",
    [{"accepted": True}, {"accepted": False, "acceptance_state": "accepted"}],
)
def test_collection_already_accepted_in_state_is_skipped(stored):
    client = FakeClient([FakeCollection("202"), FakeCollection("203")])
    accepted: list[dict[str, Any]] = []
    reconciler = _reconciler(client, FakeState({"202": stored}), accepted.append)

    assert reconciler.run_once() == ["203"]
    assert [job["id"] for job in accepted] == ["203"]


def test_observed_but_unaccepted_job_in_state_is_reconciled():
    client = FakeClient([FakeCollection("204")])
    accepted: list[dict[str, Any]] = []
    state = FakeState({"204": {"accepted": False, "acceptance_state": "observed"}})

    assert _reconciler(client, state, accepted.append).run_once() == ["204"]


def test_on_accepted_failure_is_isolated_and_retried_next_round():
    client = FakeClient([FakeCollection("301"), FakeCollection("302")])
    calls: list[str] = []
    fail = {"301"}

    def on_accepted(job: dict[str, Any]) -> None:
        calls.append(job["id"])
        if job["id"] in fail:
            raise RuntimeError("boom")

    reconciler = _reconciler(client, FakeState(), on_accepted)

    assert reconciler.run_once() == ["302"]
    assert calls == ["301", "302"]

    fail.clear()
    assert reconciler.run_once() == ["301"]
    assert calls == ["301", "302", "301"]


def test_session_dead_warns_once_per_transition(caplog):
    client = FakeClient([FakeCollection("401")])
    client.error = WorkbenchSessionDeadError("session expired")
    logger = logging.getLogger("test-reconciler-dead")
    accepted: list[dict[str, Any]] = []
    reconciler = _reconciler(client, FakeState(), accepted.append, logger)

    def dead_warnings() -> int:
        return sum(
            "session is not valid" in record.getMessage()
            for record in caplog.records
            if record.levelno == logging.WARNING
        )

    with caplog.at_level(logging.INFO, logger=logger.name):
        for _ in range(3):
            reconciler._run_guarded()
        assert dead_warnings() == 1
        assert accepted == []

        client.error = None
        reconciler._run_guarded()
        assert [job["id"] for job in accepted] == ["401"]

        client.error = WorkbenchSessionDeadError("expired again")
        reconciler._run_guarded()
        reconciler._run_guarded()
        assert dead_warnings() == 2


def test_other_errors_warn_every_round_and_do_not_raise(caplog):
    client = FakeClient([])
    client.error = WorkbenchError("HTTP 500")
    logger = logging.getLogger("test-reconciler-error")
    reconciler = _reconciler(client, FakeState(), lambda job: None, logger)

    with caplog.at_level(logging.WARNING, logger=logger.name):
        reconciler._run_guarded()
        reconciler._run_guarded()

    warnings = [r for r in caplog.records if "run failed" in r.getMessage()]
    assert len(warnings) == 2


def test_dashboard_only_collection_is_persisted_so_restart_does_not_replay(tmp_path):
    state = AppState(
        logger=logging.getLogger("test-reconciler-state"),
        state_file_path=tmp_path / "state.json",
    )
    client = FakeClient([FakeCollection("501")])
    first: list[dict[str, Any]] = []

    assert _reconciler(client, state, first.append).run_once() == ["501"]
    stored = state.get_job("501")
    assert stored is not None and stored["accepted"] is True
    assert stored["workbench_url"] == "http://sandbox/t/workbench/501"

    reloaded = AppState(
        logger=logging.getLogger("test-reconciler-state"),
        state_file_path=tmp_path / "state.json",
    )
    second: list[dict[str, Any]] = []
    assert _reconciler(client, reloaded, second.append).run_once() == []
    assert second == []


def test_start_runs_after_initial_delay_and_stop_joins_thread():
    ran = threading.Event()

    class SignallingClient(FakeClient):
        def list_incomplete_collections(self):
            ran.set()
            return super().list_incomplete_collections()

    client = SignallingClient([FakeCollection("601")])
    accepted: list[dict[str, Any]] = []
    reconciler = AcceptanceReconciler(
        logging.getLogger("test-reconciler-thread"),
        client_provider=lambda: client,
        state=FakeState(),
        on_accepted=accepted.append,
        interval_sec=3600,
        initial_delay_sec=0.01,
    )

    reconciler.start()
    try:
        assert ran.wait(2.0)
        assert reconciler.is_running
    finally:
        reconciler.stop(timeout=2.0)

    assert not reconciler.is_running
    assert client.calls == 1
    assert [job["id"] for job in accepted] == ["601"]
