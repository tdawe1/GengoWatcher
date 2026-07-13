"""Monitor status + per-thread metrics helpers extracted from GengoWatcher.

Owns three GengoWatcher-side helpers used by the dashboard and
the WebSocket ``/monitor_status`` endpoint:

* get_monitor_status(watcher) -> dict
  Walks the ``watcher._monitor_threads`` registry and reports
  ``alive | dead | disabled`` plus ``email_detail``,
  ``website_detail``, ``browser_jobs_detail``.
* sync_monitor_metrics(watcher)
  Pulls the latest status / last_check_time / jobs_found_session
  values from the email and website monitor instances onto the
  watcher for dashboard display.
* process_browser_jobs_snapshot(watcher, snapshot) -> int
  Counts how many newly-detected browser-jobs were dispatched
  through ``watcher._process_new_job`` for the given snapshot.

The watcher keeps thin delegator methods on the class so the
existing call sites (web.py monitor endpoint, dashboard rendering
hooks, the test suite) continue to resolve through the instance.
"""

from __future__ import annotations


def get_monitor_status(watcher) -> dict:
    """
    Check health of all monitor threads.

    Returns:
        dict: Mapping of monitor name to status ("alive", "dead", "disabled")
    """
    status = {}
    for name in [
        "rss",
        "websocket",
        "email",
        "website",
        "browser_worker",
        "native_browser",
        "browser_jobs",
    ]:
        thread = watcher._monitor_threads.get(name)
        if thread is None:
            status[name] = "disabled"
        elif thread.is_alive():
            status[name] = "alive"
        else:
            status[name] = "dead"
    status["email_detail"] = watcher.email_monitor_status
    status["website_detail"] = watcher.website_monitor_status
    status["browser_jobs_detail"] = watcher.browser_jobs_monitor_status
    return status


def sync_monitor_metrics(watcher):
    """Sync metrics from email and website monitors."""
    if hasattr(watcher, "_email_monitor") and watcher._email_monitor:
        watcher.email_monitor_status = getattr(
            watcher._email_monitor, "status", "Disabled"
        )
        watcher.email_last_check_time = getattr(
            watcher._email_monitor, "last_check_time", None
        )
        watcher.email_jobs_found_session = getattr(
            watcher._email_monitor, "jobs_found_session", 0
        )
    else:
        watcher.email_monitor_status = "Disabled"
        watcher.email_last_check_time = None
        watcher.email_jobs_found_session = 0

    if hasattr(watcher, "_website_monitor") and watcher._website_monitor:
        watcher.website_monitor_status = getattr(
            watcher._website_monitor, "status", "Disabled"
        )
        watcher.website_last_check_time = getattr(
            watcher._website_monitor, "last_check_time", None
        )
        watcher.website_jobs_found_session = getattr(
            watcher._website_monitor, "jobs_found_session", 0
        )
    else:
        watcher.website_monitor_status = "Disabled"
        watcher.website_last_check_time = None
        watcher.website_jobs_found_session = 0


def process_browser_jobs_snapshot(watcher, snapshot) -> int:
    processed = 0
    candidates = list(snapshot.detected_jobs) + list(snapshot.jobs)
    seen_candidate_ids: set[int] = set()
    for job in candidates:
        if job.job_id in seen_candidate_ids:
            continue
        seen_candidate_ids.add(job.job_id)
        watcher._process_new_job(
            job.job_id,
            job.title,
            job.reward,
            job.url,
            source="BrowserJobs",
            source_meta={
                "title": job.title,
                "reward": job.reward,
                "url": job.url,
                "text": job.text,
                "browser_action": snapshot.action,
                "browser_page_url": snapshot.url,
            },
        )
        processed += 1
    return processed


__all__ = [
    "get_monitor_status",
    "process_browser_jobs_snapshot",
    "sync_monitor_metrics",
]
