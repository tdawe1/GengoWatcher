"""Sentinel values and key-name patterns used by GengoWatcher's
runtime config checks.

This module exists so other modules (watcher.py,
watcher_config_io.py, ...) can import the same set of placeholder
values and sensitive-keyword markers without re-defining them at
module scope.
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

SENSITIVE_KEYWORDS: Final[FrozenSet[str]] = frozenset(
    {"auth", "cookie", "key", "password", "secret", "session", "token"}
)

__all__ = ["PLACEHOLDER_CONFIG_VALUES", "SENSITIVE_KEYWORDS"]
