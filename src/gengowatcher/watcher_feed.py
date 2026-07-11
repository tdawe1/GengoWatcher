"""Feed-utility helpers extracted from GengoWatcher.

Owns the small, pure-ish helpers used by the RSS feed processing
pipeline so the god class doesn't accumulate yet another CSV-writer
and reward-regex concern.

Keeping these pure (or pure-enough) means the public watcher methods
can stay as thin delegates, preserving every call site and mock
target that tests patched against GengoWatcher._<name>.
"""

from __future__ import annotations

import datetime
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .watcher import GengoWatcher


_REWARD_PATTERN = re.compile(
    r"Reward:\s*(?:US\$|\$)?\s*(\d+\.?\d*)",
    re.IGNORECASE,
)


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


__all__ = ["extract_reward", "log_all_entries"]
