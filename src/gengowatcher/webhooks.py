from __future__ import annotations

import concurrent.futures
import hashlib
import hmac
import json
import logging
import queue
import secrets
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import requests
from pydantic import BaseModel, Field, field_validator

SENSITIVE_KEY_PARTS = {
    "authorization",
    "cookie",
    "key",
    "password",
    "secret",
    "session",
    "signature",
    "token",
}

WEBHOOK_SUBMISSION_MAX_WORKERS = 2
WEBHOOK_SUBMISSION_MAX_PENDING = 64
_webhook_executor: concurrent.futures.ThreadPoolExecutor | None = None
_webhook_executor_lock = threading.Lock()
_webhook_submission_slots = threading.BoundedSemaphore(
    WEBHOOK_SUBMISSION_MAX_WORKERS + WEBHOOK_SUBMISSION_MAX_PENDING
)


class WebhookError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class WebhookSignatureError(WebhookError):
    def __init__(self, detail: str = "Invalid webhook signature"):
        super().__init__(401, detail)


class WebhookPayloadError(WebhookError):
    def __init__(self, detail: str = "Invalid webhook payload"):
        super().__init__(400, detail)


class IncomingJobWebhookPayload(BaseModel):
    event_id: str | None = None
    event_type: str = "job.discovered"
    id: str | None = None
    job_id: str | None = None
    title: str
    reward: float
    url: str
    source: str = "webhook"
    currency: str = "USD"
    timestamp: float | None = None
    lang_pair: str = ""
    word_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_id", "event_type", "id", "job_id", "title", "url", "source")
    @classmethod
    def _strip_optional_strings(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Field must be a string")
        value = value.strip()
        return value or None

    @field_validator("reward")
    @classmethod
    def _validate_reward(cls, value):
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError("Reward must be a non-negative number")
        return float(value)

    @field_validator("word_count")
    @classmethod
    def _validate_word_count(cls, value):
        if value is None:
            return 0
        if not isinstance(value, int) or value < 0:
            raise ValueError("Word count must be a non-negative integer")
        return value

    def resolved_job_id(self) -> str:
        job_id = self.job_id or self.id
        if not job_id:
            raise WebhookPayloadError("Webhook job payload must include id or job_id")
        return job_id

    def normalized_source(self) -> str:
        source = self.source or "webhook"
        if source.lower().startswith("webhook"):
            return source
        return f"Webhook:{source}"

    def source_meta(self) -> dict[str, Any]:
        return {
            "webhook": {
                "event_id": self.event_id,
                "event_type": self.event_type,
                "source": self.source,
                "timestamp": self.timestamp,
                "metadata": self.metadata,
            }
        }


@dataclass(frozen=True)
class OutboundWebhookTarget:
    name: str
    url: str
    secret: str = ""
    auth_token: str = ""
    verify_tls: bool = True


def _config_get(config: Any, section: str, key: str, fallback: Any = None) -> Any:
    getter = getattr(config, "get", None)
    if not callable(getter):
        return fallback
    try:
        value = getter(section, key, fallback=fallback)
    except TypeError:
        value = getter(section, key)
    return fallback if value is None else value


def _config_bool(config: Any, section: str, key: str, fallback: bool = False) -> bool:
    value = _config_get(config, section, key, fallback)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled", ""}:
            return False
    return fallback


def _config_float(config: Any, section: str, key: str, fallback: float) -> float:
    try:
        return float(_config_get(config, section, key, fallback))
    except (TypeError, ValueError):
        return fallback


def _config_int(config: Any, section: str, key: str, fallback: int) -> int:
    try:
        return int(_config_get(config, section, key, fallback))
    except (TypeError, ValueError):
        return fallback


def config_get(config: Any, section: str, key: str, fallback: Any = None) -> Any:
    return _config_get(config, section, key, fallback)


def config_bool(config: Any, section: str, key: str, fallback: bool = False) -> bool:
    return _config_bool(config, section, key, fallback)


def config_float(config: Any, section: str, key: str, fallback: float) -> float:
    return _config_float(config, section, key, fallback)


def config_int(config: Any, section: str, key: str, fallback: int) -> int:
    return _config_int(config, section, key, fallback)


def _parse_url_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        if not value.strip():
            return []
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _mask_text(value: str, keep: int = 6) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]}"


