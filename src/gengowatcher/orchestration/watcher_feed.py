"""Feed-utility helpers extracted from GengoWatcher.

Owns the small, pure-ish helpers used by the RSS feed processing
pipeline so the god class doesn't accumulate yet another CSV-writer
and reward-regex concern.

Keeping these pure (or pure-enough) means the public watcher methods
can stay as thin delegates, preserving every call site and mock
target that tests patched against GengoWatcher._<name>.
"""

from __future__ import annotations

import time
import os
import datetime
import re
from contextlib import nullcontext
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..watcher import GengoWatcher


_REWARD_PATTERN = re.compile(
    r"Reward:\s*(?:US\$|\$)?\s*(\d+\.?\d*)",
    re.IGNORECASE,
)
_JOB_DETAILS_ID_PATTERN = re.compile(r"/jobs/details/(\d+)")


def extract_reward(entry) -> float:
    """Extract the USD reward value from a parsed RSS entry.

    Looks for the literal "Reward: $N.NN" / "Reward: US$N.NN" pattern
    inside the title + summary concatenation. Returns 0.0 when no
    match is found or when the match cannot be coerced to a float.
    """
    text = entry.get("title", "") + " | " + entry.get("summary", "")
    match = _REWARD_PATTERN.search(text)
    try:
        return float(match.group(1)) if match else 0.0
    except (ValueError, IndexError):
        return 0.0


def log_all_entries(watcher: "GengoWatcher", entries) -> None:
    """Log every RSS entry to the configured CSV file.

    Writes timestamp, title, reward, link, and summary for each entry
    and flushes the underlying file handle. No-op when the CSV writer
    was not initialized (e.g. in tests that replace the watcher with
    a lightweight stub).
    """
    if not entries:
        return
    csv_lock = getattr(watcher, "_csv_lock", nullcontext())
    with csv_lock:
        log_file = getattr(watcher, "_all_entries_log_file", None)
        if log_file is None or log_file.closed:
            return
        if not getattr(watcher, "_csv_writer", None):
            return
        timestamp = datetime.datetime.now().isoformat()
        try:
            for entry in entries:
                watcher._csv_writer.writerow(
                    [
                        timestamp,
                        entry.get("title", "N/A"),
                        extract_reward(entry),
                        entry.get("link", "N/A"),
                        entry.get("summary", "N/A"),
                    ]
                )
            log_file.flush()
        except (OSError, ValueError) as error:
            watcher.logger.debug(
                "CSV entry logging stopped while the file was closing: %s", error
            )


_RSS_AVAILABLE_STATES = {"", "detected", "observed", "new", "available"}
_RSS_TERMINAL_STATES = {
    "accepted",
    "cancelled",
    "completed",
    "expired",
    "failed",
    "gone",
    "rejected",
    "unavailable",
}


def _rss_job_id_from_link(url) -> str | None:
    if not url:
        return None
    match = _JOB_DETAILS_ID_PATTERN.search(str(url))
    if not match:
        return None
    return match.group(1)


def _job_status_tokens(job: dict) -> set[str]:
    tokens = set()
    for key in ("lifecycle_state", "workflow_state", "acceptance_state"):
        value = str(job.get(key) or "").strip().lower()
        if value:
            tokens.add(value)
    return tokens


def _is_rss_job(job: dict) -> bool:
    return "rss" in str(job.get("source") or "").strip().lower()


def _is_open_rss_job(job: dict) -> bool:
    if job.get("accepted"):
        return False
    tokens = _job_status_tokens(job)
    if tokens & _RSS_TERMINAL_STATES:
        return False
    return not tokens or bool(tokens & _RSS_AVAILABLE_STATES)


def reconcile_rss_available_jobs(watcher, entries) -> int:
    """Mark stored RSS jobs gone when they are absent from the current feed.

    The Gengo RSS document is a snapshot of currently available jobs. History
    stays in state; only the available-job projection is updated.
    """
    get_recent = getattr(watcher.state, "get_recent_jobs", None)
    update_job = getattr(watcher.state, "update_job", None)
    if not callable(get_recent) or not callable(update_job):
        return 0

    stored = get_recent(getattr(watcher.state, "MAX_STORED_JOBS", 5000))
    if not isinstance(stored, list):
        return 0

    live_ids = {
        job_id
        for job_id in (
            _rss_job_id_from_link(entry.get("link")) for entry in (entries or [])
        )
        if job_id
    }
    changed = 0
    for job in stored:
        if not isinstance(job, dict) or not _is_rss_job(job):
            continue
        job_id = str(job.get("id") or "").strip()
        if not job_id:
            continue
        if job_id in live_ids:
            if str(job.get("lifecycle_state") or "").strip().lower() == "gone":
                if update_job(
                    job_id,
                    {
                        "lifecycle_state": "detected",
                        "workflow_state": "new",
                    },
                ):
                    changed += 1
            continue
        if not _is_open_rss_job(job):
            continue
        if update_job(
            job_id,
            {
                "lifecycle_state": "gone",
                "workflow_state": "gone",
            },
        ):
            changed += 1

    if changed:
        watcher.logger.info(
            "Marked %s stored RSS job(s) gone after feed snapshot with %s live listings.",
            changed,
            len(live_ids),
        )
        save_state = getattr(watcher.state, "save_state", None)
        if callable(save_state):
            save_state()
    return changed


