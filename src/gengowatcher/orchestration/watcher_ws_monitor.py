"""WebSocket monitor thread extracted from GengoWatcher.

Owns the persistent-WebSocket lifecycle loop: credential validation,
session-sync from the live browser when configured, exponential
backoff on reconnect, and orderly shutdown coordination. The watcher
keeps a thin delegator on the class so existing call sites and tests
continue to resolve ``watcher._run_websocket_monitor``.
"""

from __future__ import annotations

import asyncio
import random
import time


def run_websocket_monitor(watcher) -> None:
    """Manage the persistent WebSocket connection lifecycle.

    On each loop iteration:
    - Verifies required WebSocket credentials are configured; if
      missing, marks the WebSocket as disabled and waits for shutdown.
    - Runs the asynchronous connection logic and records the last
      close code and reason.
    - Distinguishes clean closes (codes 1000/1001) from abnormal
      closes and applies exponential backoff (bounded by the
      configured Network.max_backoff) before reconnecting.
    - Observes shutdown_event to exit promptly and updates
      websocket_status to reflect current state.
    """
    watcher.logger.debug("Starting WebSocket monitor thread.")
    # Exponential backoff on reconnect to avoid hammering server
    base_backoff = 5
    backoff = base_backoff
    max_backoff = int(watcher.config.get("Network", "max_backoff"))
    clean_close_backoff_min = watcher.config.getint(
        "Network", "clean_close_backoff_min", fallback=20
    )
    clean_close_backoff_max = watcher.config.getint(
        "Network", "clean_close_backoff_max", fallback=45
    )
    reconnect_jitter_max = watcher.config.getint(
        "Network", "reconnect_jitter_max", fallback=5
    )
    session_placeholder = "REPLACE_WITH_YOUR_SESSION_TOKEN"
    key_placeholder = "REPLACE_WITH_YOUR_USER_KEY"
    while not watcher.shutdown_event.is_set():
        watcher._websocket_session_refresh_requested = False
        watcher._websocket_sync_failed = False
        watcher._websocket_sync_failure_reason = None

        debug_url = watcher.config.get("WebSocket", "browser_debug_url")
        if debug_url:
            watcher._sync_session_from_browser(
                fail_hard=watcher.config.getboolean(
                    "WebSocket", "session_sync_fail_hard", fallback=True
                ),
                alert_on_failure=watcher.config.getboolean(
                    "WebSocket",
                    "session_sync_alert_on_failure",
                    fallback=True,
                ),
            )
            if watcher.shutdown_event.is_set():
                break

        session_token = str(
            watcher.config.get("WebSocket", "user_session", fallback="") or ""
        ).strip()
        user_key = str(
            watcher.config.get("WebSocket", "user_key", fallback="") or ""
        ).strip()
        user_id_value = watcher.config.get("WebSocket", "user_id", fallback=None)
        if not session_token or session_token == session_placeholder:
            watcher.logger.warning(
                "WebSocket session token missing; WebSocket disabled."
            )
            watcher.websocket_status = "Disabled"
            watcher.shutdown_event.wait(timeout=5)
            continue
        if not user_id_value:
            watcher.logger.warning("WebSocket user_id missing; WebSocket disabled.")
            watcher.websocket_status = "Disabled"
            watcher.shutdown_event.wait(timeout=5)
            continue
        if not user_key or user_key == key_placeholder:
            watcher.logger.warning(
                "WebSocket user key missing. Authentication will rely only on session token."
            )
            watcher.logger.info("Authentication will rely only on session token.")

        try:
            watcher.logger.debug("Running websocket logic (asyncio.run)")
            watcher.websocket_last_close_code = None
            watcher.websocket_last_close_reason = None
            session_started_at = time.time()
            asyncio.run(watcher._websocket_logic())
            session_duration = time.time() - session_started_at
            if watcher.shutdown_event.is_set():
                break
            if watcher.websocket_status != "Disabled":
                watcher.websocket_reconnect_count += 1
            if watcher._websocket_sync_failed:
                watcher.logger.error(
                    "WebSocket monitor stopped after browser session sync failure: %s",
                    watcher._websocket_sync_failure_reason,
                )
                watcher.websocket_status = "Session Sync Failed"
                break
            if watcher._websocket_session_refresh_requested:
                watcher.logger.info(
                    "WebSocket: Reconnecting immediately after browser session refresh."
                )
                backoff = base_backoff
                continue
            watcher.websocket_status = "Offline"
            close_code = watcher.websocket_last_close_code
            close_reason = watcher.websocket_last_close_reason
            normal_close = close_code in (1000, 1001)
            if normal_close:
                wait_time = min(
                    max_backoff,
                    random.uniform(clean_close_backoff_min, clean_close_backoff_max),
                )
                if session_duration < 10:
                    wait_time = max(wait_time, clean_close_backoff_max)
                    watcher.logger.warning(
                        "WebSocket connection closed cleanly after %.1fs. "
                        "Backing off to %.1fs before reconnecting.",
                        session_duration,
                        wait_time,
                    )
                else:
                    watcher.logger.info(
                        "WebSocket connection closed cleanly (code=%s, reason=%s). "
                        "Reconnecting in %.1f seconds...",
                        close_code,
                        close_reason,
                        wait_time,
                    )
            else:
                wait_time = min(backoff, max_backoff)
                if reconnect_jitter_max > 0:
                    wait_time = max(
                        1,
                        wait_time
                        + random.uniform(-reconnect_jitter_max, reconnect_jitter_max),
                    )
                watcher.logger.warning(
                    "WebSocket closed abnormally (code=%s, reason=%s). "
                    "Reconnecting in %.1f seconds...",
                    close_code,
                    close_reason,
                    wait_time,
                )
                backoff = min(backoff * 2, max_backoff)
        except Exception as e:
            wait_time = min(backoff, max_backoff)
            if reconnect_jitter_max > 0:
                wait_time = max(
                    1,
                    wait_time
                    + random.uniform(-reconnect_jitter_max, reconnect_jitter_max),
                )
            watcher.logger.exception(
                "WebSocket connection failed: %s. Reconnecting in %.1fs",
                e,
                wait_time,
            )
            backoff = min(backoff * 2, max_backoff)
            if watcher.websocket_status != "Disabled":
                watcher.websocket_reconnect_count += 1

        if not watcher.shutdown_event.wait(timeout=wait_time):
            continue
        break

    watcher.logger.info("WebSocket monitor thread stopped.")


__all__ = ["run_websocket_monitor"]
