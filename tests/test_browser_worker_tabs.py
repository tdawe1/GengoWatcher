from gengowatcher.browser_worker.tabs import TabRoles


def test_tab_roles_always_define_hold_and_candidate_pages():
    roles = TabRoles(hold_page="hold", candidate_page="candidate")

    assert roles.hold_page == "hold"
    assert roles.candidate_page == "candidate"


def test_tab_roles_exposes_role_names():
    roles = TabRoles(hold_page="hold", candidate_page="candidate")

    assert roles.names() == ("hold_tab", "candidate_tab")
