from pathlib import Path

from tests.helpers.fake_browser_runtime import FakeRuntime


def test_swap_commit_gated_on_cancel_reload_start():
    runtime = FakeRuntime(
        fixtures_dir=Path("tests/fixtures/gengo"),
    )

    runtime.prepare_candidate(job_id="34046576")

    assert runtime.can_commit_candidate() is False

    runtime.click_cancel()

    assert runtime.can_commit_candidate() is True
    assert runtime.loaded_fixture == "cancel_reload_state.html"


def test_simulated_accept_lands_on_workbench_fixture():
    runtime = FakeRuntime(
        fixtures_dir=Path("tests/fixtures/gengo"),
    )

    runtime.prepare_candidate(job_id="34046576")
    runtime.click_accept()

    assert runtime.current_candidate_url == "https://gengo.com/t/workbench/34046576"
    assert runtime.loaded_fixture == "workbench_success.html"
