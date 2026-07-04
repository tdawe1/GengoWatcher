from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
import os
import logging
from pathlib import Path
import secrets
import stat
import tempfile
from typing import Any

from .coordinator import AcceptanceCoordinator
from .flows.accept_flow import (
    dumps_workbench_payload,
    extract_workbench_payload,
    parse_workbench_job_id,
    wait_for_workbench,
)
from .models import JobIntent, JobSignal
from .profile import BrowserProfileManager
from .protocol import decode_message, encode_message
from .registry import JobRegistry
from .tabs import TabRoles
from .telemetry import BrowserWorkerTelemetry, TimingEvent


def default_browser_worker_socket_dir() -> Path:
    user_id = str(os.getuid()) if hasattr(os, "getuid") else "user"
    return Path(tempfile.gettempdir()) / f"gengowatcher-browser-worker-{user_id}"


def default_browser_worker_socket_path() -> Path:
    return default_browser_worker_socket_dir() / "gengowatcher-browser-worker.sock"


@dataclass(slots=True)
class BrowserRuntimeConfig:
    profile_path: Path
    headless: bool = False
    seed_profile_path: Path | None = None
    socket_path: Path = field(default_factory=default_browser_worker_socket_path)
    artifacts_dir: Path = field(
        default_factory=lambda: Path("logs/browser-worker-artifacts")
    )
    accept_timeout_ms: int = 12000
    auth_token: str = ""


