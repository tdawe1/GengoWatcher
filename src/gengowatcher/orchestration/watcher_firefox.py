"""Firefox debug-session helpers extracted from GengoWatcher.

These exist to keep the god class from absorbing every browser-handling
detail. Each helper takes the watcher as its first argument and reads
the bits it needs (config, logger, Firefox debug launchers) from it
without back-references through ``self``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ..browser_debug_launcher import (
    get_firefox_debug_launch_spec,
    get_firefox_debug_retry_window,
    maybe_launch_managed_firefox_debug,
)
from ..browser_session import open_url_in_browser_debug_sync

if TYPE_CHECKING:
    from ..watcher import GengoWatcher


def open_in_managed_firefox_debug_session(
    watcher: "GengoWatcher",
    url: str,
) -> bool:
    """Open ``url`` in the managed Firefox debug session if available.

    Returns ``True`` when the URL was opened successfully. Returns ``False``
    when the URL is not a Gengo URL, when no debug spec can be resolved, or
    when the session cannot be brought up within the configured retry window.

    This function is the ``GengoWatcher._open_in_managed_firefox_debug_session``
    helper moved out of the god class. Behavior is preserved verbatim.
    """
    if not watcher._is_gengo_url(url):
        return False

    debug_url = watcher.config.get("WebSocket", "browser_debug_url") or ""
    try:
        spec = get_firefox_debug_launch_spec(watcher.config, str(debug_url))
    except Exception as exc:
        watcher.logger.debug(
            "Skipping managed Firefox debug browser for %s: %s",
            url,
            exc,
        )
        return False
    if spec is None:
        return False

    last_exc: Exception | None = None
    try:
        open_url_in_browser_debug_sync(spec.debug_url, url)
        watcher.logger.debug(
            "Opened URL in managed Firefox debug session at %s: %s",
            spec.debug_url,
            url,
        )
        return True
    except Exception as exc:
        last_exc = exc

    if maybe_launch_managed_firefox_debug(
        watcher.config,
        spec.debug_url,
        logger=watcher.logger,
    ):
        timeout_sec, retry_interval_sec = get_firefox_debug_retry_window(
            watcher.config
        )
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            time.sleep(retry_interval_sec)
            try:
                open_url_in_browser_debug_sync(spec.debug_url, url)
                watcher.logger.debug(
                    "Opened URL in newly launched managed Firefox debug "
                    "session at %s: %s",
                    spec.debug_url,
                    url,
                )
                return True
            except Exception as exc:
                last_exc = exc

    watcher.logger.warning(
        "Managed Firefox debug session at %s could not open %s (%s); "
        "falling back to configured browser",
        spec.debug_url,
        url,
        last_exc,
    )
    return False


__all__ = ["open_in_managed_firefox_debug_session"]
