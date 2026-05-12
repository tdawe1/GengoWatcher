from __future__ import annotations

import time
from typing import Any


def get_websocket_quiet_age(watcher: Any, current_time: float) -> float | None:
    if watcher.websocket_connected_at_ts is None:
        return None
    last_activity_ts = (
        watcher.websocket_last_message_ts or watcher.websocket_connected_at_ts
    )
    return max(0.0, current_time - last_activity_ts)


def timestamp_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if hasattr(value, "timestamp"):
        try:
            return float(value.timestamp())
        except Exception:
            return None
    return None


def has_error_message(status: object) -> bool:
    return bool(status and "error" in str(status).lower())


def build_health_snapshot(
    watcher: Any, now: float | None = None
) -> dict[str, dict[str, object]]:
    """Return actionable subsystem health instead of coarse absolute state."""
    current_time = now if now is not None else time.time()
    check_interval = float(watcher.config.get("Watcher", "check_interval") or 45)
    browser_debug_url = watcher.config.get("WebSocket", "browser_debug_url") or ""
    ws_enabled = watcher.config.getboolean(
        "WebSocket", "enable_websocket", fallback=True
    )
    email_enabled = watcher.config.getboolean("EmailMonitor", "enabled", fallback=False)
    website_enabled = watcher.config.getboolean(
        "WebsiteMonitor", "enabled", fallback=False
    )
    auto_enabled = watcher.config.getboolean("AutoAccept", "enabled", fallback=False)
    browser_worker_enabled = watcher.config.getboolean(
        "BrowserWorker", "enabled", fallback=False
    )
    cancellation_enabled = watcher.config.getboolean(
        "Cancellation", "enabled", fallback=False
    )
    sync_interval = watcher._get_session_sync_interval_seconds()

    ws_state = "disabled"
    ws_detail = "off"
    last_pong_age = None
    last_message_age = None
    quiet_age = get_websocket_quiet_age(watcher, current_time)
    if watcher.websocket_last_pong_ts is not None:
        last_pong_age = max(0.0, current_time - watcher.websocket_last_pong_ts)
    if watcher.websocket_last_message_ts is not None:
        last_message_age = max(0.0, current_time - watcher.websocket_last_message_ts)

    if ws_enabled:
        if (
            watcher._websocket_sync_failed
            or watcher.websocket_status == "Session Sync Failed"
        ):
            ws_state = "error"
            ws_detail = "sync failed"
        elif watcher.websocket_status == "Disabled":
            ws_state = "disabled"
            ws_detail = "off"
        elif watcher.websocket_status in ("Connecting", "Authenticating", "Enabled"):
            ws_state = "working"
            ws_detail = watcher.websocket_status.lower()
        elif watcher.websocket_status == "Live":
            if last_pong_age is None:
                ws_state = "stale"
                ws_detail = "no pong"
            elif last_pong_age <= 40:
                ws_state = "healthy"
                ws_detail = "ok"
            else:
                ws_state = "stale"
                ws_detail = f"pong {int(last_pong_age)}s"
        elif watcher.websocket_status in ("Offline", "Stopped"):
            ws_state = "error"
            ws_detail = watcher.websocket_status.lower()
        else:
            ws_state = "stale"
            ws_detail = str(watcher.websocket_status or "unknown").lower()

    rss_state = "working"
    rss_detail = str(watcher.rss_action or "init").lower()
    last_check_ts = timestamp_or_none(watcher.last_check_time)
    rss_age = None if last_check_ts is None else max(0.0, current_time - last_check_ts)
    if has_error_message(watcher.rss_action):
        rss_state = "error"
    elif any(
        token in str(watcher.rss_action)
        for token in (
            "Fetching",
            "Processing",
            "Priming",
            "Backoff",
            "Initializing",
        )
    ):
        rss_state = "working"
    elif last_check_ts is None:
        rss_state = "stale"
        rss_detail = "never checked"
    elif rss_age <= max(check_interval * 2, 90):
        rss_state = "healthy"
        rss_detail = "ok"
    else:
        rss_state = "stale"
        rss_detail = f"last {int(rss_age)}s"

    auto_profile = watcher.config.get("AutoAccept", "browser_profile_path") or ""
    if not auto_enabled:
        auto_state = "disabled"
        auto_detail = "off"
    elif not auto_profile:
        auto_state = "error"
        auto_detail = "misconfig"
    elif getattr(watcher, "is_processing", False):
        auto_state = "working"
        auto_detail = "running"
    else:
        auto_state = "healthy"
        auto_detail = "ready"

    if getattr(watcher, "is_processing", False):
        workflow_state = "working"
        workflow_detail = "running"
    elif not any((auto_enabled, browser_worker_enabled, cancellation_enabled)):
        workflow_state = "disabled"
        workflow_detail = "manual"
    elif watcher._websocket_sync_failed:
        workflow_state = "error"
        workflow_detail = "blocked"
    else:
        workflow_state = "healthy"
        workflow_detail = "idle"

    email_last_check_ts = timestamp_or_none(watcher.email_last_check_time)
    email_age = (
        None
        if email_last_check_ts is None
        else max(0.0, current_time - email_last_check_ts)
    )
    email_status = str(watcher.email_monitor_status or "Disabled")
    if not email_enabled:
        email_state = "disabled"
        email_detail = "off"
    elif has_error_message(email_status):
        email_state = "error"
        email_detail = email_status.lower()
    elif email_status in ("Checking",):
        email_state = "working"
        email_detail = email_status.lower()
    elif email_last_check_ts is None:
        email_state = "stale"
        email_detail = "never checked"
    elif email_age <= max(check_interval * 2, 90):
        email_state = "healthy"
        email_detail = email_status.lower()
    else:
        email_state = "stale"
        email_detail = f"last {int(email_age)}s"

    browser_last_check_ts = timestamp_or_none(watcher.website_last_check_time)
    browser_age = (
        None
        if browser_last_check_ts is None
        else max(0.0, current_time - browser_last_check_ts)
    )
    browser_status = str(watcher.website_monitor_status or "Disabled")
    if browser_worker_enabled:
        if watcher.browser_worker_client is None:
            browser_state = "error"
            browser_detail = "worker cfg!"
        else:
            browser_state = "healthy"
            browser_detail = "worker ready"
    elif not website_enabled:
        browser_state = "disabled"
        browser_detail = "off"
    elif has_error_message(browser_status):
        browser_state = "error"
        browser_detail = browser_status.lower()
    elif browser_status in ("Checking",):
        browser_state = "working"
        browser_detail = browser_status.lower()
    elif browser_last_check_ts is None:
        browser_state = "stale"
        browser_detail = "never checked"
    elif browser_age <= max(check_interval * 2, 90):
        browser_state = "healthy"
        browser_detail = browser_status.lower()
    else:
        browser_state = "stale"
        browser_detail = f"last {int(browser_age)}s"

    session_state = "disabled"
    session_detail = "off"
    session_age = None
    if browser_debug_url:
        if watcher._browser_session_last_sync_ts is not None:
            session_age = max(0.0, current_time - watcher._browser_session_last_sync_ts)
        if (
            watcher._websocket_sync_failed
            or watcher._browser_session_last_sync_state == "error"
        ):
            session_state = "error"
            session_detail = watcher._browser_session_last_sync_detail or "sync failed"
        elif watcher._browser_session_last_sync_ts is None:
            session_state = "stale"
            session_detail = "never synced"
        elif session_age is not None and session_age > max(sync_interval * 1.25, 60):
            session_state = "stale"
            session_detail = f"last {int(session_age)}s"
        else:
            session_state = "healthy"
            session_detail = watcher._browser_session_last_sync_detail or "ok"

    return {
        "websocket": {
            "state": ws_state,
            "detail": ws_detail,
            "status": watcher.websocket_status,
            "last_pong_age_sec": last_pong_age,
            "last_message_age_sec": last_message_age,
            "quiet_age_sec": quiet_age,
            "ping_latency_ms": watcher.websocket_ping_latency_ms,
            "reconnect_count": watcher.websocket_reconnect_count,
            "last_close_code": watcher.websocket_last_close_code,
            "last_close_reason": watcher.websocket_last_close_reason,
        },
        "rss": {
            "state": rss_state,
            "detail": rss_detail,
            "status": watcher.rss_action,
            "last_success_age_sec": rss_age,
            "failure_count": watcher.failure_count,
            "next_check_in_sec": max(0.0, watcher.next_check_time - current_time),
        },
        "auto": {
            "state": auto_state,
            "detail": auto_detail,
            "enabled": auto_enabled,
        },
        "workflow": {
            "state": workflow_state,
            "detail": workflow_detail,
            "processing": bool(getattr(watcher, "is_processing", False)),
        },
        "email": {
            "state": email_state,
            "detail": email_detail,
            "status": email_status,
            "last_check_age_sec": email_age,
            "jobs_found_session": watcher.email_jobs_found_session,
        },
        "browser": {
            "state": browser_state,
            "detail": browser_detail,
            "status": browser_status,
            "last_check_age_sec": browser_age,
            "jobs_found_session": watcher.website_jobs_found_session,
        },
        "session": {
            "state": session_state,
            "detail": session_detail,
            "last_sync_age_sec": session_age,
            "debug_url": browser_debug_url,
            "sync_interval_sec": sync_interval,
            "last_sync_state": watcher._browser_session_last_sync_state,
        },
    }


def alert_on_health_snapshot(
    watcher: Any, snapshot: dict[str, dict[str, object]]
) -> None:
    """Send one-shot alerts when subsystem health enters a critical state."""
    for key in ("websocket", "rss", "session", "workflow", "email", "browser"):
        entry = snapshot.get(key, {}) if isinstance(snapshot, dict) else {}
        if not isinstance(entry, dict):
            continue
        state = str(entry.get("state") or "")
        detail = str(entry.get("detail") or "")
        previous = watcher._health_alert_states.get(key)
        watcher._health_alert_states[key] = state
        if state not in {"stale", "error"} or previous == state:
            continue
        sound_file = None
        play_sound = True
        if key == "websocket" and state == "stale":
            sound_file = (
                watcher.config.get(
                    "Paths",
                    "websocket_stale_sound_file",
                    fallback="",
                )
                or None
            )
            if detail.startswith("quiet "):
                play_sound = False
        watcher.show_notification(
            message=f"{key.title()} is {state}: {detail}",
            title="GengoWatcher Telemetry Alert",
            play_sound=play_sound,
            sound_file=sound_file,
        )