def redact_debug_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in SENSITIVE_KEY_PARTS):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact_debug_value(item)
        return redacted
    if isinstance(value, list):
        return [redact_debug_value(item) for item in value]
    return value


def normalize_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    if not headers:
        return {}
    return {str(key).lower(): str(value) for key, value in headers.items()}


def sanitize_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    normalized = normalize_headers(headers)
    sanitized: dict[str, str] = {}
    for key, value in normalized.items():
        if any(part in key for part in SENSITIVE_KEY_PARTS):
            sanitized[key] = _mask_text(value)
        else:
            sanitized[key] = value
    return sanitized


def payload_sha256(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def _body_preview(raw_body: bytes, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    truncated = len(raw_body) > max_bytes
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        preview = raw_body[:max_bytes]
        text = preview.decode("utf-8", errors="replace")
    else:
        text = json.dumps(redact_debug_value(parsed), sort_keys=True)
        if len(text.encode("utf-8")) > max_bytes:
            text = text.encode("utf-8")[:max_bytes].decode("utf-8", errors="replace")
            truncated = True
    if truncated:
        text += "...[truncated]"
    return text


def build_webhook_signature(
    secret: str,
    raw_body: bytes,
    *,
    timestamp: str | None = None,
) -> str:
    signed_body = raw_body
    if timestamp:
        signed_body = timestamp.encode("utf-8") + b"." + raw_body
    digest = hmac.new(secret.encode("utf-8"), signed_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_webhook_signature(
    *,
    raw_body: bytes,
    headers: Mapping[str, Any],
    secret: str,
    require_signature: bool = True,
    tolerance_sec: float = 300.0,
    now: float | None = None,
) -> str:
    if not require_signature:
        return "signature disabled"
    if not secret:
        raise WebhookSignatureError(
            "Webhook signature is required but no secret is configured"
        )

    normalized = normalize_headers(headers)
    signature = (
        normalized.get("x-gengowatcher-signature")
        or normalized.get("x-signature-256")
        or normalized.get("x-hub-signature-256")
        or ""
    ).strip()
    if not signature:
        raise WebhookSignatureError("Missing webhook signature header")

    timestamp = (
        normalized.get("x-gengowatcher-timestamp")
        or normalized.get("x-webhook-timestamp")
        or ""
    ).strip()
    if timestamp:
        try:
            timestamp_value = float(timestamp)
        except ValueError as exc:
            raise WebhookSignatureError("Invalid webhook timestamp") from exc
        current_time = time.time() if now is None else now
        if tolerance_sec > 0 and abs(current_time - timestamp_value) > tolerance_sec:
            raise WebhookSignatureError("Webhook timestamp is outside tolerance")

    expected = build_webhook_signature(secret, raw_body, timestamp=timestamp or None)
    if signature.startswith("sha256="):
        supplied = signature
    else:
        supplied = f"sha256={signature}"

    if not hmac.compare_digest(expected, supplied):
        raise WebhookSignatureError()
    return "signature ok"


@dataclass
class WebhookAuditLogger:
    path: Path
    logger: logging.Logger
    enabled: bool = True
    debug_enabled: bool = True
    max_payload_preview_bytes: int = 4096
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _counters: dict[str, int] = field(default_factory=dict)
    _last_entry: dict[str, Any] | None = None

    @classmethod
    def from_config(cls, config: Any, logger: logging.Logger) -> "WebhookAuditLogger":
        path = Path(
            str(
                _config_get(
                    config,
                    "Webhooks",
                    "audit_log_path",
                    "logs/webhooks.jsonl",
                )
            )
        )
        return cls(
            path=path,
            logger=logger,
            enabled=_config_bool(config, "Webhooks", "audit_enabled", True),
            debug_enabled=_config_bool(config, "Webhooks", "debug_enabled", True),
            max_payload_preview_bytes=_config_int(
                config,
                "Webhooks",
                "debug_payload_preview_bytes",
                4096,
            ),
        )

    def record(
        self,
        *,
        direction: str,
        stage: str,
        event_id: str | None = None,
        event_type: str | None = None,
        source: str | None = None,
        request_id: str | None = None,
        target: str | None = None,
        status: str | None = None,
        error: str | None = None,
        raw_body: bytes | None = None,
        payload: Any | None = None,
        headers: Mapping[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "ts": time.time(),
            "direction": direction,
            "stage": stage,
            "event_id": event_id,
            "event_type": event_type,
            "source": source,
            "request_id": request_id,
            "target": target,
            "status": status,
            "error": error,
        }
        if raw_body is not None:
            entry["payload_sha256"] = payload_sha256(raw_body)
            entry["payload_bytes"] = len(raw_body)
            if self.debug_enabled:
                entry["payload_preview"] = _body_preview(
                    raw_body,
                    self.max_payload_preview_bytes,
                )
        if payload is not None and self.debug_enabled:
            entry["payload"] = redact_debug_value(payload)
        if headers is not None and self.debug_enabled:
            entry["headers"] = sanitize_headers(headers)
        if extra:
            entry["extra"] = redact_debug_value(extra)

        compact = {key: value for key, value in entry.items() if value is not None}
        if self.enabled:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(compact, sort_keys=True) + "\n")
                self._remember_entry(compact)
        else:
            with self._lock:
                self._remember_entry(compact)
        if self.debug_enabled:
            self.logger.debug(
                "Webhook audit %s/%s event=%s status=%s error=%s",
                direction,
                stage,
                event_id,
                status,
                error,
            )
        return compact

    def _remember_entry(self, entry: dict[str, Any]) -> None:
        self._last_entry = dict(entry)
        for key in (
            "direction",
            "stage",
            "status",
            "event_type",
        ):
            value = entry.get(key)
            if value:
                counter_key = f"{key}:{value}"
                self._counters[counter_key] = self._counters.get(counter_key, 0) + 1

    def tail(self, limit: int = 50) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        if not self.path.exists():
            return []
        lines: deque[str] = deque(maxlen=limit)
        with self._lock:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    lines.append(line)
        entries: list[dict[str, Any]] = []
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                entries.append(value)
        return entries

    def summary(self, limit: int = 20) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            last_entry = dict(self._last_entry) if self._last_entry else None
        recent = (
            self.tail(limit)
            if self.enabled
            else ([] if last_entry is None else [last_entry])
        )
        return {
            "enabled": self.enabled,
            "debug_enabled": self.debug_enabled,
            "audit_log_path": str(self.path),
            "last_entry": last_entry,
            "recent": recent,
            "counters": counters,
            "incoming_total": counters.get("direction:incoming", 0),
            "outgoing_total": counters.get("direction:outgoing", 0),
            "failed_total": counters.get("status:failed", 0)
            + counters.get("status:rejected", 0)
            + counters.get("status:dropped", 0),
            "processed_total": counters.get("status:processed", 0),
            "delivered_total": counters.get("status:delivered", 0),
            "duplicate_total": counters.get("status:duplicate", 0),
        }


def get_webhook_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _webhook_executor
    with _webhook_executor_lock:
        if _webhook_executor is None:
            _webhook_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=WEBHOOK_SUBMISSION_MAX_WORKERS,
                thread_name_prefix="WebhookDeliver",
            )
        return _webhook_executor


def submit_webhook_task(task: Callable[[], None]) -> concurrent.futures.Future:
    if not _webhook_submission_slots.acquire(blocking=False):
        raise queue.Full("webhook delivery queue is full")
    try:
        future = get_webhook_executor().submit(task)
    except Exception:
        _webhook_submission_slots.release()
        raise
    future.add_done_callback(lambda _future: _webhook_submission_slots.release())
    return future


class WebhookDispatcher:
    def __init__(
        self,
        *,
        targets: list[OutboundWebhookTarget],
        logger: logging.Logger,
        audit_logger: WebhookAuditLogger,
        timeout_sec: float = 5.0,
        max_attempts: int = 3,
        initial_delay_sec: float = 0.5,
        max_delay_sec: float = 10.0,
    ):
        self.targets = targets
        self.logger = logger
        self.audit_logger = audit_logger
        self.timeout_sec = timeout_sec
        self.max_attempts = max(1, max_attempts)
        self.initial_delay_sec = max(0.0, initial_delay_sec)
        self.max_delay_sec = max(0.0, max_delay_sec)

    @classmethod
    def from_config(
        cls,
        config: Any,
        logger: logging.Logger,
        audit_logger: WebhookAuditLogger,
    ) -> "WebhookDispatcher":
        enabled = _config_bool(config, "Webhooks", "outbound_enabled", False)
        urls = _parse_url_list(_config_get(config, "Webhooks", "outbound_urls", []))
        secret = str(_config_get(config, "Webhooks", "outbound_secret", "") or "")
        auth_token = str(
            _config_get(config, "Webhooks", "outbound_auth_token", "") or ""
        )
        verify_tls = _config_bool(config, "Webhooks", "outbound_verify_tls", True)
        targets = []
        if enabled:
            for index, url in enumerate(urls, start=1):
                targets.append(
                    OutboundWebhookTarget(
                        name=f"target-{index}",
                        url=url,
                        secret=secret,
                        auth_token=auth_token,
                        verify_tls=verify_tls,
                    )
                )
        return cls(
            targets=targets,
            logger=logger,
            audit_logger=audit_logger,
            timeout_sec=_config_float(config, "Webhooks", "outbound_timeout_sec", 5.0),
            max_attempts=_config_int(config, "Webhooks", "outbound_max_attempts", 3),
            initial_delay_sec=_config_float(
                config,
                "Webhooks",
                "outbound_initial_delay_sec",
                0.5,
            ),
            max_delay_sec=_config_float(
                config, "Webhooks", "outbound_max_delay_sec", 10.0
            ),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.targets)

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_id: str | None = None,
        background: bool = True,
    ) -> list[concurrent.futures.Future | None]:
        if not self.targets:
            self.logger.debug(
                "Webhook event %s skipped because no targets are enabled", event_type
            )
            return []

        envelope = {
            "event_id": event_id or str(uuid.uuid4()),
            "event_type": event_type,
            "created_at": time.time(),
            "payload": payload,
        }
        raw_body = json.dumps(
            envelope,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        futures: list[concurrent.futures.Future | None] = []
        for target in self.targets:
            self.audit_logger.record(
                direction="outgoing",
                stage="queued",
                event_id=str(envelope["event_id"]),
                event_type=event_type,
                target=target.name,
                status="queued",
                raw_body=raw_body,
                payload=envelope,
                extra={"url": target.url},
            )
            self.logger.info(
                "Webhook queued %s event=%s target=%s url=%s",
                event_type,
                envelope["event_id"],
                target.name,
                target.url,
            )
            if background:
                try:
                    future = submit_webhook_task(
                        lambda target=target, body=raw_body, envelope=envelope: self._deliver(
                            target,
                            body,
                            envelope,
                        )
                    )
                    futures.append(future)
                except queue.Full:
                    self.audit_logger.record(
                        direction="outgoing",
                        stage="queue_full",
                        event_id=str(envelope["event_id"]),
                        event_type=event_type,
                        target=target.name,
                        status="dropped",
                        raw_body=raw_body,
                        payload=envelope,
                    )
                    self.logger.warning(
                        "Webhook delivery queue is full; dropping event %s",
                        envelope["event_id"],
                    )
                    futures.append(None)
            else:
                self._deliver(target, raw_body, envelope)
                futures.append(None)
        return futures

    def _deliver(
        self,
        target: OutboundWebhookTarget,
        raw_body: bytes,
        envelope: dict[str, Any],
    ) -> None:
        event_id = str(envelope.get("event_id") or "")
        event_type = str(envelope.get("event_type") or "")
        delay = self.initial_delay_sec
        last_error = ""

        for attempt in range(1, self.max_attempts + 1):
            timestamp = str(int(time.time()))
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "GengoWatcher-Webhooks/1.0",
                "X-GengoWatcher-Event-Id": event_id,
                "X-GengoWatcher-Event-Type": event_type,
                "X-GengoWatcher-Timestamp": timestamp,
            }
            if target.secret:
                headers["X-GengoWatcher-Signature"] = build_webhook_signature(
                    target.secret,
                    raw_body,
                    timestamp=timestamp,
                )
            if target.auth_token:
                headers["Authorization"] = f"Bearer {target.auth_token}"

            self.audit_logger.record(
                direction="outgoing",
                stage="attempt",
                event_id=event_id,
                event_type=event_type,
                target=target.name,
                status="attempting",
                raw_body=raw_body,
                headers=headers,
                extra={"attempt": attempt, "url": target.url},
            )
            self.logger.info(
                "Webhook delivery attempt event=%s type=%s target=%s attempt=%s/%s",
                event_id,
                event_type,
                target.name,
                attempt,
                self.max_attempts,
            )
            start = time.monotonic()
            try:
                response = requests.post(
                    target.url,
                    data=raw_body,
                    headers=headers,
                    timeout=self.timeout_sec,
                    verify=target.verify_tls,
                )
                elapsed_ms = round((time.monotonic() - start) * 1000, 2)
                retryable = response.status_code in {408, 429, 500, 502, 503, 504}
                success = 200 <= response.status_code < 300
                if success:
                    self.audit_logger.record(
                        direction="outgoing",
                        stage="delivered",
                        event_id=event_id,
                        event_type=event_type,
                        target=target.name,
                        status="delivered",
                        raw_body=raw_body,
                        extra={
                            "attempt": attempt,
                            "elapsed_ms": elapsed_ms,
                            "status_code": response.status_code,
                            "response_excerpt": response.text[:500],
                            "url": target.url,
                        },
                    )
                    self.logger.info(
                        "Delivered webhook event %s to %s in %.2fms",
                        event_id,
                        target.name,
                        elapsed_ms,
                    )
                    return

                last_error = f"HTTP {response.status_code}: {response.text[:500]}"
                self.audit_logger.record(
                    direction="outgoing",
                    stage="failed_attempt",
                    event_id=event_id,
                    event_type=event_type,
                    target=target.name,
                    status=(
                        "retrying"
                        if retryable and attempt < self.max_attempts
                        else "failed"
                    ),
                    error=last_error,
                    raw_body=raw_body,
                    extra={
                        "attempt": attempt,
                        "elapsed_ms": elapsed_ms,
                        "status_code": response.status_code,
                        "retryable": retryable,
                        "url": target.url,
                    },
                )
                self.logger.warning(
                    "Webhook delivery failed event=%s target=%s attempt=%s/%s error=%s",
                    event_id,
                    target.name,
                    attempt,
                    self.max_attempts,
                    last_error,
                )
                if not retryable:
                    break
            except requests.RequestException as exc:
                elapsed_ms = round((time.monotonic() - start) * 1000, 2)
                last_error = str(exc)
                self.audit_logger.record(
                    direction="outgoing",
                    stage="failed_attempt",
                    event_id=event_id,
                    event_type=event_type,
                    target=target.name,
                    status="retrying" if attempt < self.max_attempts else "failed",
                    error=last_error,
                    raw_body=raw_body,
                    extra={
                        "attempt": attempt,
                        "elapsed_ms": elapsed_ms,
                        "url": target.url,
                    },
                )
                self.logger.warning(
                    "Webhook delivery exception event=%s target=%s attempt=%s/%s error=%s",
                    event_id,
                    target.name,
                    attempt,
                    self.max_attempts,
                    last_error,
                )
            if attempt < self.max_attempts and delay > 0:
                time.sleep(delay)
                delay = min(self.max_delay_sec, delay * 2 if delay else 0)

        self.audit_logger.record(
            direction="outgoing",
            stage="dead_letter",
            event_id=event_id,
            event_type=event_type,
            target=target.name,
            status="failed",
            error=last_error,
            raw_body=raw_body,
            payload=envelope,
            extra={"url": target.url, "max_attempts": self.max_attempts},
        )
        self.logger.warning(
            "Webhook event %s failed delivery to %s after %s attempt(s): %s",
            event_id,
            target.name,
            self.max_attempts,
            last_error,
        )


def build_incoming_job_response(
    *,
    payload: IncomingJobWebhookPayload,
    event_id: str,
    status: str,
    payload_hash: str,
    audit_path: Path,
    duration_ms: float,
    debug_enabled: bool,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "status": status,
        "event_id": event_id,
        "job_id": payload.resolved_job_id(),
    }
    if debug_enabled:
        response["debug"] = {
            "event_type": payload.event_type,
            "source": payload.source,
            "normalized_source": payload.normalized_source(),
            "payload_sha256": payload_hash,
            "audit_log_path": str(audit_path),
            "duration_ms": duration_ms,
        }
    return response


def make_request_id(headers: Mapping[str, Any]) -> str:
    normalized = normalize_headers(headers)
    return (
        normalized.get("x-request-id")
        or normalized.get("x-correlation-id")
        or secrets.token_urlsafe(12)
    )
