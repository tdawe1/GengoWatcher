from gengowatcher.browser_worker.flows.swap_flow import can_commit_candidate


def test_candidate_commit_only_starts_after_cancel_navigation_begins():
    assert can_commit_candidate(cancel_navigation_started=True) is True
    assert can_commit_candidate(cancel_navigation_started=False) is False
