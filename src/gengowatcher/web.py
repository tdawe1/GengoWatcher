"""
Web API layer for GengoWatcher - provides REST and WebSocket endpoints
for web UI integration while maintaining compatibility with existing TUI.
"""

import asyncio
import csv
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import unquote, urlparse

from fastapi import (
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    Request,
    Depends,
    Query,
    UploadFile,
    File,
    Form,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from prometheus_client import Gauge, make_asgi_app
import requests
import uvicorn

from .config import AppConfig
from .prom_metrics import ensure_watcher_metrics_registered
from .state import AppState
from .watcher import GengoWatcher
from .web_file_storage import (
    StoredFileEntry,
    StoredFileUploadResponse,
    WebFileStorage,
)
from .webhooks import (
    IncomingJobWebhookPayload,
    WebhookAuditLogger,
    WebhookError,
    build_incoming_job_response,
    config_bool,
    config_float,
    config_get,
    config_int,
    make_request_id,
    normalize_headers,
    payload_sha256,
    verify_webhook_signature,
)
from .web_models import (
    APIAuthenticator,
    CommandRequest,
    ConfigSection,
    JobEntry,
    PaginationParams,
    SECURITY,
    WatcherStatus,
)

authenticator = APIAuthenticator()


class WebAPI:
    """Web API wrapper for GengoWatcher that maintains thread safety."""

    def __init__(
        self,
        config: AppConfig,
        state: AppState,
        logger: logging.Logger,
        *,
        watcher: Optional[GengoWatcher] = None,
        start_watcher_thread: bool = True,
    ):
        """Initialize the WebAPI instance.

        Uses a shared watcher when provided, otherwise creates its own watcher.
        This allows the web API to run alongside the TUI without starting a
        duplicate RSS/WebSocket monitor loop.

        Args:
            config: Application configuration object.
            state: Application state object for data persistence.
            logger: Logger instance for recording events.
            watcher: Optional shared watcher instance owned by the runtime.
            start_watcher_thread: Whether this WebAPI instance should start and
                manage the watcher thread lifecycle.
        """
        self.config = config
        self.state = state
        self.logger = logger
        self.file_storage = WebFileStorage(config, logger)

        self.watcher = (
            watcher if watcher is not None else GengoWatcher(config, state, logger)
        )
        webhook_audit_candidate = getattr(self.watcher, "webhook_audit_logger", None)
        if isinstance(webhook_audit_candidate, WebhookAuditLogger):
            self.webhook_audit_logger = webhook_audit_candidate
        else:
            self.webhook_audit_logger = WebhookAuditLogger.from_config(config, logger)
        self._webhook_event_ids: set[str] = set()
        self._webhook_event_order: deque[str] = deque(
            maxlen=max(
                1,
                config_int(config, "Webhooks", "max_seen_event_ids", 1000),
            )
        )
        self._webhook_event_lock = threading.RLock()
        self._manage_watcher_lifecycle = watcher is None and start_watcher_thread

        # Thread safety for shared state access
        self._status_lock = threading.RLock()  # Reentrant lock for better safety
        self._active_connections: List[WebSocket] = []
        self._connections_lock = threading.RLock()
        self._jobs_lock = threading.RLock()
        self._event_history: deque[dict[str, Any]] = deque(
            maxlen=max(1, config_int(config, "WebServer", "event_history_size", 200))
        )
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._previous_api_event_callback = getattr(
            self.watcher, "on_api_event_callback", None
        )
        self._api_event_callback = self._handle_watcher_api_event
        self.watcher.on_api_event_callback = self._api_event_callback
        self.watcher_thread: Optional[threading.Thread] = None

        if start_watcher_thread:
            self.watcher_thread = threading.Thread(
                target=self.watcher.run, daemon=True, name="WebWatcherThread"
            )
            self.watcher_thread.start()
            self.logger.info("WebAPI initialized and watcher thread started")
        else:
            self.logger.info("WebAPI initialized using shared watcher instance")

    def get_status(self) -> WatcherStatus:
        """Get current watcher status."""
        with self._status_lock:
            # Convert datetime to timestamp for JSON serialization
            last_check = None
            if self.watcher.last_check_time:
                if isinstance(self.watcher.last_check_time, float):
                    last_check = self.watcher.last_check_time
                else:
                    # Assume it's a datetime object
                    last_check = self.watcher.last_check_time.timestamp()

            health_snapshot = {}
            health_getter = getattr(self.watcher, "get_health_snapshot", None)
            if callable(health_getter):
                try:
                    candidate = health_getter()
                    if isinstance(candidate, dict):
                        health_snapshot = candidate
                except Exception as exc:
                    self.logger.warning("Failed to get health snapshot: %s", exc)

            return WatcherStatus(
                is_running=not self.watcher.shutdown_event.is_set(),
                websocket_status=self.watcher.websocket_status,
                rss_status=self.watcher.rss_action,
                last_check_time=last_check,
                next_check_time=self.watcher.next_check_time,
                session_stats={
                    "new_entries": self.watcher.session_new_entries,
                    "total_value": self.watcher.session_total_value,
                    "uptime": time.time() - self.watcher.start_time,
                },
                failure_count=self.watcher.failure_count,
                cancellation_stats=self.watcher.get_cancellation_stats(),
                health=health_snapshot,
            )

    async def cancel_current_job(self) -> bool:
        """Cancel the currently tracked job via the watcher."""
        return await self.watcher.cancel_current_job_async()

    def _remember_webhook_event_id(self, event_id: str) -> bool:
        with self._webhook_event_lock:
            if event_id in self._webhook_event_ids:
                return False
            maxlen = self._webhook_event_order.maxlen or 1000
            if len(self._webhook_event_order) >= maxlen:
                old_event_id = self._webhook_event_order.popleft()
                self._webhook_event_ids.discard(old_event_id)
            self._webhook_event_order.append(event_id)
            self._webhook_event_ids.add(event_id)
            return True

    def process_incoming_job_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Validate an incoming job webhook and route it into the watcher pipeline."""
        start = time.monotonic()
        request_id = make_request_id(headers)
        body_hash = payload_sha256(raw_body)
        incoming_enabled = config_bool(
            self.config,
            "Webhooks",
            "incoming_enabled",
            False,
        )
        self.webhook_audit_logger.record(
            direction="incoming",
            stage="received",
            request_id=request_id,
            status="received",
            raw_body=raw_body,
            headers=headers,
            extra={"incoming_enabled": incoming_enabled},
        )
        self.logger.info(
            "Webhook received job discovery request_id=%s bytes=%s sha256=%s",
            request_id,
            len(raw_body),
            body_hash,
        )

        if not incoming_enabled:
            self.webhook_audit_logger.record(
                direction="incoming",
                stage="rejected",
                request_id=request_id,
                status="disabled",
                raw_body=raw_body,
            )
            self.logger.warning(
                "Webhook rejected request_id=%s reason=ingress-disabled sha256=%s",
                request_id,
                body_hash,
            )
            raise WebhookError(404, "Webhook ingress is disabled")

        try:
            signature_status = verify_webhook_signature(
                raw_body=raw_body,
                headers=headers,
                secret=str(
                    config_get(self.config, "Webhooks", "incoming_secret", "") or ""
                ),
                require_signature=config_bool(
                    self.config,
                    "Webhooks",
                    "require_signature",
                    True,
                ),
                tolerance_sec=config_float(
                    self.config,
                    "Webhooks",
                    "signature_tolerance_sec",
                    300.0,
                ),
            )
        except WebhookError as exc:
            self.webhook_audit_logger.record(
                direction="incoming",
                stage="signature_rejected",
                request_id=request_id,
                status="rejected",
                error=exc.detail,
                raw_body=raw_body,
                headers=headers,
            )
            self.logger.warning(
                "Webhook signature rejected request_id=%s reason=%s sha256=%s",
                request_id,
                exc.detail,
                body_hash,
            )
            raise

        try:
            decoded = json.loads(raw_body.decode("utf-8"))
            payload = IncomingJobWebhookPayload.model_validate(decoded)
            if payload.event_type != "job.discovered":
                raise WebhookError(
                    400,
                    "Job webhook endpoint only accepts event_type=job.discovered",
                )
            header_event_id = normalize_headers(headers).get("x-gengowatcher-event-id")
            event_id = (
                payload.event_id
                or header_event_id
                or f"{payload.event_type}:{payload.resolved_job_id()}"
            )
            payload = payload.model_copy(update={"event_id": event_id})
            job_id = payload.resolved_job_id()
        except WebhookError as exc:
            self.webhook_audit_logger.record(
                direction="incoming",
                stage="validation_rejected",
                request_id=request_id,
                status="rejected",
                error=exc.detail,
                raw_body=raw_body,
                headers=headers,
            )
            self.logger.warning(
                "Webhook validation rejected request_id=%s reason=%s sha256=%s",
                request_id,
                exc.detail,
                body_hash,
            )
            raise
        except Exception as exc:
            self.webhook_audit_logger.record(
                direction="incoming",
                stage="validation_rejected",
                request_id=request_id,
                status="rejected",
                error=str(exc),
                raw_body=raw_body,
                headers=headers,
            )
            self.logger.warning(
                "Webhook payload rejected request_id=%s reason=%s sha256=%s",
                request_id,
                exc,
                body_hash,
            )
            raise WebhookError(400, f"Invalid webhook payload: {exc}") from exc

        if not self._remember_webhook_event_id(event_id):
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            self.webhook_audit_logger.record(
                direction="incoming",
                stage="duplicate",
                event_id=event_id,
                event_type=payload.event_type,
                source=payload.source,
                request_id=request_id,
                status="duplicate",
                raw_body=raw_body,
                payload=payload.model_dump(),
                extra={
                    "duration_ms": duration_ms,
                    "payload_sha256": body_hash,
                    "signature": signature_status,
                },
            )
            self.logger.info(
                "Webhook duplicate ignored event=%s job=%s source=%s sha256=%s",
                event_id,
                payload.resolved_job_id(),
                payload.source,
                body_hash,
            )
            return build_incoming_job_response(
                payload=payload,
                event_id=event_id,
                status="duplicate",
                payload_hash=body_hash,
                audit_path=self.webhook_audit_logger.path,
                duration_ms=duration_ms,
                debug_enabled=self.webhook_audit_logger.debug_enabled,
            )

        self.watcher._process_new_job(
            job_id,
            payload.title,
            payload.reward,
            payload.url,
            payload.normalized_source(),
            source_meta=payload.source_meta(),
        )
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        self.webhook_audit_logger.record(
            direction="incoming",
            stage="processed",
            event_id=event_id,
            event_type=payload.event_type,
            source=payload.source,
            request_id=request_id,
            status="processed",
            raw_body=raw_body,
            payload=payload.model_dump(),
            headers=headers,
            extra={
                "duration_ms": duration_ms,
                "payload_sha256": body_hash,
                "signature": signature_status,
                "normalized_source": payload.normalized_source(),
            },
        )
        self.logger.info(
            "Webhook processed event=%s job=%s source=%s duration=%.2fms audit=%s",
            event_id,
            job_id,
            payload.source,
            duration_ms,
            self.webhook_audit_logger.path,
        )
        return build_incoming_job_response(
            payload=payload,
            event_id=event_id,
            status="processed",
            payload_hash=body_hash,
            audit_path=self.webhook_audit_logger.path,
            duration_ms=duration_ms,
            debug_enabled=self.webhook_audit_logger.debug_enabled,
        )

    def get_webhook_audit_entries(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.webhook_audit_logger.tail(limit)

    def _get_file_storage_dir(self) -> Path:
        return self.file_storage.get_storage_dir()

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        return WebFileStorage.sanitize_filename(filename)

    @staticmethod
    def _sanitize_file_component(value: str, fallback: str) -> str:
        return WebFileStorage.sanitize_file_component(value, fallback)

    def _ensure_within_storage_dir(self, path: Path) -> Path:
        return self.file_storage.ensure_within_storage_dir(path)

    def _is_valid_stored_name(self, stored_name: str) -> bool:
        return self.file_storage.is_valid_stored_name(stored_name)

    def _build_file_entry(
        self,
        path: Path,
        *,
        original_name: str | None = None,
        content_type: str | None = None,
    ) -> StoredFileEntry:
        return self.file_storage.build_file_entry(
            path,
            original_name=original_name,
            content_type=content_type,
        )

    def _metadata_path(self, path: Path) -> Path:
        return self.file_storage.metadata_path(path)

    def _load_file_metadata(self, path: Path) -> dict[str, Any]:
        return self.file_storage.load_file_metadata(path)

    def list_files(self) -> list[StoredFileEntry]:
        return self.file_storage.list_files()

    def save_uploaded_file(
        self,
        filename: str,
        content: bytes,
        *,
        content_type: str | None = None,
        job_id: str | None = None,
        tier: str | None = None,
        word_count: int | None = None,
        value: float | None = None,
    ) -> StoredFileEntry:
        return self.file_storage.save_uploaded_file(
            filename=filename,
            content=content,
            content_type=content_type,
            job_id=job_id,
            tier=tier,
            word_count=word_count,
            value=value,
        )

    def _resolve_stored_file_path(self, stored_name: str) -> Path | None:
        return self.file_storage.resolve_stored_file_path(stored_name)

    def get_file_path(self, stored_name: str) -> Path | None:
        return self.file_storage.get_file_path(stored_name)

    def get_file_entry(self, stored_name: str) -> StoredFileEntry | None:
        return self.file_storage.get_file_entry(stored_name)

    @staticmethod
    def _normalize_tier(
        tier: str | None,
        *,
        word_count: int | None = None,
        value: float | None = None,
    ) -> str | None:
        return WebFileStorage.normalize_tier(
            tier,
            word_count=word_count,
            value=value,
        )

    def _build_stored_filename(
        self,
        filename: str,
        *,
        job_id: str | None = None,
        tier: str | None = None,
        word_count: int | None = None,
        value: float | None = None,
    ) -> str:
        return self.file_storage.build_stored_filename(
            filename,
            job_id=job_id,
            tier=tier,
            word_count=word_count,
            value=value,
        )

    def get_recent_jobs(self, limit: int = 50, page: int = 1) -> Dict[str, Any]:
        """Get recent jobs from state with pagination."""
        try:
            with self._jobs_lock:
                recent_jobs = self.state.get_recent_jobs(
                    limit * page
                )  # Get more to handle pagination
                total_jobs = len(recent_jobs)

                # Apply pagination
                start_idx = (page - 1) * limit
                end_idx = start_idx + limit
                paginated_jobs = recent_jobs[start_idx:end_idx]

                jobs = []
                for job_data in paginated_jobs:
                    try:
                        jobs.append(JobEntry(**job_data))
                    except Exception as e:
                        self.logger.warning(f"Invalid job data: {e}, skipping job")

                return {
                    "jobs": jobs,
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": total_jobs,
                        "pages": (total_jobs + limit - 1) // limit,  # Ceiling division
                    },
                }
        except Exception as e:
            self.logger.exception(f"Error retrieving recent jobs: {e}")
            return {
                "jobs": [],
                "pagination": {"page": page, "limit": limit, "total": 0, "pages": 0},
            }

    def get_jobs_from_csv(
        self,
        limit: int = 50,
        page: int = 1,
        min_reward: Optional[float] = None,
        max_reward: Optional[float] = None,
        search_term: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get jobs from CSV file with pagination and filtering."""
        try:
            # Get CSV file path from config
            csv_file_path = self.config.get(
                "Paths", "all_entries_log", fallback="logs/all_entries.csv"
            )

            # Check if file exists
            if not os.path.exists(csv_file_path):
                self.logger.warning(f"CSV file not found: {csv_file_path}")
                return {
                    "jobs": [],
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": 0,
                        "pages": 0,
                    },
                }

            # Count total rows first (for pagination)
            total_rows = 0
            with open(csv_file_path, "r", encoding="utf-8") as f:
                total_rows = sum(1 for line in f) - 1  # Subtract 1 for header row

            # If no rows, return empty result
            if total_rows <= 0:
                return {
                    "jobs": [],
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": 0,
                        "pages": 0,
                    },
                }

            jobs = []
            current_row = 0
            start_idx = (page - 1) * limit
            end_idx = start_idx + limit
            rows_processed = 0

            # Read CSV file with filtering
            with open(csv_file_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)

                for row in reader:
                    current_row += 1

                    # Skip header row if present
                    if current_row == 1 and row.get("timestamp") == "timestamp":
                        continue

                    try:
                        # Extract data from row
                        timestamp = row.get("timestamp", "")
                        title = row.get("title", "N/A")
                        reward_str = row.get("reward", "0")
                        link = row.get("link", "")
                        summary = row.get("summary", "")

                        # Convert reward to float
                        try:
                            reward = float(reward_str) if reward_str else 0.0
                        except ValueError:
                            reward = 0.0

                        # Apply reward filtering
                        if min_reward is not None and reward < min_reward:
                            continue
                        if max_reward is not None and reward > max_reward:
                            continue

                        # Apply search filtering
                        if search_term:
                            search_lower = search_term.lower()
                            if (
                                search_lower not in title.lower()
                                and search_lower not in summary.lower()
                            ):
                                continue

                        # Create job entry
                        job_entry = JobEntry(
                            id=str(hash(f"{link}{timestamp}")),  # Create unique ID
                            title=title,
                            reward=reward,
                            currency="USD",
                            url=link,
                            timestamp=time.time(),  # Use current time since we don't have exact timestamp
                            source="csv",
                        )

                        # Apply pagination
                        if rows_processed >= start_idx and rows_processed < end_idx:
                            jobs.append(job_entry)

                        rows_processed += 1

                        # Stop if we have enough jobs
                        if len(jobs) >= limit:
                            break

                    except Exception as e:
                        self.logger.warning(
                            f"Error processing CSV row {current_row}: {e}"
                        )
                        continue

            return {
                "jobs": jobs,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": rows_processed,
                    "pages": (rows_processed + limit - 1) // limit,  # Ceiling division
                },
            }

        except FileNotFoundError:
            self.logger.warning(f"CSV file not found: {csv_file_path}")
            return {
                "jobs": [],
                "pagination": {"page": page, "limit": limit, "total": 0, "pages": 0},
            }
        except Exception as e:
            self.logger.exception(f"Error reading jobs from CSV: {e}")
            return {
                "jobs": [],
                "pagination": {"page": page, "limit": limit, "total": 0, "pages": 0},
            }

    def add_job(self, job_id: str, title: str, reward: float, url: str, source: str):
        """Add a new job to the state storage."""
        try:
            with self._jobs_lock:
                job_data = {
                    "id": job_id,
                    "title": title,
                    "reward": reward,
                    "currency": "USD",
                    "url": url,
                    "timestamp": time.time(),
                    "source": source,
                }
                self.state.add_job(job_data)
                self.logger.debug(f"Added job to storage: {job_id}")
        except Exception as e:
            self.logger.exception(f"Error adding job to storage: {e}")

    async def accept_job(self, job_id: str) -> bool:
        """Accept a job by ID using the job acceptance engine."""
        try:
            # Check if the watcher has a job acceptance engine
            if not hasattr(self.watcher, "job_acceptance_engine"):
                self.logger.error("Job acceptance engine not available")
                return False

            # Find the job in the state
            jobs_result = self.get_recent_jobs(limit=1000)  # Get all jobs to search
            jobs = jobs_result["jobs"]
            target_job = None

            for job in jobs:
                if str(job.id) == str(job_id):
                    target_job = {
                        "id": job.id,
                        "title": job.title,
                        "reward": job.reward,
                        "url": job.url,
                        "source": job.source,
                    }
                    break

            if not target_job:
                self.logger.error(f"Job {job_id} not found")
                return False

            # Attempt to accept the job
            success = await self.watcher.job_acceptance_engine._attempt_job_acceptance(
                target_job
            )
            return success

        except Exception as e:
            self.logger.exception(f"Error accepting job {job_id}: {e}")
            return False

    @staticmethod
    def _json_safe(value: Any) -> Any:
        try:
            return json.loads(json.dumps(value, default=str))
        except Exception:
            return str(value)

    def publish_api_event(
        self,
        event_type: str,
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record and asynchronously broadcast a watcher API event."""
        payload = self._json_safe(dict(data or {}))
        job_id = ""
        if isinstance(payload, dict):
            job_id = str(payload.get("id") or payload.get("job_id") or "")
        timestamp = time.time()
        event = {
            "type": event_type,
            "event_type": event_type,
            "event_id": (
                f"{event_type}:{job_id or 'system'}:"
                f"{int(timestamp * 1000)}:{secrets.token_hex(4)}"
            ),
            "timestamp": timestamp,
            "data": payload,
        }
        with self._connections_lock:
            self._event_history.append(event)

        loop = self._event_loop
        if loop is not None and loop.is_running():
            try:
                try:
                    running_loop = asyncio.get_running_loop()
                except RuntimeError:
                    running_loop = None
                if running_loop is loop:
                    loop.create_task(self._broadcast_message(event))
                else:
                    asyncio.run_coroutine_threadsafe(
                        self._broadcast_message(event),
                        loop,
                    )
            except RuntimeError:
                self.logger.debug("API event loop unavailable for %s", event_type)
        return event

    def get_recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connections_lock:
            return list(self._event_history)[-max(1, limit) :]

    def _handle_watcher_api_event(self, event_type: str, payload: dict) -> None:
        previous = self._previous_api_event_callback
        if callable(previous):
            try:
                previous(event_type, payload)
            except Exception:
                self.logger.exception("Previous watcher API event callback failed")

        event = self.publish_api_event(event_type, payload)
        if event_type == "job.accepted":
            self._handle_accepted_job_for_workflow(event["data"])

    def _workflow_file_mode(self) -> str:
        mode = (
            str(
                config_get(self.config, "TranslationWorkflow", "file_mode", "user")
                or "user"
            )
            .strip()
            .lower()
        )
        if mode in {"auto", "download"}:
            return "auto"
        if mode in {"none", "disabled", "off"}:
            return "none"
        return "user"

    def _find_file_for_job(self, job_id: str) -> StoredFileEntry | None:
        for entry in self.list_files():
            if str(entry.job_id or "") == str(job_id):
                return entry
        return None

    @staticmethod
    def _entry_to_dict(entry: StoredFileEntry | None) -> dict[str, Any] | None:
        if entry is None:
            return None
        return entry.model_dump()

    def _handle_accepted_job_for_workflow(self, payload: Mapping[str, Any]) -> None:
        job_id = str(payload.get("id") or payload.get("job_id") or "").strip()
        if not job_id:
            return
        job = self.state.get_job(job_id)
        if not isinstance(job, dict):
            job = dict(payload)

        mode = self._workflow_file_mode()
        existing_file = self._find_file_for_job(job_id)
        if existing_file is not None or mode == "none":
            self._start_translation_workflow(
                job_id,
                file_entry=existing_file,
                file_content=None,
                mode=mode,
            )
            return

        if mode == "auto":
            self._request_auto_file_download(job)
            return

        self.state.update_job(
            job_id,
            {
                "file_state": "pending",
                "workflow_state": "waiting_for_file",
                "workflow_file_mode": "user",
            },
        )
        self.state.save_state()
        self.publish_api_event(
            "job.file_pending",
            {
                "job_id": job_id,
                "mode": "user",
                "reason": "waiting for user file upload",
            },
        )

    def _request_auto_file_download(self, job: Mapping[str, Any]) -> None:
        job_id = str(job.get("id") or job.get("job_id") or "").strip()
        if not job_id:
            return
        urls = self._find_download_urls(job)
        self.state.update_job(
            job_id,
            {
                "file_state": "download_requested",
                "workflow_state": "waiting_for_file_download",
                "workflow_file_mode": "auto",
                "download_candidate_urls": urls,
            },
        )
        self.state.save_state()
        self.publish_api_event(
            "job.file_download_requested",
            {"job_id": job_id, "mode": "auto", "candidate_urls": urls},
        )
        if not urls:
            self.publish_api_event(
                "job.file_pending",
                {
                    "job_id": job_id,
                    "mode": "auto",
                    "reason": "no downloadable file URL found in accepted payload",
                },
            )
            return

        threading.Thread(
            target=self._download_job_file,
            args=(job_id, urls[0]),
            daemon=True,
            name=f"WorkflowFileDownload-{job_id}",
        ).start()

    def _find_download_urls(self, value: Any) -> list[str]:
        found: list[str] = []

        def visit(candidate: Any, key_hint: str = "") -> None:
            if isinstance(candidate, dict):
                for key, nested in candidate.items():
                    visit(nested, str(key).lower())
                return
            if isinstance(candidate, list):
                for nested in candidate:
                    visit(nested, key_hint)
                return
            if not isinstance(candidate, str):
                return
            text = candidate.strip()
            if not text.startswith(("http://", "https://")):
                return
            lowered = f"{key_hint} {text}".lower()
            if any(
                token in lowered
                for token in ("download", "file", "attachment", "source", "asset")
            ):
                found.append(text)

        visit(value)
        deduped: list[str] = []
        seen: set[str] = set()
        for url in found:
            if url in seen:
                continue
            seen.add(url)
            deduped.append(url)
        return deduped

    def _download_headers(self, *, url: str = "") -> dict[str, str]:
        headers: dict[str, str] = {}
        user_session = str(
            config_get(self.config, "WebSocket", "user_session", "") or ""
        ).strip()
        if user_session and not user_session.startswith("REPLACE_WITH"):
            # Only attach session cookie to gengo.com hosts
            host = urlparse(url).hostname or "" if url else ""
            if host == "gengo.com" or host.endswith(".gengo.com"):
                headers["Cookie"] = f"my_gengo_session={user_session}"
        user_agent = str(
            config_get(self.config, "Network", "browser_user_agent", "") or ""
        ).strip()
        if user_agent:
            headers["User-Agent"] = user_agent
        return headers

    @staticmethod
    def _filename_from_download_response(url: str, response: requests.Response) -> str:
        disposition = response.headers.get("content-disposition", "")
        match = re.search(r'filename="?([^";]+)"?', disposition)
        if match:
            return Path(match.group(1)).name
        parsed_name = Path(unquote(urlparse(url).path)).name
        return parsed_name or "gengo-source-file.bin"

    def _download_job_file(self, job_id: str, url: str) -> None:
        try:
            timeout_sec = float(
                config_float(
                    self.config,
                    "TranslationWorkflow",
                    "download_timeout_sec",
                    30.0,
                )
            )
            response = requests.get(
                url,
                headers=self._download_headers(url=url),
                timeout=timeout_sec,
            )
            response.raise_for_status()
            entry = self.save_uploaded_file(
                self._filename_from_download_response(url, response),
                response.content,
                content_type=response.headers.get("content-type"),
                job_id=job_id,
            )
            self._handle_stored_file_for_job(
                entry,
                content=response.content,
                mode="auto",
            )
        except Exception as exc:
            self.state.update_job(
                job_id,
                {
                    "file_state": "download_failed",
                    "workflow_state": "waiting_for_file",
                    "file_download_error": str(exc),
                },
            )
            self.state.save_state()
            self.publish_api_event(
                "job.file_download_failed",
                {"job_id": job_id, "url": url, "error": str(exc)},
            )

    @staticmethod
    def _decode_file_text(
        content: bytes | None,
        *,
        filename: str = "",
        content_type: str | None = None,
        max_chars: int = 250000,
    ) -> str:
        if not content:
            return ""
        lowered_name = filename.lower()
        lowered_type = str(content_type or "").lower()
        text_like = (
            lowered_type.startswith("text/")
            or any(token in lowered_type for token in ("json", "xml", "csv"))
            or lowered_name.endswith((".txt", ".md", ".csv", ".json", ".xml", ".html"))
        )
        if not text_like or b"\x00" in content[:4096]:
            return ""
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return content.decode(encoding)[:max_chars]
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")[:max_chars]

    def _handle_stored_file_for_job(
        self,
        entry: StoredFileEntry,
        *,
        content: bytes | None,
        mode: str,
    ) -> None:
        file_payload = self._entry_to_dict(entry) or {}
        if entry.job_id:
            self.state.update_job(
                entry.job_id,
                {
                    "file_state": "received",
                    "workflow_state": "file_received",
                    "workflow_file_mode": mode,
                    "workflow_file": file_payload,
                },
            )
            self.state.save_state()
        self.publish_api_event(
            "job.file_received",
            {
                "job_id": entry.job_id,
                "mode": mode,
                "file": file_payload,
            },
        )
        if entry.job_id:
            self._start_translation_workflow(
                entry.job_id,
                file_entry=entry,
                file_content=content,
                mode=mode,
            )

    def _start_translation_workflow(
        self,
        job_id: str,
        *,
        file_entry: StoredFileEntry | None,
        file_content: bytes | None,
        mode: str,
    ) -> dict[str, Any] | None:
        job = self.state.get_job(job_id)
        if not isinstance(job, dict):
            return None

        file_payload = self._entry_to_dict(file_entry)
        max_chars = config_int(
            self.config,
            "TranslationWorkflow",
            "file_text_max_chars",
            250000,
        )
        file_text = ""
        if file_entry is not None:
            if file_content is None:
                path = self.get_file_path(file_entry.stored_name)
                if path is not None and path.is_file():
                    file_content = path.read_bytes()
            file_text = self._decode_file_text(
                file_content,
                filename=file_entry.original_name if file_entry else "",
                content_type=file_entry.content_type if file_entry else None,
                max_chars=max_chars,
            )

        source_text = str(job.get("accepted_source_text") or "")
        workflow = {
            "id": f"translation:{job_id}:{int(time.time() * 1000)}",
            "job_id": job_id,
            "state": "started",
            "mode": mode,
            "started_at": time.time(),
            "source_text": source_text,
            "segments": job.get("accepted_segments") or [],
            "file": file_payload,
            "file_text": file_text,
            "accepted_workbench": job.get("accepted_workbench"),
        }
        self.state.update_job(
            job_id,
            {
                "workflow_state": "started",
                "translation_workflow": workflow,
                "workflow_started_at": workflow["started_at"],
            },
        )
        self.state.save_state()
        self.publish_api_event("translation.workflow.started", workflow)

        submitter = getattr(self.watcher, "_submit_job_to_translation_app_async", None)
        if callable(submitter):
            submitter({**job, "translation_workflow": workflow})
        return workflow

    def get_config(self) -> List[ConfigSection]:
        """Get current configuration."""
        sections = []
        # Use the proper config access methods
        for section_name in self.config.config.keys():
            section_data = {}
            for key in self.config.config[section_name].keys():
                try:
                    # Try to get the value using the appropriate method based on type
                    default_val = self.config.config[section_name][key]
                    if isinstance(default_val, bool):
                        value = self.config.getboolean(section_name, key, default_val)
                    elif isinstance(default_val, int):
                        value = self.config.getint(section_name, key, default_val)
                    elif isinstance(default_val, float):
                        value = self.config.getfloat(section_name, key, default_val)
                    else:
                        value = self.config.get(section_name, key, default_val)
                    section_data[key] = value
                except Exception:
                    # Fallback to direct access if method fails
                    section_data[key] = self.config.config[section_name][key]
            sections.append(ConfigSection(section=section_name, options=section_data))
        return sections

    def update_config(self, section: str, option: str, value: str) -> bool:
        """Update configuration value."""
        try:
            self.watcher.set_config_value(section, option, value)
            return True
        except Exception as e:
            self.logger.exception(f"Failed to update config {section}.{option}: {e}")
            return False

    def execute_command(
        self, command: str, args: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Execute a watcher command."""
        try:
            if command == "check":
                self.watcher.check_now_event.set()
                return {"status": "success", "message": "Check triggered"}
            elif command == "pause":
                self.watcher.pause_monitoring()
                return {"status": "success", "message": "Watcher paused"}
            elif command == "resume":
                self.watcher.resume_monitoring()
                return {"status": "success", "message": "Watcher resumed"}
            elif command == "cancel":
                success = self.watcher.cancel_current_job_sync()
                if success:
                    return {"status": "success", "message": "Current job cancelled"}
                return {
                    "status": "error",
                    "message": "No active job to cancel or cancellation failed",
                }
            elif command in {"ping", "notify"}:
                self.watcher.queue_websocket_test_command(command)
                return {
                    "status": "success",
                    "message": f"WebSocket {command} test queued",
                }
            else:
                return {"status": "error", "message": f"Unknown command: {command}"}
        except Exception as e:
            # Log full details server-side, but return a generic error message
            self.logger.exception(
                f"Unexpected error executing watcher command '%s': %s",
                command,
                e,
            )
            return {
                "status": "error",
                "message": "Internal command execution error",
            }

    async def broadcast_status_update(self):
        """Broadcast status update to all connected WebSocket clients."""
        status = self.get_status()
        message = {"type": "status_update", "data": status.model_dump()}
        await self._broadcast_message(message)

    async def _broadcast_message(self, message: Mapping[str, Any]) -> None:
        with self._connections_lock:
            connections = list(self._active_connections)

        disconnected = []
        for connection in connections:
            try:
                await connection.send_json(dict(message))
            except Exception:
                disconnected.append(connection)

        if disconnected:
            with self._connections_lock:
                # Clean up disconnected clients
                for conn in disconnected:
                    if conn in self._active_connections:
                        self._active_connections.remove(conn)

    def shutdown(self):
        """Shutdown the web API and watcher."""
        self.logger.info("Shutting down WebAPI")
        if (
            getattr(self.watcher, "on_api_event_callback", None)
            is self._api_event_callback
        ):
            self.watcher.on_api_event_callback = self._previous_api_event_callback
        if self._manage_watcher_lifecycle:
            self.watcher.handle_exit()


# Global API instance
api_instance: Optional[WebAPI] = None
shared_runtime_context: Optional[Dict[str, Any]] = None


PROM_API_INITIALIZED = Gauge(
    "gengowatcher_api_initialized",
    "Whether the GengoWatcher web API has been initialized.",
)
PROM_API_INITIALIZED.set_function(lambda: 1.0 if api_instance else 0.0)

ensure_watcher_metrics_registered(
    watcher_provider=lambda: api_instance.watcher if api_instance else None
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager."""
    global api_instance, shared_runtime_context

    # Startup
    logger = logging.getLogger("gengowatcher.web")
    try:
        runtime_context = shared_runtime_context
        shared_watcher = None
        start_watcher_thread = True
        if runtime_context:
            config = runtime_context["config"]
            state = runtime_context["state"]
            logger = runtime_context.get("logger") or logger
            shared_watcher = runtime_context.get("watcher")
            start_watcher_thread = bool(
                runtime_context.get("start_watcher_thread", True)
            )
        else:
            # Check if config exists, create it if needed
            from pathlib import Path

            config_path = Path(AppConfig.CONFIG_FILE)
            if not config_path.exists():
                logger.info("Creating default %s for web API", AppConfig.CONFIG_FILE)
                config_path.write_text(
                    AppConfig._dump_toml(AppConfig.DEFAULT_CONFIG),
                    encoding="utf-8",
                )
                logger.info(
                    "Default config created. Please review %s before using the web API.",
                    AppConfig.CONFIG_FILE,
                )

            config = AppConfig()
            state = AppState(logger=logger)

        # Initialize authenticator with config token
        api_token = config.get("WebServer", "auth_token")

        if not api_token or api_token == "REPLACE_WITH_YOUR_WEB_API_TOKEN":
            api_token = secrets.token_urlsafe(32)
            config.set("WebServer", "auth_token", api_token)
            config.save_config()
            logger.warning(
                "No WebServer auth_token found or it was a placeholder. Generated a new one."
            )
            logger.warning(
                "Check %s [WebServer] for the auth_token value.",
                AppConfig.CONFIG_FILE,
            )

        global authenticator
        authenticator = APIAuthenticator(api_token)

        api_instance = WebAPI(
            config,
            state,
            logger,
            watcher=shared_watcher,
            start_watcher_thread=start_watcher_thread,
        )
        logger.info("WebAPI started successfully")
    except Exception as e:
        logger.exception(f"Failed to start WebAPI: {e}")
        raise

    yield

    # Shutdown
    if api_instance:
        api_instance.shutdown()
    shared_runtime_context = None


# Create FastAPI app
app = FastAPI(
    title="GengoWatcher API",
    description="Web API for GengoWatcher job monitoring application",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/metrics", make_asgi_app())

# Add CORS middleware with security restrictions
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",  # Vite dev server
        "http://127.0.0.1:5173",
        "http://localhost:5174",  # Vite dev server (alternative port)
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# Mount static files for React app
static_path = os.path.join(os.path.dirname(__file__), "..", "..", "static", "web")
if os.path.exists(static_path):
    app.mount("/web", StaticFiles(directory=static_path, html=True), name="web")
else:
    logging.getLogger("gengowatcher.web").warning(
        f"Static files directory not found: {static_path}"
    )


async def verify_auth(credentials: HTTPAuthorizationCredentials = Depends(SECURITY)):
    """Verify API authentication."""
    if not authenticator.authenticate(credentials):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True


@app.get("/api/status", response_model=WatcherStatus)
async def get_status(authenticated: bool = Depends(verify_auth)):
    """Get current watcher status."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")
    try:
        return api_instance.get_status()
    except Exception as e:
        api_instance.logger.exception(f"Error getting status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/jobs")
async def get_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    min_reward: Optional[float] = Query(None, ge=0),
    max_reward: Optional[float] = Query(None, ge=0),
    search: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    authenticated: bool = Depends(verify_auth),
):
    """Get recent jobs with pagination and filtering."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")

    try:
        # If source is specified as 'csv' or if we want to include CSV data, read from CSV
        if source == "csv":
            result = api_instance.get_jobs_from_csv(
                limit=limit,
                page=page,
                min_reward=min_reward,
                max_reward=max_reward,
                search_term=search,
            )
            return result
        else:
            # Default behavior - get recent jobs from state
            result = api_instance.get_recent_jobs(limit, page)
            return result
    except Exception as e:
        api_instance.logger.exception(f"Error getting jobs: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/events")
async def get_events(
    limit: int = Query(100, ge=1, le=500),
    authenticated: bool = Depends(verify_auth),
):
    """Return recent lifecycle events published to API websockets."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")
    return {"events": api_instance.get_recent_events(limit)}


