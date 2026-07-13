import json
import logging
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from gengowatcher.web import WebAPI, app, authenticator
from gengowatcher.webhooks import (
    OutboundWebhookTarget,
    WebhookAuditLogger,
    WebhookDispatcher,
    build_webhook_signature,
    verify_webhook_signature,
)


def _config(tmp_path, **overrides):
    values = {
        ("Paths", "file_storage_dir"): str(tmp_path / "files"),
        ("Paths", "all_entries_log"): str(tmp_path / "all_entries.csv"),
        ("Webhooks", "incoming_enabled"): True,
        ("Webhooks", "incoming_secret"): "incoming-secret",
        ("Webhooks", "require_signature"): True,
        ("Webhooks", "signature_tolerance_sec"): 300.0,
        ("Webhooks", "max_body_bytes"): 1024 * 1024,
        ("Webhooks", "max_seen_event_ids"): 1000,
        ("Webhooks", "debug_enabled"): True,
        ("Webhooks", "debug_payload_preview_bytes"): 4096,
        ("Webhooks", "audit_enabled"): True,
        ("Webhooks", "audit_log_path"): str(tmp_path / "webhooks.jsonl"),
        ("Webhooks", "audit_max_bytes"): 1024 * 1024,
        ("Webhooks", "audit_max_lines"): 5000,
        ("Webhooks", "outbound_enabled"): False,
        ("Webhooks", "outbound_urls"): [],
        ("Webhooks", "outbound_secret"): "",
        ("Webhooks", "outbound_auth_token"): "",
        ("Webhooks", "outbound_timeout_sec"): 5.0,
        ("Webhooks", "outbound_max_attempts"): 3,
        ("Webhooks", "outbound_initial_delay_sec"): 0.0,
        ("Webhooks", "outbound_max_delay_sec"): 0.0,
        ("Webhooks", "outbound_verify_tls"): True,
    }
    for key, value in overrides.items():
        if isinstance(key, tuple):
            values[key] = value
        else:
            values[("Webhooks", key)] = value
    config = MagicMock()
    config.get.side_effect = lambda section, key, **kwargs: values.get(
        (section, key),
        kwargs.get("fallback"),
    )
    config.config = {"Webhooks": {}}
    return config


def _signed_headers(raw_body: bytes, secret: str = "incoming-secret"):
    timestamp = str(int(time.time()))
    return {
        "X-GengoWatcher-Timestamp": timestamp,
        "X-GengoWatcher-Signature": build_webhook_signature(
            secret,
            raw_body,
            timestamp=timestamp,
        ),
        "X-Request-ID": "req-test-1",
    }


def _api(tmp_path, watcher=None, **config_overrides):
    config = _config(tmp_path, **config_overrides)
    state = MagicMock()
    logger = logging.getLogger("test.webhooks")
    watcher = watcher or MagicMock()
    watcher._process_new_job = MagicMock()
    return WebAPI(
        config,
        state,
        logger,
        watcher=watcher,
        start_watcher_thread=False,
    )


def test_verify_webhook_signature_accepts_timestamped_body():
    raw_body = b'{"id":"123"}'
    timestamp = str(int(time.time()))
    signature = build_webhook_signature(
        "secret",
        raw_body,
        timestamp=timestamp,
    )

    result = verify_webhook_signature(
        raw_body=raw_body,
        headers={
            "X-GengoWatcher-Timestamp": timestamp,
            "X-GengoWatcher-Signature": signature,
        },
        secret="secret",
    )

    assert result == "signature ok"


def test_verify_webhook_signature_rejects_missing_timestamp():
    """Replay attack: signed body but no timestamp header should be rejected."""
    raw_body = b'{"id":"123"}'
    signature = build_webhook_signature(
        "secret",
        raw_body,
        timestamp=None,
    )

    # No X-GengoWatcher-Timestamp header - should reject even when the
    # signature was generated over the raw body without a timestamp.
    from gengowatcher.webhooks import WebhookSignatureError

    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(
            raw_body=raw_body,
            headers={
                "X-GengoWatcher-Signature": signature,
            },
            secret="secret",
            require_signature=True,
        )


