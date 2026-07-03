from gengowatcher.workbench_payload import normalize_workbench_payload


def test_normalize_workbench_payload_accepts_order_left_and_text_aliases():
    raw = {
        "order": {"order": "341", "left": 120},
        "jobs": [{"segments": [{"text": "hello"}]}],
    }

    normalized = normalize_workbench_payload(raw)

    assert normalized["order_id"] == "341"
    assert normalized["seconds_left"] == 120
    assert normalized["source_text"] == "hello"


def test_normalize_workbench_payload_accepts_top_level_order_left_aliases():
    raw = {
        "order": "341",
        "left": 120,
        "jobs": [{"segments": [{"text": "hello"}]}],
    }

    normalized = normalize_workbench_payload(raw)

    assert normalized["order_id"] == "341"
    assert normalized["seconds_left"] == 120
    assert normalized["source_text"] == "hello"
