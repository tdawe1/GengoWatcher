from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest


pytestmark = pytest.mark.e2e

API_TOKEN = "e2e-smoke-token"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    authenticated: bool = True,
) -> tuple[int, dict]:
    headers = {"Accept": "application/json"}
    if authenticated:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def _wait_until_ready(base_url: str, process: subprocess.Popen, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            pytest.fail(
                f"web process exited before readiness ({process.returncode})\n{output}"
            )
        try:
            status, _payload = _request(base_url, "/api/status")
            if status == 200:
                return
        except (URLError, TimeoutError, ConnectionError) as error:
            last_error = error
        time.sleep(0.1)
    pytest.fail(f"web API did not become ready: {last_error}")


def _write_config(workdir: Path) -> None:
    (workdir / "config.toml").write_text(
        """
[Watcher]
feed_url = "https://example.invalid/jobs.rss"
check_interval = 3600
min_reward = 0.0
enable_notifications = false
enable_sound = false

[WebSocket]
enable_websocket = false

[BrowserJobs]
enabled = false

[NativeBrowserListener]
enabled = false

[EmailMonitor]
enabled = false

[WebsiteMonitor]
enabled = false

[WebServer]
auth_token = "e2e-smoke-token"
event_history_size = 20

[Webhooks]
incoming_enabled = true
require_signature = false
audit_enabled = true
debug_enabled = true
audit_log_path = "logs/webhooks.jsonl"

[Logging]
log_main_enabled = false
log_stdio_enabled = true
log_all_entries_enabled = false

[Paths]
browser_path = "/bin/true"
browser_args = "{url}"
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_web_only_process_ingests_persists_and_serves_job(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    _write_config(tmp_path)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "gengowatcher.main",
            "--web-only",
            "--web-port",
            str(port),
        ],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        _wait_until_ready(base_url, process, timeout=15)

        unauthorized_status, _ = _request(
            base_url, "/api/status", authenticated=False
        )
        assert unauthorized_status == 401

        event = {
            "event_id": "e2e-job-123",
            "event_type": "job.discovered",
            "job_id": "123",
            "title": "JA to EN smoke job",
            "reward": 12.5,
            "url": "https://gengo.com/t/jobs/details/123",
            "source": "e2e-smoke",
            "lang_pair": "JA-EN",
            "word_count": 250,
        }
        status, accepted = _request(
            base_url,
            "/api/jobs/discovered",
            method="POST",
            payload=event,
        )
        assert status == 200
        assert accepted["status"] == "processed"
        assert accepted["job_id"] == "123"

        duplicate_status, duplicate = _request(
            base_url,
            "/api/jobs/discovered",
            method="POST",
            payload=event,
        )
        assert duplicate_status == 200
        assert duplicate["status"] == "duplicate"

        jobs_status, jobs = _request(base_url, "/api/jobs")
        assert jobs_status == 200
        assert jobs["pagination"]["total"] == 1
        assert jobs["jobs"][0]["id"] == "123"
        assert jobs["jobs"][0]["reward"] == 12.5

        events_status, events = _request(base_url, "/api/events")
        assert events_status == 200
        event_types = {item["type"] for item in events["events"]}
        assert {"job.discovered", "job.details"} <= event_types

        state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert [job["id"] for job in state["jobs"]] == ["123"]
        audit_lines = (tmp_path / "logs" / "webhooks.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        audit_stages = {json.loads(line)["stage"] for line in audit_lines}
        assert {"received", "processed", "duplicate"} <= audit_stages

        # The CLI performs a one-second post-start health window before entering
        # its interrupt-aware web-only wait loop.
        time.sleep(1.1)
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        try:
            output, _ = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate(timeout=5)
            pytest.fail(f"web process did not stop after SIGINT\n{output}")

    assert process.returncode == 0, output
