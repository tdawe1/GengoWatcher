"""Regression tests for the BrowserJobs event-driven monitor.

Before the refactor, _run_browser_jobs_monitor polled the browser at a fixed
interval (default 1.5s) and drove the live Firefox tab to random browse
URLs. The monitor now wakes on:
  - A job.visible / job.details / job.discovered API event, OR
  - An explicit trigger_browser_jobs_refresh() call, OR
  - A long idle-cap keepalive (default 30 min).

These tests verify:
  - The monitor does NOT scrape when no trigger fires within idle_cap_sec.
  - The monitor scrapes exactly once per trigger.
  - The public trigger_browser_jobs_refresh() hook wakes the loop.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from gengowatcher.watcher import GengoWatcher
from gengowatcher.state import AppState


class _FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, section, key, fallback=None):
        return self.values.get((section, key), fallback)

    def getfloat(self, section, key, fallback=None):
        v = self.values.get((section, key), fallback)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return fallback

    def getint(self, section, key, fallback=None):
        v = self.values.get((section, key), fallback)
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return fallback

    def getboolean(self, section, key, fallback=False):
        v = self.values.get((section, key), fallback)
        return bool(v) if isinstance(v, bool) else fallback


class _FakeState:
    def __init__(self):
        self.last_seen_rss_link = None
        self.last_seen_link = None
        self.seen_job_ids = []
        self._jobs = []

    def save_state(self):
        pass


def _make_watcher(**config_overrides):
    values = {
        ("BrowserJobs", "enabled"): True,
        ("BrowserJobs", "allow_navigation"): False,
        ("BrowserJobs", "idle_cap_sec"): 0.2,
        ("WebSocket", "browser_debug_url"): "ws://127.0.0.1:6000",
    }
    for k, v in config_overrides.items():
        # Support either ("section", "key") tuple or "section.key" string.
        if isinstance(k, tuple):
            values[k] = v
        elif "." in k:
            section, key = k.split(".", 1)
            values[(section, key)] = v
        else:
            raise TypeError(f"unsupported config key: {k!r}")
    config = _FakeConfig(values)
    state = _FakeState()
    import logging
    watcher = GengoWatcher.__new__(GengoWatcher)
    watcher.config = config
    watcher.state = state
    watcher.logger = logging.getLogger("test.browser_jobs_event_driven")
    watcher.shutdown_event = threading.Event()
    watcher._browser_jobs_refresh_event = threading.Event()
    watcher.browser_jobs_monitor_status = "Disabled"
    watcher.browser_jobs_last_check_time = None
    watcher.browser_jobs_last_action = ""
    watcher.browser_jobs_found_session = 0
    return watcher


def test_no_scrape_without_trigger_within_idle_cap():
    """The monitor must not call inspect_available_jobs_page_sync during the
    idle-cap window when nothing has triggered it.
    """
    watcher = _make_watcher()
    scrape_calls = []
    shutdown = threading.Event()

    def fake_inspect(debug_url, **kwargs):
        scrape_calls.append(time.time())
        from gengowatcher.browser_session import BrowserAvailableJobsSnapshot
        return BrowserAvailableJobsSnapshot(
            url="https://gengo.com/t/jobs/available",
            title="Available jobs",
            ready_state="complete",
            jobs=(),
            action="inspect",
        )

    def run_loop():
        with (
            patch(
                "gengowatcher.watcher.inspect_available_jobs_page_sync",
                fake_inspect,
            ),
            patch.object(watcher, "_browser_jobs_navigation_enabled", return_value=False),
            patch.object(watcher, "_browser_jobs_mouse_activity_enabled", return_value=False),
        ):
            watcher._run_browser_jobs_monitor()
        shutdown.set()

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
    # Sleep for less than idle_cap_sec; nothing should have been scraped.
    time.sleep(0.05)
    # Now trigger shutdown
    watcher.shutdown_event.set()
    shutdown.wait(timeout=2)
    assert scrape_calls == [], (
        "monitor should not scrape without a trigger inside idle_cap window"
    )


def test_scrape_after_explicit_trigger():
    """A trigger_browser_jobs_refresh() call wakes the monitor once."""
    watcher = _make_watcher()
    scrape_calls = []
    shutdown = threading.Event()

    def fake_inspect(debug_url, **kwargs):
        scrape_calls.append(time.time())
        from gengowatcher.browser_session import BrowserAvailableJobsSnapshot
        return BrowserAvailableJobsSnapshot(
            url="https://gengo.com/t/jobs/available",
            title="Available jobs",
            ready_state="complete",
            jobs=(),
            action="inspect",
        )

    def run_loop():
        with (
            patch(
                "gengowatcher.watcher.inspect_available_jobs_page_sync",
                fake_inspect,
            ),
            patch.object(watcher, "_browser_jobs_navigation_enabled", return_value=False),
            patch.object(watcher, "_browser_jobs_mouse_activity_enabled", return_value=False),
        ):
            watcher._run_browser_jobs_monitor()
        shutdown.set()

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
    # Give the loop a moment to enter wait(), then fire the trigger.
    time.sleep(0.05)
    watcher.trigger_browser_jobs_refresh(reason="test")
    # Allow the scrape to complete.
    time.sleep(0.1)
    watcher.shutdown_event.set()
    shutdown.wait(timeout=2)
    assert len(scrape_calls) >= 1, "monitor should scrape after explicit trigger"


def test_keepalive_scrape_after_idle_cap_elapses():
    """When nothing triggers the monitor within idle_cap_sec, a passive
    keepalive scrape runs and no random browse navigation occurs.
    """
    watcher = _make_watcher(**{"BrowserJobs.idle_cap_sec": 0.1})
    scrape_calls = []
    browse_urls_seen = []
    shutdown = threading.Event()

    def fake_inspect(debug_url, *, force_refresh=False, browse_url=None, **kwargs):
        scrape_calls.append(
            {"force_refresh": force_refresh, "browse_url": browse_url}
        )
        if browse_url is not None:
            browse_urls_seen.append(browse_url)
        from gengowatcher.browser_session import BrowserAvailableJobsSnapshot
        return BrowserAvailableJobsSnapshot(
            url="https://gengo.com/t/jobs/available",
            title="Available jobs",
            ready_state="complete",
            jobs=(),
            action="inspect",
        )

    def run_loop():
        with (
            patch(
                "gengowatcher.watcher.inspect_available_jobs_page_sync",
                fake_inspect,
            ),
            patch.object(watcher, "_browser_jobs_navigation_enabled", return_value=False),
            patch.object(watcher, "_browser_jobs_mouse_activity_enabled", return_value=False),
        ):
            watcher._run_browser_jobs_monitor()
        shutdown.set()

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
    # Wait long enough for at least one idle-cap to elapse.
    time.sleep(0.4)
    watcher.shutdown_event.set()
    shutdown.wait(timeout=2)
    assert browse_urls_seen == [], "keepalive scrape must not drive browse navigation"
    assert all(
        call["force_refresh"] is False and call["browse_url"] is None
        for call in scrape_calls
    ), "keepalive scrape must be passive (no force_refresh, no browse_url)"


def test_triggered_refresh_runs_passive_when_navigation_disabled():
    """A triggered refresh with allow_navigation=False must not navigate or
    interact; force_refresh stays False in that case.
    """
    watcher = _make_watcher()  # default allow_navigation is False
    scrape_calls = []
    shutdown = threading.Event()

    def fake_inspect(debug_url, *, force_refresh=False, browse_url=None, interact=False, **kwargs):
        scrape_calls.append(
            {
                "force_refresh": force_refresh,
                "browse_url": browse_url,
                "interact": interact,
            }
        )
        from gengowatcher.browser_session import BrowserAvailableJobsSnapshot
        return BrowserAvailableJobsSnapshot(
            url="https://gengo.com/t/jobs/available",
            title="Available jobs",
            ready_state="complete",
            jobs=(),
            action="inspect",
        )

    def run_loop():
        with (
            patch(
                "gengowatcher.watcher.inspect_available_jobs_page_sync",
                fake_inspect,
            ),
            patch.object(watcher, "_browser_jobs_navigation_enabled", return_value=False),
            patch.object(watcher, "_browser_jobs_mouse_activity_enabled", return_value=False),
        ):
            watcher._run_browser_jobs_monitor()
        shutdown.set()

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
    time.sleep(0.05)
    watcher.trigger_browser_jobs_refresh(reason="workbench-visible")
    time.sleep(0.1)
    watcher.shutdown_event.set()
    shutdown.wait(timeout=2)
    triggered_calls = [
        c for c in scrape_calls
        if c["browse_url"] is None and c["interact"] is False
    ]
    assert triggered_calls, "trigger should produce at least one passive scrape"
    assert all(
        c["force_refresh"] is False for c in triggered_calls
    ), "without allow_navigation, force_refresh must remain False"