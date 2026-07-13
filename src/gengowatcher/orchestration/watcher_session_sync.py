"""Browser session synchronization helpers extracted from GengoWatcher.

Owns the path that pulls a fresh websocket session token (and cookies)
from the live Firefox debug session before each WebSocket connection
attempt. The watcher keeps thin delegator methods on the class so the
existing call sites in watcher_ws_monitor, watcher_ws_logic, and the
test suite keep resolving them through the instance.
"""

from __future__ import annotations

import time

from ..browser_debug_launcher import (
    get_firefox_debug_retry_window,
    maybe_launch_managed_firefox_debug,
)
from ..browser_session import fetch_browser_session_snapshot_sync


def sync_session_from_browser(
    watcher,
    *,
    fail_hard: bool = False,
    alert_on_failure: bool = False,
) -> bool:
    """Refresh the configured websocket session token from a live browser."""
    debug_url = watcher.config.get("WebSocket", "browser_debug_url")
    if not debug_url:
        return False

    snapshot = None
    sync_error: Exception | None = None
    try:
        snapshot = fetch_browser_session_snapshot_sync(str(debug_url))
    except Exception as exc:
        sync_error = exc
        if maybe_launch_managed_firefox_debug(
            watcher.config,
            str(debug_url),
            logger=watcher.logger,
        ):
            timeout_sec, retry_interval_sec = get_firefox_debug_retry_window(
                watcher.config
            )
            deadline = time.monotonic() + timeout_sec
            last_exc: Exception = exc
            while time.monotonic() < deadline:
                time.sleep(retry_interval_sec)
                try:
                    snapshot = fetch_browser_session_snapshot_sync(str(debug_url))
                    break
                except Exception as retry_exc:
                    last_exc = retry_exc
            sync_error = last_exc

    if snapshot is None:
        watcher._browser_session_last_sync_ts = time.time()
        watcher._browser_session_last_sync_state = "error"
        error_detail = str(sync_error or "browser session sync failed")
        watcher._browser_session_last_sync_detail = error_detail
        watcher.logger.warning(
            "Browser session sync failed for %s: %s",
            debug_url,
            error_detail,
        )
        if watcher._has_cached_websocket_credentials():
            watcher.logger.warning(
                "Browser session sync failed for %s, but cached WebSocket"
                " credentials are present. Continuing with the last known"
                " session instead of stopping realtime monitoring.",
                debug_url,
            )
            watcher._websocket_sync_failed = False
            watcher._websocket_sync_failure_reason = None
            return False
        if alert_on_failure:
            sound_file = watcher.config.get(
                "Paths", "browser_session_sync_failed_sound_file"
            )
            watcher.show_notification(
                message=f"Browser session sync failed: {error_detail}",
                title="GengoWatcher Session Sync Failed",
                play_sound=True,
                sound_file=sound_file or None,
            )
        if fail_hard:
            watcher._websocket_sync_failed = True
            watcher._websocket_sync_failure_reason = error_detail
            watcher.websocket_status = "Session Sync Failed"
        return False

    current_token = watcher.config.get("WebSocket", "user_session")
    current_browser_user_agent = watcher.config.get("Network", "browser_user_agent")
    current_accept_language = watcher.config.get("Network", "browser_accept_language")
    browser_token = snapshot.session_token
    browser_user_agent = str(snapshot.user_agent or "").strip()
    browser_accept_language = str(snapshot.accept_language or "").strip()
    watcher._browser_cookies = snapshot.cookies or []
    watcher._browser_session_last_sync_ts = time.time()
    watcher._browser_session_last_sync_state = "healthy"
    changed_fields = []
    if browser_token != current_token:
        watcher.config.set("WebSocket", "user_session", browser_token)
        changed_fields.append("user_session")
    if (
        browser_user_agent
        and browser_user_agent != str(current_browser_user_agent or "").strip()
    ):
        watcher.config.set("Network", "browser_user_agent", browser_user_agent)
        changed_fields.append("browser_user_agent")
    if (
        browser_accept_language
        and browser_accept_language != str(current_accept_language or "").strip()
    ):
        watcher.config.set(
            "Network", "browser_accept_language", browser_accept_language
        )
        changed_fields.append("browser_accept_language")
    if str(debug_url) != str(
        watcher.config.get("WebSocket", "browser_debug_url") or ""
    ):
        watcher.config.set("WebSocket", "browser_debug_url", str(debug_url))
        changed_fields.append("browser_debug_url")

    if changed_fields:
        watcher.config.save_config()
        watcher._browser_session_last_sync_detail = (
            f"updated {', '.join(changed_fields)}"
        )
    else:
        watcher._browser_session_last_sync_detail = "unchanged"
    watcher.logger.info(
        "Updated WebSocket session settings from live browser session at %s "
        "(session=%s)",
        debug_url,
        watcher._mask_secret(browser_token),
    )
    return bool(changed_fields)


def sync_session_before_websocket_connect(watcher) -> bool:
    """Try to sync browser session once before building websocket auth."""
    debug_url = watcher.config.get("WebSocket", "browser_debug_url")
    if not debug_url:
        return True

    sync_fail_hard = watcher.config.getboolean(
        "WebSocket", "session_sync_fail_hard", fallback=True
    )
    sync_alert_on_failure = watcher.config.getboolean(
        "WebSocket",
        "session_sync_alert_on_failure",
        fallback=True,
    )
    watcher.logger.info(
        "WebSocket: Syncing browser session from %s before connecting.",
        debug_url,
    )
    watcher._sync_session_from_browser(
        fail_hard=sync_fail_hard,
        alert_on_failure=sync_alert_on_failure,
    )
    if watcher._websocket_sync_failed:
        watcher.logger.error("WebSocket: Browser session sync failed before connect.")
        return False
    return True


__all__ = [
    "sync_session_before_websocket_connect",
    "sync_session_from_browser",
]
