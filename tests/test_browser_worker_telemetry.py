import json

from gengowatcher.browser_worker.telemetry import BrowserWorkerTelemetry, TimingEvent


def test_timing_event_serializes_to_json_safe_dict():
    event = TimingEvent(name="accept_click", monotonic_ms=123.4)

    payload = event.to_dict()

    assert payload["name"] == "accept_click"
    assert payload["monotonic_ms"] == 123.4


def test_telemetry_appends_jsonl_events(tmp_path):
    telemetry = BrowserWorkerTelemetry(log_path=tmp_path / "worker.jsonl")
    telemetry.record(TimingEvent(name="candidate_ready", monotonic_ms=50.0))

    payload = json.loads(telemetry.log_path.read_text(encoding="utf-8").strip())

    assert payload["event"]["name"] == "candidate_ready"
