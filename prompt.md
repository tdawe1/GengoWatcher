Title: GengoWatcher — Finish Ultra‑Fast Acceptance (Observers, Race, Metrics, Tests)
  Mode: Multi‑agent (A1..A8), autonomous. Work in repo root. Backend at src/gengowatcher/.

  Context

  - We already added:
      - Selenium persistent session + starter monitors, instant “open details + accept watcher,” webdriver‑manager, and improved accept form parsing/
  CSRF.
      - Pieces of the HTTP↔Selenium race with timing scaffolding.
  - We need to harden everything for sub‑second reaction and add tests/docs, without restarting the user’s app automatically.

  Constraints

  - No secrets in logs (never log captcha tokens or cookies).
  - Minimal diffs; keep style (Black/flake8).
  - Don’t auto‑restart the app; produce a clear summary + manual restart note.

  Objectives

  1. Finalize Selenium monitors and accept watcher
      - Replace polling with MutationObserver on both views:
          - Realtime dashboard: observe jobs table; on new links a[href*='/t/jobs/details/'], dedupe and emit (job_id, url).
          - Available jobs list: keep 1.0–1.5s refresh, plus MutationObserver between refreshes to catch DOM updates.
      - Accept watcher (details page): every 50–75ms try accept; success on redirect or “accepted/success” text. Add optional screenshot on failure.
  2. Wire true concurrency (race)
      - In JobAcceptanceEngine, implement _race_submit(job_data): run HTTP form submit and Selenium click concurrently; first success wins; cancel loser
  (and set a cancel_event for the Selenium side).
      - Integrate the race into accept_job path with configurable per‑attempt timeout (e.g., 6–8s) and total deadline (≈12–15s).
  3. Robust form submit
      - Use parsed accept form (action/method/hidden fields) from details page. Broaden CSRF via hidden inputs and meta[name=csrf-token]; add
  X‑CSRF‑Token header if present. Use absolute URL for action.
  4. Logging & metrics
      - Append structured JSONL to logs/accept_attempts.log:
        { ts, job_id, source, attempt, attempts, path: http|selenium, http_status, redirect, result, reason,
        seen_ms, details_ms, token_ms, click_ms, redirect_ms }
      - Redact tokens. This log must never crash acceptance flow.
  5. Watcher integration
      - On eligible job (RSS/WS):
          - Keep opening the user’s browser instantly (current behavior).
          - Immediately arm Selenium accept watcher on job details.
          - Launch _race_submit in background; dedupe per job_id.
      - Ensure clean shutdown respects Selenium threads (no leaked threads).
  6. Tests (unit + mock integration)
      - Unit:
          - Accept form parsing (action/method/hidden/meta CSRF).
          - Race: first‑wins cancels loser; cancel_event is set; loser does not mark success.
          - Accept watcher token detection via HTML fixtures (no real Selenium in unit tests).
      - Mock integration (scripts/mock_gengo_server.py):
          - Details page: with & without captcha.
          - Accept action: 302/303 redirect; 200 success; 200 captcha prompt.
          - Slow/fast variants to force race outcomes.
      - CI: run unit + a small mock subset in headless mode. Store screenshots/logs as artifacts on failure.
  7. Docs/TUI
      - README: dual monitors, concurrency, config toggles, troubleshooting Chrome/driver, reading JSONL metrics.
      - TUI help/status: show Selenium monitor status and last acceptance timing summary.

  Files to modify/add

  - src/gengowatcher/browser_automation/engine.py
      - Add MutationObserver injection JS for both monitors.
      - Implement attempt_accept_via_browser(job_data, probe_ms, timeout, cancel_event, timings, start_monotonic) returning a structured result; add
  optional screenshots on failure.
      - Ensure thread‑safe driver usage (lock); respect cancel_event.
  - src/gengowatcher/job_acceptance.py
      - Implement _race_submit and cancellation logic; keep AcceptResult + AcceptForm.
      - Harden _parse_accept_form, _extract_meta_tokens; ensure action is absolute (urljoin).
      - Log JSONL via _log_accept_attempt; update timing fields.
  - src/gengowatcher/watcher.py
      - On job eligible: call open_job_details_and_arm_accept(url) immediately and start race concurrently. Keep job_id dedupe and clean shutdown.
  - src/gengowatcher/config.py
      - Ensure defaults for:
          - SeleniumMonitoring.enable_live_dashboard=true
          - SeleniumMonitoring.enable_list_refresh=true
          - SeleniumMonitoring.refresh_interval_ms=1500
          - SeleniumMonitoring.headless=false
          - AutoAccept.concurrent_submission=true
          - AutoAccept.accept_click_probe_ms=75
          - AutoAccept.attempt_timeout_sec=8
          - AutoAccept.selenium_attempt_timeout_sec=8
  - tests/
      - Add unit tests for parser/CSRF/race/watcher fixtures; keep them independent of Selenium.
      - Add mock server scenarios and a small headless integration.
  - scripts/mock_gengo_server.py
      - Extend routes for details + accept with the permutations above.
  - README.md, src/gengowatcher/ui.py (help text)
      - Document monitors and metrics; show status/help in TUI.

  Acceptance criteria

  - Mock integration: HTTP faster → HTTP wins; Selenium faster → Selenium wins; loser is canceled; JSONL includes timing fields.
  - Accept watcher clicks ≤150ms after token present in HTML fixture scenario.
  - No secrets in logs; JSONL appended safely even on errors.
  - CI (unit + small mock) passes; docs updated with restart instructions.

  Guardrails

  - Don’t leak tokens or cookies to logs.
  - Respect existing config; only add toggles; keep current CLI UX.
  - Do not restart user’s app automatically; only provide restart instructions in final message.

  Deliverable summary (final message)

  - List changed files with brief rationale.
  - Exact new config keys and defaults.
  - Manual restart command; how to validate (tail logs/accept_attempts.log).
  - Any follow‑ups or caveats.

  Begin now.

  Run it and capture JSONL
  From repo root:

  - ts=$(date +%F_%H-%M-%S); out="codex_run_$ts.jsonl"; last="codex_last_$ts.json"
  - codex exec -m gpt-5-codex --json --output-last-message "$last" PROMPT2.md | tee "$out"

  Live alerts

  - tail -F "$out" | jq -r --unbuffered 'select(.error or (.status?|test("fail|error";"i")) or (.event?|test("exception|worker_failed|
  worker_error";"i"))) | "ALERT: " + ((.error // .status // .event) | tostring)'

  When finished, restart manually to enable changes
