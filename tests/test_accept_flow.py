import pytest

from gengowatcher.browser_worker.flows.accept_flow import (
    extract_workbench_payload,
    is_workbench_url,
    normalize_workbench_envelope,
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


def test_normalize_workbench_envelope_accepts_gengo_shape():
    payload = {
        "source": "window.__GENGO_WORKBENCH_DATA__",
        "payload": {
            "summary": {
                "order_id": 8012055,
                "expire_time": 1782760306560,
                "seconds_left": 6344,
            },
            "jobs": [{"id": 98936958, "unit_count": 263}],
        },
    }

    assert normalize_workbench_envelope(payload) == payload


@pytest.mark.asyncio
async def test_extract_workbench_payload_uses_page_visible_data():
    payload = {
        "source": "window.__GENGO_WORKBENCH_DATA__",
        "payload": {
            "summary": {"order_id": 8012055, "seconds_left": 6344},
            "jobs": [{"id": 98936958}],
        },
    }

    class FakePage:
        async def evaluate(self, _script):
            return payload

    assert await extract_workbench_payload(FakePage()) == payload
