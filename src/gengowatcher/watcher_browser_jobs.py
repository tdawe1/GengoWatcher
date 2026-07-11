"""BrowserJobs monitor threads and helpers extracted from GengoWatcher.

This module owns the event-driven monitor thread that wakes on a refresh
event, performs a passive keepalive when the idle cap elapses, and
delegates the actual scrape to ``inspect_available_jobs_page_sync``.

The helpers here read ``self.<state>`` and ``self.<config>`` through the
passed-in ``watcher`` reference, identical to the pattern used by
``watcher_firefox.py``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .browser_session import inspect_available_jobs_page_sync
from .browser_session_core import GENGO_AVAILABLE_JOBS_URL

if TYPE_CHECKING:
    from .watcher import GengoWatcher


def run_browser_jobs_monitor(watcher: "GengoWatcher") -> None:
    """Event-driven BrowserJobs monitor thread.

    Wakes when ``watcher._browser_jobs_refresh_event`` is set (workbench-
    visible event, WS-discovered job, or an explicit refresh hook) or when
    the idle cap elapses (default 30 minutes), at which point a passive
    keepalive scrape is performed to validate the page is still
    responsive.
    """
    watcher.logger.info(
        "Browser available-jobs monitor thread started (event-driven, idle by default)."
    )
    debug_url = str(
        watcher.config.get("WebSocket", "browser_debug_url", fallback="")
    )
    if not debug_url:
        watcher.browser_jobs_monitor_status = "Disabled"
        return

    allow_navigation = watcher._browser_jobs_navigation_enabled()
    if allow_navigation:
        watcher._open_in_managed_firefox_debug_session(GENGO_AVAILABLE_JOBS_URL)
    watcher.browser_jobs_monitor_status = "Idle (event-driven)"
    idle_cap_seconds = watcher._get_browser_jobs_idle_cap_seconds()
    while not watcher.shutdown_event.is_set():
        triggered = watcher._browser_jobs_refresh_event.wait(
            timeout=idle_cap_seconds
        )
        if watcher.shutdown_event.is_set():
            break
        if not triggered:
            run_browser_jobs_passive_keepalive(watcher, debug_url)
            continue
        watcher._browser_jobs_refresh_event.clear()
        run_browser_jobs_triggered_refresh(
            watcher, debug_url, allow_navigation
        )

    watcher.browser_jobs_monitor_status = "Stopped"
    watcher.logger.info(
        "Browser available-jobs monitor thread stopped."
    )


def trigger_browser_jobs_refresh(
    watcher: "GengoWatcher", *, reason: str = "manual"
) -> None:
    """Public hook to wake the BrowserJobs monitor from external triggers."""
    trigger = getattr(watcher, "_browser_jobs_refresh_event", None)
    if trigger is None:
        return
    watcher.logger.debug("BrowserJobs refresh triggered (%s)", reason)
    trigger.set()


def run_browser_jobs_triggered_refresh(
    watcher: "GengoWatcher",
    debug_url: str,
    allow_navigation: bool,
) -> None:
    """One-shot refresh triggered by a workbench-visible / discovered event.

    Always runs in passive mode (no random browse navigation). When
    allow_navigation is true and a refresh is due, the page is force-
    refreshed â but the monitor never drives the tab to a different page.
    """
    force_refresh = allow_navigation
    browse_url = None
    _run_browser_jobs_scrape(
        watcher,
        debug_url,
        force_refresh=force_refresh,
        browse_url=browse_url,
        interact=False,
        allow_navigation=allow_navigation,
        is_keepalive=False,
    )


def run_browser_jobs_passive_keepalive(
    watcher: "GengoWatcher", debug_url: str
) -> None:
    """Idle-cap keepalive: lightweight passive eval, no interaction."""
    _run_browser_jobs_scrape(
        watcher,
        debug_url,
        force_refresh=False,
        browse_url=None,
        interact=False,
        allow_navigation=False,
        is_keepalive=True,
    )


def _run_browser_jobs_scrape(
    watcher: "GengoWatcher",
    debug_url: str,
    *,
    force_refresh: bool,
    browse_url: str | None,
    interact: bool,
    allow_navigation: bool,
    is_keepalive: bool,
) -> None:
    """Perform one BrowserJobs scrape, update status, dispatch snapshots."""
    try:
        snapshot = inspect_available_jobs_page_sync(
            debug_url,
            force_refresh=force_refresh,
            browse_url=browse_url,
            interact=interact,
            allow_navigation=allow_navigation,
        )
        watcher.browser_jobs_last_check_time = time.time()
        watcher.browser_jobs_last_action = snapshot.action
        if snapshot.action == "manual_browse":
            watcher.browser_jobs_monitor_status = "Paused: browser in manual use"
        elif is_keepalive:
            watcher.browser_jobs_monitor_status = "Idle (keepalive ok)"
        else:
            watcher.browser_jobs_monitor_status = "Refreshed (triggered)"

        if is_keepalive or snapshot.action == "manual_browse":
            return

        processed = watcher._process_browser_jobs_snapshot(snapshot)
        if processed:
            watcher.browser_jobs_found_session += processed
            watcher.logger.info(
                "Browser available-jobs page reported %d candidate job(s).",
                processed,
            )
    except Exception as exc:
        watcher.browser_jobs_monitor_status = f"Error: {exc}"
        log_method = watcher.logger.warning
        log_method(
            "Browser available-jobs monitor scrape failed: %s",
            exc,
        )


__all__ = [
    "GENGO_AVAILABLE_JOBS_URL",
    "run_browser_jobs_monitor",
    "trigger_browser_jobs_refresh",
    "run_browser_jobs_triggered_refresh",
    "run_browser_jobs_passive_keepalive",
]