class BrowserRuntime:
    def __init__(
        self,
        config: BrowserRuntimeConfig,
        logger: logging.Logger | None = None,
        telemetry: BrowserWorkerTelemetry | None = None,
    ):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.profile_manager = BrowserProfileManager(
            config.profile_path,
            seed_profile=config.seed_profile_path,
        )
        self.coordinator = AcceptanceCoordinator()
        self.registry = JobRegistry()
        self.telemetry = telemetry
        self.tab_roles: TabRoles | None = None
        self.context: Any = None
        self._playwright: Any = None
        self._server: asyncio.AbstractServer | None = None
        self._page_observer_task: asyncio.Task | None = None
        self._captured_workbench_ids: set[str] = set()
        self._workbench_payload_attempts: dict[str, int] = {}

    async def start(self) -> "BrowserRuntime":
        from playwright.async_api import async_playwright

        self.profile_manager.ensure_ready()
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        self.context = await self._playwright.chromium.launch_persistent_context(
            str(self.config.profile_path),
            headless=self.config.headless,
        )
        await self.ensure_tabs()
        self._page_observer_task = asyncio.create_task(
            self._observe_browser_pages(),
            name="gengowatcher-browser-page-observer",
        )
        self._record_event(
            "runtime_started", 0.0, profile=str(self.config.profile_path)
        )
        return self

    async def ensure_tabs(self) -> TabRoles:
        if self.context is None:
            raise RuntimeError("browser runtime has not been started")

        pages = list(self.context.pages)
        while len(pages) < 2:
            pages.append(await self.context.new_page())
        self.tab_roles = TabRoles(hold_page=pages[0], candidate_page=pages[1])
        return self.tab_roles

    async def prepare_candidate(self, intent) -> str:
        roles = await self.ensure_tabs()
        self.registry.register(intent)
        await roles.candidate_page.goto(
            intent.canonical_url, wait_until="domcontentloaded"
        )
        self._record_event("candidate_ready", 0.0, job_id=intent.job_id)
        return roles.candidate_page.url

    async def handle_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._authorize_payload(payload)
        command_type = payload.get("type")
        if command_type != "job_url":
            raise ValueError(f"unsupported browser worker command: {command_type}")

        intent = JobIntent.from_signal(
            JobSignal(
                source=str(payload.get("source") or ""),
                direct_url=str(payload.get("url") or ""),
                metadata=dict(payload.get("metadata") or {}),
            )
        )
        candidate_url = await self.prepare_candidate(intent)
        response: dict[str, Any] = {
            "ok": True,
            "job_id": intent.job_id,
            "url": candidate_url,
        }

        if not payload.get("track_acceptance"):
            return response

        timeout_ms = self._coerce_acceptance_timeout_ms(
            payload.get("acceptance_timeout_ms")
        )
        if timeout_ms <= 0:
            response["accepted"] = False
            response["acceptance_tracking"] = {
                "status": "disabled",
                "reason": "acceptance_timeout_ms is not positive",
            }
            return response

        tracking = await self.wait_for_manual_acceptance_capture(
            intent.job_id,
            timeout_ms=timeout_ms,
        )
        response.update(tracking)
        return response

    @staticmethod
    def _coerce_acceptance_timeout_ms(value: object) -> int:
        try:
            return max(0, int(float(value or 0)))
        except (TypeError, ValueError):
            return 0

    def _authorize_payload(self, payload: dict[str, Any]) -> None:
        expected_token = str(self.config.auth_token or "")
        if not expected_token:
            return
        supplied_token = str(payload.get("auth_token") or "")
        if not secrets.compare_digest(supplied_token, expected_token):
            raise PermissionError("browser worker command authorization failed")

    async def handle_client(self, reader, writer) -> None:
        response: dict[str, Any] | None = None
        try:
            raw_payload = await reader.readline()
            if not raw_payload:
                return

            payload = decode_message(raw_payload)
            response = await self.handle_command(payload)
        except Exception as exc:
            self.logger.exception("browser worker command failed")
            response = {"ok": False, "error": str(exc)}

        writer.write(encode_message(response))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def serve_forever(self) -> None:
        socket_path = self._prepare_socket_path()

        self._server = await asyncio.start_unix_server(
            self.handle_client,
            path=str(socket_path),
        )
        self._secure_socket_file(socket_path)
        self._record_event("server_started", 0.0, socket_path=str(socket_path))
        try:
            async with self._server:
                await self._server.serve_forever()
        finally:
            if socket_path.exists():
                socket_path.unlink()
            self._server = None

    def _prepare_socket_path(self) -> Path:
        socket_path = self.config.socket_path
        socket_dir = socket_path.parent
        if socket_dir.exists():
            if not socket_dir.is_dir():
                raise ValueError(
                    f"browser worker socket parent is not a directory: {socket_dir}"
                )
            mode = stat.S_IMODE(socket_dir.stat().st_mode)
            if socket_dir == default_browser_worker_socket_dir() and mode != 0o700:
                os.chmod(socket_dir, 0o700)
            elif mode & 0o077:
                self.logger.warning(
                    "browser worker socket directory %s is accessible by group/other "
                    "(mode %03o); prefer a 0700 directory for browser profile control",
                    socket_dir,
                    mode,
                )
        else:
            socket_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if socket_path.exists():
            socket_path.unlink()
        return socket_path

    def _secure_socket_file(self, socket_path: Path) -> None:
        try:
            os.chmod(socket_path, 0o600)
        except OSError as exc:
            self.logger.warning(
                "failed to restrict browser worker socket permissions for %s: %s",
                socket_path,
                exc,
            )

    async def commit_accept(
        self, job_id: str, *, accept_selector: str = "text=Accept"
    ) -> str:
        if not self.coordinator.acquire():
            raise RuntimeError("another acceptance routine is already running")
        try:
            roles = await self.ensure_tabs()
            await roles.candidate_page.click(accept_selector)
            workbench_url = await wait_for_workbench(
                roles.candidate_page,
                job_id,
                timeout_ms=self.config.accept_timeout_ms,
            )
            self._record_event(
                "accept_succeeded", 0.0, job_id=job_id, url=workbench_url
            )
            return workbench_url
        finally:
            self.coordinator.release()

    async def _observe_browser_pages(self) -> None:
        while self.context is not None:
            try:
                await self._observe_browser_pages_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive runtime logging
                self.logger.warning("browser page observer failed: %s", exc)
            await asyncio.sleep(0.75)

    async def _observe_browser_pages_once(self) -> None:
        if self.context is None:
            return
        pages = list(getattr(self.context, "pages", []) or [])
        for page in pages:
            await self._capture_workbench_page_if_ready(page)

    async def _capture_workbench_page_if_ready(self, page) -> None:
        url = str(getattr(page, "url", "") or "")
        job_id = parse_workbench_job_id(url)
        if not job_id or job_id in self._captured_workbench_ids:
            return

        attempts = self._workbench_payload_attempts.get(job_id, 0)
        self._workbench_payload_attempts[job_id] = attempts + 1

        payload = await extract_workbench_payload(page)
        if payload:
            self._record_accepted_workbench_payload(job_id, url, payload)
            return

        if attempts == 0:
            self._record_event("workbench_detected", 0.0, job_id=job_id, url=url)

    def _record_accepted_workbench_payload(
        self, job_id: str, url: str, payload: dict[str, Any]
    ) -> None:
        if job_id in self._captured_workbench_ids:
            return
        self._captured_workbench_ids.add(job_id)
        # Prune stale entries to prevent unbounded growth
        if len(self._captured_workbench_ids) > 200:
            self._captured_workbench_ids = set(list(self._captured_workbench_ids)[-100:])
        if job_id in self._workbench_payload_attempts:
            del self._workbench_payload_attempts[job_id]
        self._record_event(
            "accepted_workbench_payload",
            0.0,
            job_id=job_id,
            url=url,
            source=payload.get("source"),
            payload=payload.get("payload"),
        )
        if self.telemetry is not None:
            self.telemetry.write_text_artifact(
                f"accepted-workbench-{job_id}.json",
                dumps_workbench_payload(payload) + "\n",
            )

    async def wait_for_manual_acceptance_capture(
        self,
        job_id: str,
        *,
        timeout_ms: int,
    ) -> dict[str, Any]:
        roles = await self.ensure_tabs()
        try:
            workbench_url = await wait_for_workbench(
                roles.candidate_page,
                job_id,
                timeout_ms=timeout_ms,
            )
        except Exception as exc:
            if exc.__class__.__name__ != "TimeoutError":
                raise
            # Note: Would use PlaywrightTimeoutError directly, but keeping
            # class name check for compatibility without playwright import dependency
            self._record_event(
                "manual_accept_timeout",
                0.0,
                job_id=job_id,
                timeout_ms=timeout_ms,
            )
            return {
                "accepted": False,
                "acceptance_tracking": {
                    "status": "timeout",
                    "timeout_ms": timeout_ms,
                },
            }

        payload = await extract_workbench_payload(roles.candidate_page)
        response: dict[str, Any] = {
            "accepted": True,
            "workbench_url": workbench_url,
            "acceptance_tracking": {
                "status": "captured" if payload else "accepted_no_payload",
                "timeout_ms": timeout_ms,
            },
        }
        if payload:
            response["accepted_workbench"] = payload
            self._record_accepted_workbench_payload(job_id, workbench_url, payload)
        else:
            self._record_event(
                "manual_accept_no_payload",
                0.0,
                job_id=job_id,
                url=workbench_url,
            )
        return response

    async def stop(self) -> None:
        if self._page_observer_task is not None:
            self._page_observer_task.cancel()
            try:
                await self._page_observer_task
            except asyncio.CancelledError:
                pass
            self._page_observer_task = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self.context is not None:
            await self.context.close()
            self.context = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._record_event("runtime_stopped", 0.0)

    def _record_event(self, name: str, monotonic_ms: float, **extra: object) -> None:
        if self.telemetry is None:
            return
        self.telemetry.record(
            TimingEvent(name=name, monotonic_ms=monotonic_ms), **extra
        )
