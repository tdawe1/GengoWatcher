from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
import logging
from pathlib import Path
import tempfile
from typing import Any

from .coordinator import AcceptanceCoordinator
from .flows.accept_flow import wait_for_workbench
from .models import JobIntent, JobSignal
from .profile import BrowserProfileManager
from .protocol import decode_message, encode_message
from .registry import JobRegistry
from .tabs import TabRoles
from .telemetry import BrowserWorkerTelemetry, TimingEvent


@dataclass(slots=True)
class BrowserRuntimeConfig:
    profile_path: Path
    headless: bool = False
    seed_profile_path: Path | None = None
    socket_path: Path = field(
        default_factory=lambda: Path(tempfile.gettempdir())
        / "gengowatcher-browser-worker.sock"
    )
    artifacts_dir: Path = field(
        default_factory=lambda: Path("logs/browser-worker-artifacts")
    )
    accept_timeout_ms: int = 12000


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
        self._record_event("runtime_started", 0.0, profile=str(self.config.profile_path))
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
        await roles.candidate_page.goto(intent.canonical_url, wait_until="domcontentloaded")
        self._record_event("candidate_ready", 0.0, job_id=intent.job_id)
        return roles.candidate_page.url

    async def handle_command(self, payload: dict[str, Any]) -> dict[str, Any]:
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
        return {"ok": True, "job_id": intent.job_id, "url": candidate_url}

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
        socket_path = self.config.socket_path
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        if socket_path.exists():
            socket_path.unlink()

        self._server = await asyncio.start_unix_server(
            self.handle_client,
            path=str(socket_path),
        )
        self._record_event("server_started", 0.0, socket_path=str(socket_path))
        try:
            async with self._server:
                await self._server.serve_forever()
        finally:
            if socket_path.exists():
                socket_path.unlink()
            self._server = None

    async def commit_accept(self, job_id: str, *, accept_selector: str = "text=Accept") -> str:
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
            self._record_event("accept_succeeded", 0.0, job_id=job_id, url=workbench_url)
            return workbench_url
        finally:
            self.coordinator.release()

    async def stop(self) -> None:
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
        self.telemetry.record(TimingEvent(name=name, monotonic_ms=monotonic_ms), **extra)
