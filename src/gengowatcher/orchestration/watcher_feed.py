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
    if not getattr(watcher, "_csv_writer", None):
        return
    timestamp = datetime.datetime.now().isoformat()
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
    flush = getattr(watcher, "_all_entries_log_file", None)
    if flush is not None:
        flush.flush()


def process_feed_entries(watcher, entries):
    """Process RSS feed entries to identify new jobs.

    Filters entries to find only new ones since the last check, extracts job
    information, and processes each new job. Updates the last seen RSS link
    to avoid duplicate processing.

    Args:
        entries: List of RSS entry dictionaries from the feed parser.
    """
    watcher.logger.debug(f"Processing {len(entries) if entries else 0} RSS entries.")
    if not entries:
        return
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
    if not new_entries:
        return
    latest_link = new_entries[0].get("link")
    watcher.state.last_seen_rss_link = latest_link
    watcher.state.last_seen_link = latest_link
    for entry in reversed(new_entries):
        title = entry.get("title", "No Title")
        url = entry.get("link")
        watcher.logger.debug(f"Processing new RSS entry: {title} {url}")
        try:
            match = _JOB_DETAILS_ID_PATTERN.search(url)
            if not match:
                watcher.logger.warning(f"Could not parse job ID from RSS link: {url}")
                continue
            job_id = int(match.group(1))
            reward = watcher._extract_reward(entry)
            watcher._process_new_job(
                job_id,
                title,
                reward,
                url,
                source="RSS",
                source_meta=entry,
            )
        except (ValueError, IndexError) as e:
            watcher.logger.warning(f"Error processing RSS entry {url}: {e}")

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
