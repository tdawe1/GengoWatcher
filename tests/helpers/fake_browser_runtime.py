from __future__ import annotations

from pathlib import Path

from gengowatcher.browser_worker.flows.accept_flow import workbench_url_for_job
from gengowatcher.browser_worker.flows.swap_flow import can_commit_candidate


class FakeRuntime:
    def __init__(self, fixtures_dir: Path | None = None):
        self.fixtures_dir = fixtures_dir
        self.cancel_navigation_started = False
        self.candidate_job_id: str | None = None
        self.current_candidate_url = "about:blank"
        self.loaded_fixture: str | None = None

    def prepare_candidate(self, job_id: str) -> None:
        self.candidate_job_id = job_id
        self.current_candidate_url = f"https://gengo.com/t/jobs/details/{job_id}"
        self.loaded_fixture = "job_details_ready.html"

    def click_cancel(self) -> None:
        self.cancel_navigation_started = True
        self.loaded_fixture = "cancel_reload_state.html"

    def can_commit_candidate(self) -> bool:
        return can_commit_candidate(
            cancel_navigation_started=self.cancel_navigation_started
        )

    def click_accept(self) -> None:
        if not self.candidate_job_id:
            raise RuntimeError("candidate job has not been prepared")
        self.current_candidate_url = workbench_url_for_job(self.candidate_job_id)
        self.loaded_fixture = "workbench_success.html"
