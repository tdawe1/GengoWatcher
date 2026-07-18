from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import socket

import pytest
import httpx
import uvicorn
import websockets

from gengowatcher.browser_worker.flows.accept_flow import extract_workbench_payload
from gengowatcher.browser_worker.runtime import BrowserRuntime, BrowserRuntimeConfig
from gengowatcher.gengo_sandbox import SandboxState, create_app

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


async def _wait_for_server(
    server: uvicorn.Server, server_task: asyncio.Task[None]
) -> None:
    for _ in range(100):
        if server.started:
            return
        if server_task.done():
            await server_task
            raise RuntimeError("local Gengo sandbox stopped during startup")
        await asyncio.sleep(0.05)
    raise RuntimeError("local Gengo sandbox did not start")


async def test_browser_worker_accepts_sandbox_job_and_extracts_payload(
    tmp_path: Path,
) -> None:
    if os.environ.get("GENGOWATCHER_RUN_BROWSER_E2E") != "1":
        pytest.skip("set GENGOWATCHER_RUN_BROWSER_E2E=1 to launch a real browser")

    executable = os.environ.get("GENGOWATCHER_BROWSER_EXECUTABLE") or shutil.which(
        "chromium"
    )
    if not executable:
        pytest.skip("no Chromium executable is available")

    host = "127.0.0.1"
    requested_port = int(os.environ.get("GENGOWATCHER_SANDBOX_E2E_PORT", "0"))
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, requested_port))
    port = int(listener.getsockname()[1])
    origin = f"http://{host}:{port}"
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(SandboxState()),
            host=host,
            port=port,
            log_level="warning",
        )
    )
    server_task = asyncio.create_task(server.serve(sockets=[listener]))
    runtime: BrowserRuntime | None = None
    try:
        await _wait_for_server(server, server_task)

        async with websockets.connect(f"ws://{host}:{port}/live-dashboard") as ws:
            await ws.send(
                json.dumps({"user_id": "sandbox-e2e", "user_session": "local"})
            )
            welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            assert welcome == {"type": "welcome", "user_id": "sandbox-e2e"}
            for _ in range(2):
                await asyncio.wait_for(ws.recv(), timeout=2)
            async with httpx.AsyncClient(base_url=origin) as client:
                created = await client.post(
                    "/__sandbox__/jobs",
                    json={
                        "collection_id": 9900,
                        "job_id": 99900,
                        "order_id": 89900,
                        "source": "Live WebSocket E2E source",
                        "reward": 7.5,
                        "unit_count": 4,
                    },
                )
                assert created.status_code == 201
            live_event = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            assert live_event["type"] == "available_collection"
            assert live_event["collection"]["id"] == 9900

        runtime = BrowserRuntime(
            BrowserRuntimeConfig(
                profile_path=tmp_path / "browser-profile",
                headless=True,
                browser_executable_path=Path(executable),
                sandbox_origin=origin,
                artifacts_dir=tmp_path / "artifacts",
            )
        )
        await runtime.start()

        prepared = await runtime.handle_command(
            {
                "type": "job_url",
                "url": f"{origin}/t/jobs/details/34176080",
                "source": "sandbox-e2e",
            }
        )
        assert prepared == {
            "ok": True,
            "job_id": "34176080",
            "url": f"{origin}/t/jobs/details/34176080",
        }

        workbench_url = await runtime.commit_accept(
            "34176080", accept_selector="#accept"
        )
        assert workbench_url.startswith(f"{origin}/t/workbench/34176080")

        roles = await runtime.ensure_tabs()
        envelope = await extract_workbench_payload(roles.candidate_page)
        assert envelope is not None
        assert envelope["source"] == "window.__GENGO_WORKBENCH_DATA__"
        payload = envelope["payload"]
        assert payload["summary"]["status"] == "incomplete"
        assert payload["summary"]["order_id"] == 8012277
        assert payload["jobs"][0]["id"] == 98938270
    finally:
        if runtime is not None:
            await runtime.stop()
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=5)
        finally:
            listener.close()