def process_feed_entries(watcher, entries):
    """Process RSS feed entries to identify new jobs.

    Filters entries to find only new ones since the last check, extracts job
    information, and processes each new job. Updates the last seen RSS link
    to avoid duplicate processing.

    Args:
        entries: List of RSS entry dictionaries from the feed parser.
    """
    watcher.logger.debug(f"Processing {len(entries) if entries else 0} RSS entries.")
    if entries:
        watcher._log_all_entries(entries)
        new_entries = []
        for entry in entries:
            link = entry.get("link")
            if not link:
                watcher.logger.debug(f"Skipping entry with no link: {entry}")
                continue
            if link == watcher.state.last_seen_rss_link:
                watcher.logger.debug(f"Reached last seen RSS link: {link}")
                break
            new_entries.append(entry)
        watcher.logger.debug(f"Found {len(new_entries)} new RSS entries.")
        if new_entries:
            latest_link = new_entries[0].get("link")
            watcher.state.last_seen_rss_link = latest_link
            watcher.state.last_seen_link = latest_link
            for entry in reversed(new_entries):
                title = entry.get("title", "No Title")
                url = entry.get("link")
                watcher.logger.debug(f"Processing new RSS entry: {title} {url}")
                try:
                    job_id = _rss_job_id_from_link(url)
                    if not job_id:
                        watcher.logger.warning(
                            f"Could not parse job ID from RSS link: {url}"
                        )
                        continue
                    reward = watcher._extract_reward(entry)
                    watcher._process_new_job(
                        int(job_id),
                        title,
                        reward,
                        url,
                        source="RSS",
                        source_meta=entry,
                    )
                except (ValueError, IndexError) as e:
                    watcher.logger.warning(f"Error processing RSS entry {url}: {e}")
    reconcile_rss_available_jobs(watcher, entries)


def run_rss_monitor(watcher):
    watcher.logger.debug("Starting RSS monitor thread.")
    watcher.logger.info("RSS monitor thread started.")
    state_updated = False
    if not watcher.state.last_seen_rss_link:
        if watcher.state.last_seen_link:
            watcher.state.last_seen_rss_link = watcher.state.last_seen_link
            watcher.logger.debug(
                "Migrated legacy last_seen_link value to last_seen_rss_link."
            )
            state_updated = True
        else:
            watcher.rss_action = "Priming feed"
            initial_feed = watcher.fetch_rss()
            if initial_feed and initial_feed.entries:
                first_link = initial_feed.entries[0].get("link")
                watcher.state.last_seen_rss_link = first_link
                watcher.state.last_seen_link = first_link
                watcher.logger.info("Initial RSS feed primed successfully.")
                state_updated = True
    if state_updated:
        watcher.state.save_state()

    while not watcher.shutdown_event.is_set():
        is_paused = os.path.exists(watcher.PAUSE_FILE)
        time_to_next_check = watcher.next_check_time - time.time()
        wait_duration = max(0, time_to_next_check)
        watcher.logger.debug(
            f"Waiting for next RSS check: {wait_duration:.2f}s (paused={is_paused})"
        )

        triggered = watcher.check_now_event.wait(timeout=wait_duration)
        if watcher.shutdown_event.is_set():
            break

        if triggered or time.time() >= watcher.next_check_time:
            watcher.logger.debug("RSS check triggered.")
            watcher.check_now_event.clear()

            if os.path.exists(watcher.PAUSE_FILE):
                watcher.rss_action = "Paused"
                wait_time = 5
            else:
                watcher.rss_action = "Fetching RSS"
                feed = watcher.fetch_rss()
                if feed is None:
                    watcher.failure_count += 1
                    wait_time = min(
                        watcher._pick_next_rss_wait_seconds()
                        * (2**watcher.failure_count),
                        watcher.config.get("Network", "max_backoff"),
                    )
                    watcher.rss_action = f"RSS Backoff ({int(wait_time)}s)"
                else:
                    if watcher.failure_count > 0:
                        watcher.logger.info("RSS Connection re-established.")
                    watcher.failure_count = 0
                    watcher.last_check_time = datetime.datetime.now()
                    watcher.rss_action = "Processing RSS"
                    watcher._process_feed_entries(feed.entries)
                    wait_time = watcher._pick_next_rss_wait_seconds()
                    watcher.rss_action = "Waiting"
            watcher.next_check_time = time.time() + wait_time

    watcher.logger.info("RSS monitor thread stopped.")


__all__ = [
    "extract_reward",
    "log_all_entries",
    "process_feed_entries",
    "run_rss_monitor",
]
