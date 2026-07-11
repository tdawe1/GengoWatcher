"""Sentinel values used to detect "not configured yet" entries in
the runtime config. Defined as a set so callers can do
``value in PLACEHOLDER_CONFIG_VALUES`` in O(1).

The set intentionally overlaps with what config.py's
``PLACEHOLDER_CONFIG_VALUES`` (a list) catches at parse-time so a token
written to disk before this module was introduced is still treated as
a placeholder by the runtime checks in watcher.py /
watcher_job_processor.py.
"""

from __future__ import annotations

from typing import Any, Final, FrozenSet

PLACEHOLDER_CONFIG_VALUES: Final[FrozenSet[Any]] = frozenset(
    {
        None,
        "",
        "REPLACE_WITH_YOUR_SESSION_TOKEN",
        "REPLACE_WITH_YOUR_USER_KEY",
        "REPLACE_WITH_YOUR_TRANSLATION_APP_TOKEN",
    }
)

__all__ = ["PLACEHOLDER_CONFIG_VALUES"]
