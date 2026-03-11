# Browser Worker Black-Box Test Procedure

## Purpose

This procedure standardizes local browser-worker runs so black-box comparison tests are measuring one variable set at a time.

## Preconditions

1. Configure `BrowserWorker.enabled = true`.
2. Set `BrowserWorker.socket_path` to a writable Unix socket path.
3. Set `BrowserWorker.profile_path` to the dedicated persistent worker profile.
4. Optionally set `BrowserWorker.seed_profile_path` once if you want to bootstrap from an existing logged-in profile.
5. Verify the dedicated profile is logged into Gengo before any live validation.

## Start The Worker

Run the worker in headed mode with the dedicated profile:

```bash
PYTHONPATH=src python -m gengowatcher.browser_worker.main \
  --profile-path profiles/browser-worker \
  --socket-path /tmp/gengowatcher-browser-worker.sock
```

Keep the browser visible. The worker is expected to own two long-lived tabs:

- `hold_tab`
- `candidate_tab`

## Run Deterministic Verification

These checks do not require a live job:

```bash
python -m pytest tests/test_browser_worker_protocol.py tests/test_browser_worker_profile.py tests/test_browser_worker_runtime.py tests/test_browser_worker_tabs.py tests/test_browser_worker_coordinator.py tests/test_browser_worker_registry.py tests/test_accept_flow.py tests/test_swap_flow.py tests/test_accept_swap_simulation.py tests/test_browser_worker_telemetry.py tests/test_browser_worker_client.py -v
```

## Manual Validation Sequence

1. Start the worker and confirm the dedicated profile stays open.
2. Start GengoWatcher with the browser worker enabled.
3. Verify new RSS/WebSocket-discovered jobs are submitted to the local worker socket.
4. Record a manual control run with the same logged-in profile.
5. Record a Playwright worker run with the same profile and same general workflow.
6. Compare success, failure, cancellation, and any challenge outcomes.

## Rules For Manual Runs

1. Keep the browser headed for every run.
2. Do not require a live job for automated verification.
3. Treat live jobs as manual validation only.
4. Use the first direct job URL as authoritative when comparing runs.
5. Treat workbench arrival at `/t/workbench/<job_id>` as the v1 accept-success boundary.
6. Treat cancel-triggered reload/navigation start as the v1 swap gate.

## Evidence To Save

- Browser worker JSONL telemetry under `logs/browser-worker-artifacts/`
- Any failure artifacts written by the worker
- Operator notes about visible page state, timing, and outcome differences