def test_incoming_job_webhook_routes_into_existing_watcher_pipeline(tmp_path):
    api = _api(tmp_path)
    payload = {
        "event_id": "evt-job-123",
        "event_type": "job.discovered",
        "job_id": "123",
        "title": "JA > EN | Short translation",
        "reward": 12.5,
        "url": "https://gengo.com/t/jobs/details/123",
        "source": "browser-extension",
        "metadata": {"debug_url": "https://gengo.com/t/jobs/status/available"},
    }
    raw_body = json.dumps(payload).encode("utf-8")

    response = api.process_incoming_job_webhook(raw_body, _signed_headers(raw_body))

    assert response["status"] == "processed"
    assert response["job_id"] == "123"
    assert response["debug"]["payload_sha256"]
    api.watcher._process_new_job.assert_called_once()
    args = api.watcher._process_new_job.call_args.args
    kwargs = api.watcher._process_new_job.call_args.kwargs
    assert args[:5] == (
        "123",
        "JA > EN | Short translation",
        12.5,
        "https://gengo.com/t/jobs/details/123",
        "Webhook:browser-extension",
    )
    assert kwargs["source_meta"]["webhook"]["event_id"] == "evt-job-123"

    audit_entries = api.get_webhook_audit_entries(10)
    assert [entry["stage"] for entry in audit_entries] == ["received", "processed"]
    assert audit_entries[-1]["payload_sha256"] == response["debug"]["payload_sha256"]


def test_incoming_job_webhook_emits_console_log_messages(tmp_path, caplog):
    api = _api(tmp_path)
    payload = {
        "event_id": "evt-log",
        "id": "123",
        "title": "Logged",
        "reward": 1.0,
        "url": "https://gengo.com/t/jobs/details/123",
    }
    raw_body = json.dumps(payload).encode("utf-8")

    with caplog.at_level(logging.INFO, logger="test.webhooks"):
        api.process_incoming_job_webhook(raw_body, _signed_headers(raw_body))

    assert "Webhook received job discovery" in caplog.text
    assert "Webhook processed event=evt-log" in caplog.text


def test_incoming_job_webhook_dedupes_event_ids_and_audits_duplicate(tmp_path):
    api = _api(tmp_path)
    payload = {
        "event_id": "evt-dup",
        "id": "123",
        "title": "Duplicate",
        "reward": 1.0,
        "url": "https://gengo.com/t/jobs/details/123",
    }
    raw_body = json.dumps(payload).encode("utf-8")
    headers = _signed_headers(raw_body)

    first = api.process_incoming_job_webhook(raw_body, headers)
    second = api.process_incoming_job_webhook(raw_body, headers)

    assert first["status"] == "processed"
    assert second["status"] == "duplicate"
    api.watcher._process_new_job.assert_called_once()
    assert api.get_webhook_audit_entries(10)[-1]["stage"] == "duplicate"


def test_incoming_job_webhook_rejects_bad_signature_with_audit(tmp_path):
    api = _api(tmp_path)
    payload = {
        "id": "123",
        "title": "Bad signature",
        "reward": 1.0,
        "url": "https://gengo.com/t/jobs/details/123",
    }
    raw_body = json.dumps(payload).encode("utf-8")

    client = TestClient(app)
    with patch("gengowatcher.web.api_instance", api):
        response = client.post(
            "/api/webhooks/jobs/discovered",
            content=raw_body,
            headers={
                "X-GengoWatcher-Timestamp": str(int(time.time())),
                "X-GengoWatcher-Signature": "sha256=wrong",
            },
        )

    assert response.status_code == 401
    assert api.get_webhook_audit_entries(10)[-1]["stage"] == "signature_rejected"
    api.watcher._process_new_job.assert_not_called()


def test_incoming_job_webhook_rejects_oversized_body(tmp_path):
    api = _api(tmp_path, max_body_bytes=8)

    client = TestClient(app)
    with patch("gengowatcher.web.api_instance", api):
        response = client.post(
            "/api/webhooks/jobs/discovered",
            content=b"x" * 9,
            headers={"Content-Length": "9"},
        )

    assert response.status_code == 413
    api.watcher._process_new_job.assert_not_called()


