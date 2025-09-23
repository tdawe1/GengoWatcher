Made the acceptance core concurrency-aware and laid the groundwork for Selenium/HTTP racing:

- `src/gengowatcher/config.py`: added `AutoAccept.concurrent_submission`, `accept_click_probe_ms`, `attempt_timeout_sec`, and `selenium_attempt_timeout_sec` defaults so the new flow can be tuned without code changes.
- `src/gengowatcher/job_acceptance.py`: introduced `AcceptResult`/`AcceptForm`, replaced the single-path attempt with `_attempt_job_acceptance` that races HTTP form submission against the Selenium path, records timing milestones for JSONL logging, and centralised per-attempt logging in `_log_accept_attempt`. CAPTCHA handling now updates timing fields and shares headers/hidden-field parsing via revamped `_parse_accept_form`/`_extract_meta_tokens`.
- `src/gengowatcher/browser_automation/engine.py`: added `attempt_accept_via_browser` plus helpers (`_await_post_click`, `_capture_screenshot`) so the Python side can request a synchronous Selenium accept attempt, returning timing metadata; `_safe_submit_first_form` now accepts an explicit driver.

What’s still pending:
- Finish the Selenium monitor overhaul (MutationObservers, fast accept watcher, cancellation wiring) and ensure those threads honour the new `_driver_lock`.
- Expand watcher integration (`watcher.py`) to trigger `_race_submit`, propagate cancellation to Selenium threads, and surface the new metrics.
- Extend logging/tests/docs per the prompt (JSONL log validation, race controller tests, README/TUI updates).
- Clean up/run the test suite once the remaining pieces land; I haven’t executed any tests yet.

Next steps I’d tackle: 1) finish the browser automation observers + watcher integration so the race can actually run, 2) wire the JSONL logger into the UI/docs, and 3) add the required unit/integration tests.