@app.post("/api/jobs/{job_id}/accept")
async def accept_job(job_id: str, authenticated: bool = Depends(verify_auth)):
    """Force accept a job by ID."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")

    try:
        success = await api_instance.accept_job(job_id)

        if success:
            return {
                "status": "success",
                "message": f"Job {job_id} accepted successfully",
            }
        else:
            raise HTTPException(
                status_code=500, detail=f"Failed to accept job {job_id}"
            )

    except HTTPException:
        raise
    except Exception as e:
        api_instance.logger.exception(f"Error accepting job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/api/jobs/cancel")
async def cancel_current_job(authenticated: bool = Depends(verify_auth)):
    """Cancel the currently tracked job."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")

    try:
        success = await api_instance.cancel_current_job()
        if success:
            return {"status": "success", "message": "Current job cancelled"}
        raise HTTPException(
            status_code=400, detail="No active job to cancel or cancellation failed"
        )
    except HTTPException:
        raise
    except Exception as e:
        api_instance.logger.exception(f"Error cancelling current job: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def _receive_job_discovered_api_event(request: Request):
    """Receive a signed external job-discovery API event."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")

    raw_body = await request.body()
    try:
        return api_instance.process_incoming_job_webhook(raw_body, request.headers)
    except WebhookError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as e:
        api_instance.logger.exception(f"Error processing job discovery event: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@app.post("/api/jobs/discovered")
async def receive_job_discovered_api_event(request: Request):
    return await _receive_job_discovered_api_event(request)


@app.post("/api/webhooks/jobs/discovered", include_in_schema=False)
async def receive_job_discovered_webhook(request: Request):
    return await _receive_job_discovered_api_event(request)


async def _get_api_event_audit(limit: int) -> dict[str, Any]:
    """Return recent API event audit records for local debugging."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")
    try:
        return {
            "entries": api_instance.get_webhook_audit_entries(limit),
            "audit_log_path": str(api_instance.webhook_audit_logger.path),
        }
    except Exception as e:
        api_instance.logger.exception(f"Error reading API event audit log: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@app.get("/api/events/audit")
async def get_api_event_audit(
    limit: int = Query(50, ge=1, le=500),
    authenticated: bool = Depends(verify_auth),
):
    return await _get_api_event_audit(limit)


@app.get("/api/webhooks/debug/audit", include_in_schema=False)
async def get_webhook_audit(
    limit: int = Query(50, ge=1, le=500),
    authenticated: bool = Depends(verify_auth),
):
    return await _get_api_event_audit(limit)


@app.get("/api/config", response_model=List[ConfigSection])
async def get_config(authenticated: bool = Depends(verify_auth)):
    """Get current configuration."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")
    try:
        return api_instance.get_config()
    except Exception as e:
        api_instance.logger.exception(f"Error getting config: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.put("/api/config/{section}/{option}")
async def update_config(
    section: str, option: str, value: str, authenticated: bool = Depends(verify_auth)
):
    """Update configuration value."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")

    # Validate input
    if not section or not option:
        raise HTTPException(status_code=400, detail="Section and option are required")

    try:
        success = api_instance.update_config(section, option, value)
        if not success:
            raise HTTPException(
                status_code=400, detail="Failed to update configuration"
            )
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        api_instance.logger.exception(f"Error updating config: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/commands")
async def execute_command(
    request: CommandRequest, authenticated: bool = Depends(verify_auth)
):
    """Execute a watcher command."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")

    try:
        result = api_instance.execute_command(request.command, request.args)
        if result["status"] == "error":
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        api_instance.logger.exception(f"Error executing command: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/files", response_model=List[StoredFileEntry])
async def list_uploaded_files(authenticated: bool = Depends(verify_auth)):
    """List files available through the built-in file transfer store."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")
    try:
        return api_instance.list_files()
    except Exception as e:
        api_instance.logger.exception(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB


@app.post("/api/files/upload", response_model=StoredFileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    job_id: str | None = Form(None),
    tier: str | None = Form(None),
    word_count: int | None = Form(None),
    value: float | None = Form(None),
    authenticated: bool = Depends(verify_auth),
):
    """Store an uploaded file in the local file transfer directory."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")
    try:
        # Read file in chunks to avoid loading entire file into memory
        content = b""
        chunk_size = 1024 * 1024  # 1 MB chunks
        while True:
            read_all_at_once = False
            try:
                chunk = await file.read(chunk_size)
            except TypeError:
                chunk = await file.read()
                read_all_at_once = True
            if not chunk:
                break
            content += chunk
            if len(content) > MAX_UPLOAD_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum size is {MAX_UPLOAD_SIZE} bytes",
                )
            if read_all_at_once:
                break

        entry = api_instance.save_uploaded_file(
            file.filename or "upload.bin",
            content,
            content_type=file.content_type,
            job_id=job_id,
            tier=tier,
            word_count=word_count,
            value=value,
        )
        api_instance._handle_stored_file_for_job(
            entry,
            content=content,
            mode="user",
        )
        return StoredFileUploadResponse(status="success", file=entry)
    except HTTPException:
        raise
    except Exception as e:
        api_instance.logger.exception(f"Error uploading file: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@app.get("/api/files/{stored_name}")
async def download_file(
    stored_name: str,
    authenticated: bool = Depends(verify_auth),
):
    """Download a file from the local file transfer directory."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")
    if not api_instance._is_valid_stored_name(stored_name):
        raise HTTPException(status_code=400, detail="Invalid file name")
    entry = api_instance.get_file_entry(stored_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="File not found")
    try:
        storage_dir = api_instance._get_file_storage_dir()
        path = api_instance._ensure_within_storage_dir(storage_dir / entry.stored_name)
    except ValueError:
        raise HTTPException(status_code=404, detail="File not found")
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(path), filename=entry.original_name)