def test_incoming_job_webhook_processing_runs_off_event_loop(tmp_path):
    api = _api(tmp_path)
    payload = {
        "id": "123",
        "title": "JA > EN | Short translation",
        "reward": 12.5,
        "url": "https://gengo.com/t/jobs/details/123",
    }
    raw_body = json.dumps(payload).encode("utf-8")
    calls = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append(func.__name__)
        return func(*args, **kwargs)

    client = TestClient(app)
    with (
        patch("gengowatcher.web.api_instance", api),
        patch("gengowatcher.web.asyncio.to_thread", side_effect=fake_to_thread),
    ):
        response = client.post(
            "/api/webhooks/jobs/discovered",
            content=raw_body,
            headers=_signed_headers(raw_body),
        )

    assert response.status_code == 200
    assert calls == ["process_incoming_job_webhook"]
    api.watcher._process_new_job.assert_called_once()


def test_api_event_audit_endpoint_returns_recent_records(tmp_path):
    api = _api(tmp_path)
    api.webhook_audit_logger.record(
        direction="incoming",
        stage="received",
        event_id="evt-audit",
        status="received",
    )

    client = TestClient(app)
    with patch("gengowatcher.web.api_instance", api):
        response = client.get(
            "/api/events/audit?limit=5",
            headers={"Authorization": f"Bearer {authenticator.get_api_key()}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["entries"][-1]["event_id"] == "evt-audit"
    assert data["audit_log_path"].endswith("webhooks.jsonl")


def test_webhook_audit_log_rotates_by_size(tmp_path):
    audit = WebhookAuditLogger(
        path=tmp_path / "webhooks.jsonl",
        logger=logging.getLogger("test.webhooks.audit"),
        enabled=True,
        debug_enabled=True,
        max_log_bytes=120,
        max_log_lines=2,
    )

    for index in range(5):
        audit.record(
            direction="incoming",
            stage="received",
            event_id=f"evt-{index}",
            status="received",
            raw_body=b"x" * 80,
        )

    lines = audit.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 2


def test_webhook_audit_redacts_customer_content(tmp_path):
    audit = WebhookAuditLogger(
        path=tmp_path / "webhooks.jsonl",
        logger=logging.getLogger("test.webhooks.audit"),
        enabled=True,
        debug_enabled=True,
    )

    entry = audit.record(
        direction="outgoing",
        stage="queued",
        payload={
            "job_id": "123",
            "source_text": "private customer text",
            "segments": [{"source_content": "private customer text"}],
            "accepted_segments": [
                {
                    "target_content": "private target text",
                    "glossary": ["private glossary term"],
                }
            ],
            "accepted_target_text": "private accepted target",
        },
        raw_body=json.dumps(
            {
                "accepted_target_text": "private accepted target",
                "source_text": "private customer text",
                "job_id": "123",
            }
        ).encode(),
    )

    serialized = json.dumps(entry)
    assert "private customer text" not in serialized
    assert "private target text" not in serialized
    assert "private glossary term" not in serialized
    assert "private accepted target" not in serialized
    assert entry["payload"] == {"job_id": "123"}


def test_webhook_audit_removes_entries_older_than_retention(tmp_path):
    path = tmp_path / "webhooks.jsonl"
    now = time.time()
    path.write_text(
        json.dumps({"ts": now - 3 * 86400, "event_id": "old"})
        + "\n"
        + json.dumps({"ts": now, "event_id": "new"})
        + "\n",
        encoding="utf-8",
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")
        handle.write(json.dumps({"event_id": "unknown-age"}) + "\n")
    audit = WebhookAuditLogger(
        path=path,
        logger=logging.getLogger("test.webhooks.audit"),
        enabled=True,
        retention_days=1,
        _records_since_retention_check=99,
    )

    audit.record(direction="incoming", stage="received", event_id="latest")

    content = path.read_text(encoding="utf-8")
    assert '"event_id": "old"' not in content
    assert '"event_id": "new"' in content
    assert "not-json" in content
    assert '"event_id": "unknown-age"' in content


def test_outbound_webhook_redacts_customer_content_by_default(tmp_path):
    audit = WebhookAuditLogger(
        path=tmp_path / "outbound.jsonl",
        logger=logging.getLogger("test.webhooks.outbound"),
        enabled=False,
    )
    dispatcher = WebhookDispatcher(
        targets=[OutboundWebhookTarget(name="target", url="https://example.test")],
        logger=logging.getLogger("test.webhooks.dispatcher"),
        audit_logger=audit,
    )
    dispatcher._deliver = MagicMock()

    dispatcher.emit(
        "job.accepted",
        {
            "job_id": "123",
            "source_text": "private customer text",
            "accepted_segments": [
                {
                    "target_content": "private target text",
                    "glossary": ["private glossary term"],
                }
            ],
            "accepted_target_text": "private accepted target",
        },
        background=False,
    )

    envelope = dispatcher._deliver.call_args.args[2]
    assert envelope["payload"] == {"job_id": "123"}


def test_outbound_dispatcher_signs_delivers_and_audits_response(tmp_path):
    audit = WebhookAuditLogger(
        path=tmp_path / "outbound.jsonl",
        logger=logging.getLogger("test.webhooks.outbound"),
        enabled=True,
        debug_enabled=True,
    )
    dispatcher = WebhookDispatcher(
        targets=[
            OutboundWebhookTarget(
                name="translation-app",
                url="https://translation-app.test/webhooks",
                secret="outbound-secret",
                auth_token="outbound-token",
                verify_tls=False,
            )
        ],
        logger=logging.getLogger("test.webhooks.dispatcher"),
        audit_logger=audit,
        timeout_sec=1.0,
        max_attempts=1,
        initial_delay_sec=0.0,
        max_delay_sec=0.0,
    )
    response = MagicMock(status_code=200, text="ok")

    with patch("gengowatcher.webhooks.requests.post", return_value=response) as post:
        dispatcher.emit(
            "job.discovered",
            {"id": "123", "title": "Outbound"},
            event_id="evt-outbound",
            background=False,
        )

    post.assert_called_once()
    raw_body = post.call_args.kwargs["data"]
    headers = post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer outbound-token"
    assert (
        verify_webhook_signature(
            raw_body=raw_body,
            headers=headers,
            secret="outbound-secret",
        )
        == "signature ok"
    )
    stages = [entry["stage"] for entry in audit.tail(10)]
    assert stages == ["queued", "attempt", "delivered"]


def test_outbound_dispatcher_retries_with_minimum_delay_when_configured_zero(tmp_path):
    audit = WebhookAuditLogger(
        path=tmp_path / "outbound-retry.jsonl",
        logger=logging.getLogger("test.webhooks.outbound.retry"),
        enabled=True,
        debug_enabled=True,
    )
    dispatcher = WebhookDispatcher(
        targets=[
            OutboundWebhookTarget(
                name="retry-target",
                url="https://translation-app.test/webhooks",
            )
        ],
        logger=logging.getLogger("test.webhooks.dispatcher.retry"),
        audit_logger=audit,
        timeout_sec=1.0,
        max_attempts=3,
        initial_delay_sec=0.0,
        max_delay_sec=0.0,
    )
    response = MagicMock(status_code=503, text="retry later")

    with patch("gengowatcher.webhooks.requests.post", return_value=response) as post:
        with patch("gengowatcher.webhooks.time.sleep") as sleep:
            dispatcher.emit(
                "job.discovered",
                {"id": "123", "title": "Outbound"},
                event_id="evt-outbound-retry",
                background=False,
            )

    assert post.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 1.0]


def test_outbound_dispatcher_emits_console_log_messages(tmp_path, caplog):
    audit = WebhookAuditLogger(
        path=tmp_path / "outbound.jsonl",
        logger=logging.getLogger("test.webhooks.outbound.logs"),
        enabled=True,
        debug_enabled=True,
    )
    dispatcher = WebhookDispatcher(
        targets=[
            OutboundWebhookTarget(
                name="debug-target",
                url="https://translation-app.test/webhooks",
            )
        ],
        logger=logging.getLogger("test.webhooks.dispatcher.logs"),
        audit_logger=audit,
        timeout_sec=1.0,
        max_attempts=1,
        initial_delay_sec=0.0,
        max_delay_sec=0.0,
    )
    response = MagicMock(status_code=200, text="ok")

    with patch("gengowatcher.webhooks.requests.post", return_value=response):
        with caplog.at_level(logging.INFO, logger="test.webhooks.dispatcher.logs"):
            dispatcher.emit(
                "job.discovered",
                {"id": "123", "title": "Outbound"},
                event_id="evt-outbound-log",
                background=False,
            )

    assert "Webhook queued job.discovered event=evt-outbound-log" in caplog.text
    assert "Webhook delivery attempt event=evt-outbound-log" in caplog.text
    assert "Delivered webhook event evt-outbound-log" in caplog.text
