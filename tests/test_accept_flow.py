from gengowatcher.browser_worker.flows.accept_flow import (
    is_workbench_url,
    parse_workbench_job_id,
)


def test_is_workbench_url_detects_success_destination():
    assert is_workbench_url("https://gengo.com/t/workbench/34046576#!/") is True
    assert is_workbench_url("https://gengo.com/t/jobs/details/34046576") is False


def test_parse_workbench_job_id_extracts_expected_identifier():
    assert (
        parse_workbench_job_id("https://gengo.com/t/workbench/34046576#!/")
        == "34046576"
    )