@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """WebSocket endpoint for real-time status updates."""
    if not api_instance:
        await websocket.close(code=1011)  # Internal error
        return

    # Simple authentication via query parameter
    api_key = websocket.query_params.get("api_key")
    if not api_key or api_key != authenticator.get_api_key():
        await websocket.close(code=1008)  # Policy violation
        return

    await websocket.accept()
    api_instance._event_loop = asyncio.get_running_loop()

    # Add to active connections
    with api_instance._connections_lock:
        api_instance._active_connections.append(websocket)

    try:
        # Send initial status
        status = api_instance.get_status()
        await websocket.send_json(
            {"type": "status_update", "data": status.model_dump()}
        )
        await websocket.send_json(
            {
                "type": "events_snapshot",
                "events": api_instance.get_recent_events(),
            }
        )

        # Keep connection alive and listen for client messages
        while True:
            # Wait for client messages or timeout
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Handle any client messages if needed
                try:
                    message = json.loads(data)
                    if message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except json.JSONDecodeError:
                    pass  # Ignore invalid JSON
            except asyncio.TimeoutError:
                # Send periodic status updates
                try:
                    status = api_instance.get_status()
                    await websocket.send_json(
                        {"type": "status_update", "data": status.model_dump()}
                    )
                except Exception as e:
                    api_instance.logger.exception(f"Error sending status update: {e}")
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        api_instance.logger.exception(f"WebSocket error: {e}")
    finally:
        # Remove from active connections
        with api_instance._connections_lock:
            try:
                if websocket in api_instance._active_connections:
                    api_instance._active_connections.remove(websocket)
            except ValueError:
                pass  # Already removed


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "GengoWatcher API",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "/api/status",
        "api_key_required": True,
    }


