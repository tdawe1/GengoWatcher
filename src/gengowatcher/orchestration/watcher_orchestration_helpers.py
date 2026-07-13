"""Orchestration helpers extracted from GengoWatcher.

Owns five GengoWatcher-side helpers used by the websocket lifecycle,
the cancellation manager, and the interactive configuration UI:

* sync_browser_session_for_quiet_socket(watcher, *, current_time=None,
  fail_hard=False, alert_on_failure=False) -> bool
  Re-runs sync_session_from_browser after the websocket has been
  quiet for longer than WebSocket.session_quiet_probe_seconds.
* warn_if_browser_session_mismatch(watcher)
  Logs a startup warning when the configured user_session /
  user_id / user_key / browser_user_agent differ from the live
  browser's reported values.
* get_default_required_config_fields(watcher) -> list[tuple[str,str]]
  Returns the required (section, option) fields for the
  currently-enabled features (websocket, email-monitor,
  website-monitor, auto-accept, browser-worker).
* get_effective_rss_wait_range_seconds(watcher)
  -> tuple[float, float]
  Computes the watcher's RSS retry range. When
  ``Watcher.use_adaptive_rss_wait`` is enabled it returns the
  adaptive range; otherwise it returns the static
  config-driven range.
* configure_cancellation_manager(watcher)
  Pulls the Cancellation.{enabled, min_improvement_ratio,
  extreme_threshold} config values and pushes them into the
  watcher.cancellation_manager.

The watcher keeps thin delegator methods on the class so existing
call sites (watcher_ws_logic.py:191, watcher_config_io.py:27/71/157,
watcher.run(), watcher.__init__ at lines 298/303, the test suite)
continue to resolve through the instance.
"""

from __future__ import annotations

import time

from ..browser_session import fetch_browser_session_snapshot_sync

from .watcher_config_values import PLACEHOLDER_CONFIG_VALUES


def sync_browser_session_for_quiet_socket(
    watcher,
    *,
    current_time: float | None = None,
    fail_hard: bool = False,
    alert_on_failure: bool = False,
) -> bool:
    """Refresh the browser session when a quiet websocket needs a recheck."""
    debug_url = watcher.config.get("WebSocket", "browser_debug_url")
    if not debug_url or watcher.websocket_status != "Live":
        return False

    now = current_time if current_time is not None else time.time()
    quiet_age = watcher._get_websocket_quiet_age(now)
    quiet_probe_after = watcher._get_session_quiet_probe_seconds()
    if quiet_age is None or quiet_age < quiet_probe_after:
        return False

    next_sync_ts = watcher._next_quiet_socket_sync_ts
    if next_sync_ts is not None and now < next_sync_ts:
        return False
    if watcher._browser_session_last_sync_ts is not None:
        sync_age = max(0.0, now - watcher._browser_session_last_sync_ts)
        if sync_age < quiet_probe_after:
            return False

    watcher.logger.warning(
        "WebSocket: No application messages for %.1fs while live; syncing browser"
        " session from %s before continuing.",
        quiet_age,
        debug_url,
    )

    changed = watcher._sync_session_from_browser(
        fail_hard=fail_hard,
        alert_on_failure=alert_on_failure,
    )
    if changed:
        watcher._next_quiet_socket_sync_ts = None
        return True

    watcher._next_quiet_socket_sync_ts = (
        now + watcher._pick_quiet_socket_sync_delay_seconds()
    )
    return False


def warn_if_browser_session_mismatch(watcher) -> None:
    debug_url = watcher.config.get("WebSocket", "browser_debug_url")
    configured_token = watcher.config.get("WebSocket", "user_session")

    if not debug_url or configured_token in PLACEHOLDER_CONFIG_VALUES:
        return

    try:
        snapshot = fetch_browser_session_snapshot_sync(str(debug_url))
    except Exception as exc:
        watcher.logger.debug(
            "Browser session check skipped for %s: %s",
            debug_url,
            exc,
        )
        return

    browser_token = snapshot.session_token
    if browser_token == configured_token:
        return

    watcher.logger.warning(
        "WebSocket.user_session differs from the live browser session at %s "
        "(config=%s browser=%s). Realtime detections may fall back to RSS until"
        " you sync the token.",
        debug_url,
        watcher._mask_secret(configured_token),
        watcher._mask_secret(browser_token),
    )


def get_default_required_config_fields(watcher) -> list[tuple[str, str]]:
    """Return the required config fields for currently enabled features."""
    required_fields = [("Watcher", "feed_url"), ("Watcher", "check_interval")]

    if watcher.config.getboolean("WebSocket", "enable_websocket", fallback=True):
        required_fields.extend(
            [("WebSocket", "user_id"), ("WebSocket", "user_session")]
        )

    if watcher.config.getboolean("EmailMonitor", "enabled", fallback=False):
        required_fields.extend(
            [
                ("EmailMonitor", "email"),
                ("EmailMonitor", "client_id"),
                ("EmailMonitor", "client_secret"),
                ("EmailMonitor", "refresh_token"),
            ]
        )

    if watcher.config.getboolean("WebsiteMonitor", "enabled", fallback=False):
        required_fields.append(("WebsiteMonitor", "jobs_url"))

    if watcher.config.getboolean("AutoAccept", "enabled", fallback=False):
        required_fields.append(("AutoAccept", "browser_profile_path"))

    if watcher.config.getboolean("BrowserWorker", "enabled", fallback=False):
        required_fields.append(("BrowserWorker", "socket_path"))

    return required_fields


def get_effective_rss_wait_range_seconds(watcher) -> tuple[float, float]:
    if watcher._is_gengo_rss_feed():
        min_delay = float(
            watcher.config.get("Watcher", "gengo_rss_interval_min_sec", fallback=31)
            or 31
        )
        max_delay = float(
            watcher.config.get("Watcher", "gengo_rss_interval_max_sec", fallback=60)
            or 60
        )
        if max_delay < min_delay:
            min_delay, max_delay = max_delay, min_delay
        return min_delay, max_delay

    check_interval = float(watcher.config.get("Watcher", "check_interval") or 45)
    return check_interval, check_interval


def configure_cancellation_manager(watcher):
    """Apply configuration settings to the cancellation manager."""
    try:
        settings = {
            "cancellation_enabled": watcher.cancellation_manager._config_getboolean(
                "Cancellation", "enabled", fallback=False
            ),
            "min_improvement_ratio": watcher.cancellation_manager._config_getfloat(
                "Cancellation", "min_improvement_ratio", fallback=2.0
            ),
            "extreme_threshold": watcher.cancellation_manager._config_getfloat(
                "Cancellation", "extreme_threshold", fallback=1000.0
            ),
        }
        watcher.cancellation_manager.update_settings(**settings)
    except Exception as e:
        watcher.logger.error(f"Failed to configure cancellation manager: {e}")


__all__ = [
    "configure_cancellation_manager",
    "get_default_required_config_fields",
    "get_effective_rss_wait_range_seconds",
    "sync_browser_session_for_quiet_socket",
    "warn_if_browser_session_mismatch",
]