@app.get("/api/auth/key")
async def get_api_key():
    """Get API key for frontend authentication (development only)."""
    # Only allow in development mode
    dev_mode = os.getenv("GENGOWATCHER_DEV_MODE", "false").lower() == "true"
    if not dev_mode:
        raise HTTPException(
            status_code=403,
            detail="This endpoint is only available in development mode",
        )

    return {
        "api_key": authenticator.get_api_key(),
        "warning": "This endpoint should be disabled in production",
    }


@app.get("/api/stats")
async def get_stats(authenticated: bool = Depends(verify_auth)):
    """Get application statistics."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")

    try:
        status = api_instance.get_status()
        jobs_result = api_instance.get_recent_jobs(limit=1000)  # Get all for stats

        total_jobs = jobs_result["pagination"]["total"]
        jobs = jobs_result["jobs"]

        # Calculate statistics
        total_value = sum(job.reward for job in jobs)
        avg_reward = total_value / total_jobs if total_jobs > 0 else 0

        source_counts = {}
        for job in jobs:
            source_counts[job.source] = source_counts.get(job.source, 0) + 1

        return {
            "total_jobs": total_jobs,
            "total_value": round(total_value, 2),
            "average_reward": round(avg_reward, 2),
            "jobs_by_source": source_counts,
            "session_stats": status.session_stats,
            "uptime": status.session_stats.get("uptime", 0),
        }
    except Exception as e:
        api_instance.logger.exception(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    if not api_instance:
        return {
            "status": "unhealthy",
            "detail": "API not initialized",
            "timestamp": time.time(),
        }

    try:
        status = api_instance.get_status()
        return {
            "status": "healthy",
            "watcher_running": status.is_running,
            "websocket_status": status.websocket_status,
            "timestamp": time.time(),
        }
    except Exception as e:
        api_instance.logger.exception(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "detail": "Internal error",
            "timestamp": time.time(),
        }


@app.get("/web/{path:path}")
async def serve_react_app(path: str):
    """Serve React app for any unmatched /web routes."""
    index_path = os.path.join(static_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        raise HTTPException(status_code=404, detail="React app not built yet")


def run_web_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    config: AppConfig | None = None,
    state: AppState | None = None,
    logger: logging.Logger | None = None,
    watcher: Optional[GengoWatcher] = None,
    start_watcher_thread: bool = True,
):
    """Run the web server."""
    if (config is None) != (state is None):
        raise ValueError("config and state must be supplied together")
    if watcher is not None and (config is None or state is None):
        raise ValueError("shared watcher requires config and state")

    _set_shared_runtime_context(
        config=config,
        state=state,
        logger=logger,
        watcher=watcher,
        start_watcher_thread=start_watcher_thread,
    )

    uvicorn.run(app, host=host, port=port, reload=False, log_level="info")


def _set_shared_runtime_context(
    *,
    config: Optional[AppConfig],
    state: Optional[AppState],
    logger: Optional[logging.Logger],
    watcher: Optional[GengoWatcher],
    start_watcher_thread: bool,
) -> None:
    global shared_runtime_context
    if config is not None and state is not None:
        shared_runtime_context = {
            "config": config,
            "state": state,
            "logger": logger,
            "watcher": watcher,
            "start_watcher_thread": start_watcher_thread,
        }
    else:
        shared_runtime_context = None


class ManagedWebServer:
    """Small wrapper around uvicorn.Server so TUI controls can stop it."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8000,
        config: AppConfig | None = None,
        state: AppState | None = None,
        logger: logging.Logger | None = None,
        watcher: GengoWatcher | None = None,
        start_watcher_thread: bool = True,
    ):
        if (config is None) != (state is None):
            raise ValueError("config and state must be supplied together")
        if watcher is not None and (config is None or state is None):
            raise ValueError("shared watcher requires config and state")

        self.host = host
        self.port = port
        self.config = config
        self.state = state
        self.logger = logger or logging.getLogger("gengowatcher.web")
        self.watcher = watcher
        self.start_watcher_thread = start_watcher_thread
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None
        self.startup_error: BaseException | None = None

    def start(self) -> threading.Thread:
        _set_shared_runtime_context(
            config=self.config,
            state=self.state,
            logger=self.logger,
            watcher=self.watcher,
            start_watcher_thread=self.start_watcher_thread,
        )
        uvicorn_config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            reload=False,
            log_level="info",
        )
        self.server = uvicorn.Server(uvicorn_config)
        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="WebServerThread",
        )
        self.thread.gengowatcher_api_host = self.host
        self.thread.gengowatcher_api_port = self.port
        self.thread.gengowatcher_api_server = self
        self.thread.start()
        return self.thread

    def _run(self) -> None:
        try:
            assert self.server is not None
            self.server.run()
        except BaseException as error:
            self.startup_error = error
            if isinstance(error, SystemExit) and error.code in (0, None):
                return
            self.logger.exception("Web API server failed")

    def stop(self, timeout: float = 5.0) -> bool:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=timeout)
        return not (self.thread is not None and self.thread.is_alive())

    def is_alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())


def start_web_server_thread(
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    config: Optional[AppConfig] = None,
    state: Optional[AppState] = None,
    logger: Optional[logging.Logger] = None,
    watcher: Optional[GengoWatcher] = None,
    start_watcher_thread: bool = True,
) -> threading.Thread:
    """Start the web server in a daemon thread and return the thread handle."""
    server = ManagedWebServer(
        host=host,
        port=port,
        config=config,
        state=state,
        logger=logger,
        watcher=watcher,
        start_watcher_thread=start_watcher_thread,
    )
    return server.start()


if __name__ == "__main__":
    run_web_server()
