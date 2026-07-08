__version__ = "2.9.2"
__release_date__ = "2026-07-07"

import asyncio
import concurrent.futures
import csv
import datetime
import json
import logging
import os
import queue
import re
import random
import subprocess
import sys
import threading
import time
import webbrowser
from typing import Any, Callable, Optional
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import websockets
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatusCode

from .browser_session import (
    GENGO_AVAILABLE_JOBS_URL,
    GENGO_BROWSER_BROWSE_URLS,
    build_browser_aligned_websocket_headers,
    build_websocket_auth_payload,
    fetch_browser_session_snapshot_sync,
    inspect_available_jobs_page_sync,
    open_url_in_browser_debug_sync,
    refresh_browser_page_activity_sync,
)
from .browser_debug_launcher import (
    get_firefox_debug_launch_spec,
    get_firefox_debug_retry_window,
    maybe_launch_managed_firefox_debug,
)
from .browser_detector import get_preferred_browser_user_agent
from .config import AppConfig
from .job_acceptance import JobAcceptanceEngine
from .job_cancellation_manager import JobCancellationManager
from .state import AppState
from .translation_app_queue import (
    submit_translation_app_task as _submit_translation_app_task,
)
from .watcher_debug import (
    redact_raw_ws_text as _redact_raw_ws_text,
    redact_raw_ws_value as _redact_raw_ws_value,
)
from .watcher_job_metadata import (
    TIER_UNIT_RATES,
    coerce_positive_float,
    coerce_positive_int,
    derive_lang_pair,
    derive_word_count,
    estimate_word_count_from_reward,
    format_lang_token,
    normalize_lang_pair_string,
    normalize_meta,
    parse_lang_pair_from_title,
    pick_meta_value,
    resolve_tier_rate,
)
from .watcher_health import (
    alert_on_health_snapshot as _alert_on_health_snapshot,
    build_health_snapshot,
    get_websocket_quiet_age,
    has_error_message,
    timestamp_or_none,
)
from .webhooks import WebhookAuditLogger, WebhookDispatcher

from . import notifier

try:
    from .browser_worker.client import BrowserWorkerClient
except ImportError:  # pragma: no cover - optional integration at runtime
    BrowserWorkerClient = None

try:
    from .email_monitor import EmailMonitor
except ImportError:
    EmailMonitor = None

try:
    from .website_monitor import WebsiteMonitor
except ImportError:
    WebsiteMonitor = None

try:
    from .translation_app_client import TranslationAppClient
except ImportError:  # pragma: no cover - optional integration at runtime
    TranslationAppClient = None

PLACEHOLDER_CONFIG_VALUES = {
    None,
    "",
    "REPLACE_WITH_YOUR_SESSION_TOKEN",
    "REPLACE_WITH_YOUR_USER_KEY",
    "REPLACE_WITH_YOUR_TRANSLATION_APP_TOKEN",
}

SENSITIVE_KEYWORDS = {"auth", "cookie", "key", "password", "secret", "session", "token"}


def _redact_config_for_log(value: Any, key: str = "") -> Any:
    """Return a log-safe copy of nested config data."""
    if isinstance(value, dict):
        return {
            item_key: _redact_config_for_log(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_config_for_log(item, key) for item in value]

    if any(marker in key.lower() for marker in SENSITIVE_KEYWORDS):
        if value in (None, ""):
            return value
        text = str(value)
        if len(text) <= 8:
            return "***"
        return f"{text[:4]}...{text[-4:]}"
    return value


class GengoWatcher:
    PAUSE_FILE = "gengowatcher.pause"

    def __init__(self, config: AppConfig, state: AppState, logger: logging.Logger):
        """
        Initialises the GengoWatcher and configures its core subsystems.

        Initial setup includes wiring configuration and persistent state, preparing logging (CSV entry logging when enabled), and initialising the CAPTCHA solver, browser automation engine, job acceptance engine and job cancellation manager. Also initialises thread/async coordination primitives and WebSocket heartbeat/diagnostic fields used by monitoring and UI components.
        """
        logger.info(
            f"[DIAG] websockets module path: {getattr(websockets, '__file__', 'unknown')}"
        )
        logger.info(
            f"[DIAG] websockets version: {getattr(websockets, '__version__', 'unknown')}"
        )
        import asyncio

        logger.info(
            f"[DIAG] asyncio module path: {getattr(asyncio, '__file__', 'unknown')}"
        )
        self.logger = logger
        self.config = config
        self.state = state
        self.webhook_audit_logger = WebhookAuditLogger.from_config(config, logger)
        self.webhook_dispatcher = WebhookDispatcher.from_config(
            config,
            logger,
            self.webhook_audit_logger,
        )
        self.browser_backend = str(
            config.get("Browser", "backend", fallback="native") or ""
        ).lower()
        self.native_browser_mode = self.browser_backend == "native"
        self.browser_worker_enabled = config.getboolean(
            "BrowserWorker", "enabled", fallback=False
        )
        if (
            self.native_browser_mode
            and self.browser_worker_enabled
            and not config.getboolean("Browser", "allow_playwright", fallback=False)
        ):
            logger.warning(
                "BrowserWorker disabled: native browser mode does not allow "
                "BrowserWorker/Playwright unless Browser.allow_playwright is true"
            )
            self.browser_worker_enabled = False

        # Validate critical config values to prevent infinite loops or crashes
        check_interval = config.get("Watcher", "check_interval")
        if check_interval is not None and check_interval < 1:
            logger.warning(
                f"check_interval={check_interval} is too low, using minimum of 5 seconds"
            )
            config.set("Watcher", "check_interval", 5)

        self.shutdown_event = threading.Event()
        self.check_now_event = threading.Event()
        self._test_command = None
        self._test_command_lock = threading.Lock()
        self.last_check_time = None
        self.next_check_time = time.time()
        self.failure_count = 0
        self.rss_action = "Initializing"
        self.start_time = time.time()
        self.session_new_entries = 0
        self.session_total_value = 0.0
        self.websocket_status = "Disabled"
        # WebSocket heartbeat metrics (read by UI thread)
        self.websocket_last_pong_ts = None  # float epoch seconds
        self.websocket_ping_latency_ms = None  # float milliseconds
        self.websocket_next_ping_ts = None  # float epoch seconds
        self.websocket_last_message_ts = None  # float epoch seconds
        self.websocket_connected_at_ts = None  # float epoch seconds
        self.websocket_last_close_code = None
        self.websocket_last_close_reason = None
        self.websocket_reconnect_count = 0
        # Email monitor metrics (read by UI)
        self.email_monitor_status = "Disabled"
        self.email_last_check_time = None
        self.email_jobs_found_session = 0

        # Website monitor metrics (read by UI)
        self.website_monitor_status = "Disabled"
        self.website_last_check_time = None
        self.website_jobs_found_session = 0

        # Browser available-jobs page monitor metrics (read by UI/health callers)
        self.browser_jobs_monitor_status = "Disabled"
        self.browser_jobs_last_check_time = None
        self.browser_jobs_found_session = 0
        self.browser_jobs_last_action = ""
        self._seen_jobs_session = set(state.seen_job_ids)
        self._seen_jobs_lock = threading.Lock()
        self._all_entries_log_file = None
        self._csv_writer = None
        self._shutdown_initiated = False
        self._rss_executor = None
        self._rss_future = None
        self._rss_future_started_at = None
        self._websocket_session_refresh_requested = False
        self._websocket_sync_failed = False
        self._websocket_sync_failure_reason = None
        self._browser_session_last_sync_ts = None
        self._browser_session_last_sync_state = "idle"
        self._browser_session_last_sync_detail = "never synced"
        self._next_quiet_socket_sync_ts = None
        self._health_alert_states = {}
        # Thread references for health monitoring
        self._monitor_threads = {}  # name -> threading.Thread
        # Raw WebSocket message buffer for debug output
        self._raw_ws_messages = deque(maxlen=50)
        self._raw_ws_lock = threading.Lock()
        self.logger.debug(
            "Initializing GengoWatcher with config: %s",
            _redact_config_for_log(self.config.config),
        )
        if self.config.get("Logging", "log_all_entries_enabled"):
            self._setup_csv_logging()

        # Callback for UI notification when a new job is added (set by UI)
        self.on_job_added_callback: Optional[Callable[[dict], None]] = None
        self.on_api_event_callback: Optional[Callable[[str, dict], None]] = None

        # Initialize job acceptance engine (without CAPTCHA support)
        self.job_acceptance_engine = JobAcceptanceEngine(
            config,
            logger,
        )
        self.browser_worker_client = self._build_browser_worker_client()
        self._warn_if_browser_session_mismatch()

        # Initialize job cancellation manager
        self.cancellation_manager = JobCancellationManager(config, logger)
        self.cancellation_manager.load_job_state()
        self._configure_cancellation_manager()

        self.logger.info(f"GengoWatcher v{__version__} initialized.")

    def _emit_webhook_event(
        self,
        event_type: str,
        payload: dict,
        *,
        event_id: str | None = None,
    ) -> None:
        """Emit an outbound webhook event without blocking watcher monitors."""
        dispatcher = getattr(self, "webhook_dispatcher", None)
        if dispatcher is None or not getattr(dispatcher, "enabled", False):
            return
        try:
            self.logger.info(
                "Webhook emit queued type=%s job=%s",
                event_type,
                payload.get("id", payload.get("subsystem", "n/a")),
            )
            dispatcher.emit(event_type, dict(payload), event_id=event_id)
        except Exception:
            self.logger.exception(
                "Failed to queue webhook event %s for job %s",
                event_type,
                payload.get("id", "unknown"),
            )

    def _emit_api_event(self, event_type: str, payload: dict) -> None:
        """Emit an in-process API websocket event without blocking monitors."""
        callback = getattr(self, "on_api_event_callback", None)
        if not callable(callback):
            return
        try:
            callback(event_type, dict(payload))
        except Exception:
            self.logger.exception(
                "Failed to publish API event %s for job %s",
                event_type,
                payload.get("id", payload.get("job_id", "unknown")),
            )

    @staticmethod
    def _json_safe(value):
        try:
            return json.loads(json.dumps(value, default=str))
        except Exception:
            return str(value)

    def _build_browser_worker_client(self):
        if BrowserWorkerClient is None:
            return None
        if not self.browser_worker_enabled:
            return None

        socket_path = self.config.get("BrowserWorker", "socket_path") or ""
        if not socket_path:
            self.logger.warning(
                "Browser worker is enabled but BrowserWorker.socket_path is empty"
            )
            return None

        auth_token = str(
            self.config.get("BrowserWorker", "auth_token", fallback="") or ""
        )
        return BrowserWorkerClient(
            socket_path=socket_path,
            logger=self.logger,
            auth_token=auth_token,
        )

    def _browser_worker_telemetry_path(self) -> Path:
        artifacts_dir = str(
            self.config.get(
                "BrowserWorker",
                "artifacts_dir",
                fallback="logs/browser-worker-artifacts",
            )
            or "logs/browser-worker-artifacts"
        )
        return Path(artifacts_dir) / "worker.jsonl"

    @staticmethod
    def _mask_secret(value) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if len(text) <= 4:
            return "*" * len(text)
        if len(text) <= 8:
            return f"{text[0]}{'*' * (len(text) - 2)}{text[-1]}"
        return f"{text[:4]}...{text[-4:]}"

    def _warn_if_browser_session_mismatch(self) -> None:
        debug_url = self.config.get("WebSocket", "browser_debug_url")
        configured_token = self.config.get("WebSocket", "user_session")

        if not debug_url or configured_token in PLACEHOLDER_CONFIG_VALUES:
            return

        try:
            snapshot = fetch_browser_session_snapshot_sync(str(debug_url))
        except Exception as exc:
            self.logger.debug(
                "Browser session check skipped for %s: %s",
                debug_url,
                exc,
            )
            return

        browser_token = snapshot.session_token
        if browser_token == configured_token:
            return

        self.logger.warning(
            "WebSocket.user_session differs from the live browser session at %s "
            "(config=%s browser=%s). Realtime detections may fall back to RSS until"
            " you sync the token.",
            debug_url,
            self._mask_secret(configured_token),
            self._mask_secret(browser_token),
        )

    def _get_default_required_config_fields(self) -> list[tuple[str, str]]:
        """Return the required config fields for currently enabled features."""
        required_fields = [("Watcher", "feed_url"), ("Watcher", "check_interval")]

        if self.config.getboolean("WebSocket", "enable_websocket", fallback=True):
            required_fields.extend(
                [("WebSocket", "user_id"), ("WebSocket", "user_session")]
            )

        if self.config.getboolean("EmailMonitor", "enabled", fallback=False):
            required_fields.extend(
                [
                    ("EmailMonitor", "email"),
                    ("EmailMonitor", "client_id"),
                    ("EmailMonitor", "client_secret"),
                    ("EmailMonitor", "refresh_token"),
                ]
            )

        if self.config.getboolean("WebsiteMonitor", "enabled", fallback=False):
            required_fields.append(("WebsiteMonitor", "jobs_url"))

        if self.config.getboolean("AutoAccept", "enabled", fallback=False):
            required_fields.append(("AutoAccept", "browser_profile_path"))

        if self.config.getboolean("BrowserWorker", "enabled", fallback=False):
            required_fields.append(("BrowserWorker", "socket_path"))

        return required_fields

    def _get_session_sync_interval_seconds(self) -> int:
        return self.config.getint(
            "WebSocket", "session_sync_interval_sec", fallback=14400
        )

    def _has_cached_websocket_credentials(self) -> bool:
        session_token = str(self.config.get("WebSocket", "user_session") or "").strip()
        return bool(session_token and session_token not in PLACEHOLDER_CONFIG_VALUES)

    def _get_session_quiet_probe_seconds(self) -> int:
        return self.config.getint("WebSocket", "session_quiet_probe_sec", fallback=90)

    def _get_session_quiet_stale_seconds(self) -> int:
        configured = self.config.getint(
            "WebSocket", "session_quiet_stale_after_sec", fallback=0
        )
        if configured and configured > 0:
            return configured
        return max(self._get_session_quiet_probe_seconds() * 2, 300)

    def _get_websocket_quiet_age(self, current_time: float) -> float | None:
        return get_websocket_quiet_age(self, current_time)

    @staticmethod
    def _timestamp_or_none(value):
        return timestamp_or_none(value)

    def get_health_snapshot(
        self, now: float | None = None
    ) -> dict[str, dict[str, object]]:
        return build_health_snapshot(self, now=now)

    @staticmethod
    def _has_error_message(status: object) -> bool:
        return has_error_message(status)

    def alert_on_health_snapshot(self, snapshot: dict[str, dict[str, object]]) -> None:
        _alert_on_health_snapshot(self, snapshot)

    def _sync_session_from_browser(
        self,
        *,
        fail_hard: bool = False,
        alert_on_failure: bool = False,
    ) -> bool:
        """Refresh the configured websocket session token from a live browser."""
        debug_url = self.config.get("WebSocket", "browser_debug_url")
        if not debug_url:
            return False

        snapshot = None
        sync_error: Exception | None = None
        try:
            snapshot = fetch_browser_session_snapshot_sync(str(debug_url))
        except Exception as exc:
            sync_error = exc
            if maybe_launch_managed_firefox_debug(
                self.config,
                str(debug_url),
                logger=self.logger,
            ):
                timeout_sec, retry_interval_sec = get_firefox_debug_retry_window(
                    self.config
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
            self._browser_session_last_sync_ts = time.time()
            self._browser_session_last_sync_state = "error"
            error_detail = str(sync_error or "browser session sync failed")
            self._browser_session_last_sync_detail = error_detail
            self.logger.warning(
                "Browser session sync failed for %s: %s",
                debug_url,
                error_detail,
            )
            if self._has_cached_websocket_credentials():
                self.logger.warning(
                    "Browser session sync failed for %s, but cached WebSocket"
                    " credentials are present. Continuing with the last known"
                    " session instead of stopping realtime monitoring.",
                    debug_url,
                )
                self._websocket_sync_failed = False
                self._websocket_sync_failure_reason = None
                return False
            if alert_on_failure:
                sound_file = self.config.get(
                    "Paths", "browser_session_sync_failed_sound_file"
                )
                self.show_notification(
                    message=f"Browser session sync failed: {error_detail}",
                    title="GengoWatcher Session Sync Failed",
                    play_sound=True,
                    sound_file=sound_file or None,
                )
            if fail_hard:
                self._websocket_sync_failed = True
                self._websocket_sync_failure_reason = error_detail
                self.websocket_status = "Session Sync Failed"
            return False

        current_token = self.config.get("WebSocket", "user_session")
        current_browser_user_agent = self.config.get("Network", "browser_user_agent")
        current_accept_language = self.config.get("Network", "browser_accept_language")
        browser_token = snapshot.session_token
        browser_user_agent = str(snapshot.user_agent or "").strip()
        browser_accept_language = str(snapshot.accept_language or "").strip()
        self._browser_session_last_sync_ts = time.time()
        self._browser_session_last_sync_state = "healthy"
        changed_fields = []
        if browser_token != current_token:
            self.config.set("WebSocket", "user_session", browser_token)
            changed_fields.append("user_session")
        if (
            browser_user_agent
            and browser_user_agent != str(current_browser_user_agent or "").strip()
        ):
            self.config.set("Network", "browser_user_agent", browser_user_agent)
            changed_fields.append("browser_user_agent")
        if (
            browser_accept_language
            and browser_accept_language != str(current_accept_language or "").strip()
        ):
            self.config.set(
                "Network", "browser_accept_language", browser_accept_language
            )
            changed_fields.append("browser_accept_language")
        if str(debug_url) != str(
            self.config.get("WebSocket", "browser_debug_url") or ""
        ):
            self.config.set("WebSocket", "browser_debug_url", str(debug_url))
            changed_fields.append("browser_debug_url")

        if changed_fields:
            self.config.save_config()
            self._browser_session_last_sync_detail = (
                f"updated {', '.join(changed_fields)}"
            )
        else:
            self._browser_session_last_sync_detail = "unchanged"
        self.logger.info(
            "Updated WebSocket session settings from live browser session at %s "
            "(session=%s)",
            debug_url,
            self._mask_secret(browser_token),
        )
        return bool(changed_fields)

    def _pick_quiet_socket_sync_delay_seconds(self) -> float:
        min_delay = float(
            self.config.get("WebSocket", "browser_activity_min_sec", fallback=300)
            or 300
        )
        max_delay = float(
            self.config.get("WebSocket", "browser_activity_max_sec", fallback=3600)
            or 3600
        )
        if max_delay < min_delay:
            min_delay, max_delay = max_delay, min_delay
        return random.uniform(min_delay, max_delay)

    def _sync_browser_session_for_quiet_socket(
        self,
        *,
        current_time: float | None = None,
        fail_hard: bool = False,
        alert_on_failure: bool = False,
    ) -> bool:
        """Refresh the browser session when a quiet websocket needs a recheck."""
        debug_url = self.config.get("WebSocket", "browser_debug_url")
        if not debug_url or self.websocket_status != "Live":
            return False

        now = current_time if current_time is not None else time.time()
        quiet_age = self._get_websocket_quiet_age(now)
        quiet_probe_after = self._get_session_quiet_probe_seconds()
        if quiet_age is None or quiet_age < quiet_probe_after:
            return False

        next_sync_ts = self._next_quiet_socket_sync_ts
        if next_sync_ts is not None and now < next_sync_ts:
            return False
        if self._browser_session_last_sync_ts is not None:
            sync_age = max(0.0, now - self._browser_session_last_sync_ts)
            if sync_age < quiet_probe_after:
                return False

        self.logger.warning(
            "WebSocket: No application messages for %.1fs while live; syncing browser"
            " session from %s before continuing.",
            quiet_age,
            debug_url,
        )

        changed = self._sync_session_from_browser(
            fail_hard=fail_hard,
            alert_on_failure=alert_on_failure,
        )
        if changed:
            self._next_quiet_socket_sync_ts = None
            return True

        self._next_quiet_socket_sync_ts = (
            now + self._pick_quiet_socket_sync_delay_seconds()
        )
        return False

    def _sync_session_before_websocket_connect(self) -> bool:
        """Try to sync browser session once before building websocket auth."""
        debug_url = self.config.get("WebSocket", "browser_debug_url")
        if not debug_url:
            return True

        sync_fail_hard = self.config.getboolean(
            "WebSocket", "session_sync_fail_hard", fallback=True
        )
        sync_alert_on_failure = self.config.getboolean(
            "WebSocket",
            "session_sync_alert_on_failure",
            fallback=True,
        )
        self.logger.info(
            "WebSocket: Syncing browser session from %s before connecting.",
            debug_url,
        )
        self._sync_session_from_browser(
            fail_hard=sync_fail_hard,
            alert_on_failure=sync_alert_on_failure,
        )
        if self._websocket_sync_failed:
            self.logger.error("WebSocket: Browser session sync failed before connect.")
            return False
        return True

    def _is_gengo_rss_feed(self) -> bool:
        feed_url = str(self.config.get("Watcher", "feed_url") or "")
        return "gengo.com" in feed_url.lower()

    def _get_effective_rss_wait_range_seconds(self) -> tuple[float, float]:
        if self._is_gengo_rss_feed():
            min_delay = float(
                self.config.get("Watcher", "gengo_rss_interval_min_sec", fallback=31)
                or 31
            )
            max_delay = float(
                self.config.get("Watcher", "gengo_rss_interval_max_sec", fallback=60)
                or 60
            )
            if max_delay < min_delay:
                min_delay, max_delay = max_delay, min_delay
            return min_delay, max_delay

        check_interval = float(self.config.get("Watcher", "check_interval") or 45)
        return check_interval, check_interval

    def _get_effective_rss_check_interval(self) -> float:
        if self._is_gengo_rss_feed():
            _min_delay, max_delay = self._get_effective_rss_wait_range_seconds()
            check_interval = float(self.config.get("Watcher", "check_interval") or 45)
            return max(check_interval, max_delay)
        return float(self.config.get("Watcher", "check_interval") or 45)

    def _pick_next_rss_wait_seconds(self) -> float:
        min_delay, max_delay = self._get_effective_rss_wait_range_seconds()
        if min_delay == max_delay:
            return min_delay
        return random.uniform(min_delay, max_delay)

    def _pick_planned_websocket_reconnect_delay_seconds(self) -> float:
        min_delay = float(
            self.config.get("WebSocket", "planned_reconnect_min_sec", fallback=300)
            or 300
        )
        max_delay = float(
            self.config.get("WebSocket", "planned_reconnect_max_sec", fallback=3600)
            or 3600
        )
        if max_delay < min_delay:
            min_delay, max_delay = max_delay, min_delay
        return random.uniform(min_delay, max_delay)

    def _pick_browser_activity_delay_seconds(self) -> float:
        min_delay = float(
            self.config.get("WebSocket", "browser_activity_min_sec", fallback=300)
            or 300
        )
        max_delay = float(
            self.config.get("WebSocket", "browser_activity_max_sec", fallback=3600)
            or 3600
        )
        if max_delay < min_delay:
            min_delay, max_delay = max_delay, min_delay
        return random.uniform(min_delay, max_delay)

    def _perform_browser_activity(self) -> str | None:
        debug_url = self.config.get("WebSocket", "browser_debug_url")
        if not debug_url:
            return None

        previous_action = getattr(self, "_last_browser_activity_action", None)
        action = refresh_browser_page_activity_sync(
            str(debug_url),
            previous_action=previous_action,
        )
        self._last_browser_activity_action = action
        return action

    def _browser_jobs_monitor_enabled(self) -> bool:
        if not self.config.getboolean("BrowserJobs", "enabled", fallback=True):
            return False
        return bool(self.config.get("WebSocket", "browser_debug_url", fallback=""))

    def _browser_jobs_navigation_enabled(self) -> bool:
        return self.config.getboolean("BrowserJobs", "allow_navigation", fallback=False)

    def _get_browser_jobs_poll_interval_seconds(self) -> float:
        interval = float(
            self.config.getfloat("BrowserJobs", "poll_interval_sec", fallback=1.5)
            or 1.5
        )
        return max(0.25, interval)

    def _pick_browser_jobs_refresh_delay_seconds(self) -> float:
        min_delay = float(
            self.config.getfloat("BrowserJobs", "refresh_min_sec", fallback=20.0)
            or 20.0
        )
        max_delay = float(
            self.config.getfloat("BrowserJobs", "refresh_max_sec", fallback=65.0)
            or 65.0
        )
        if max_delay < min_delay:
            min_delay, max_delay = max_delay, min_delay
        return random.uniform(max(1.0, min_delay), max(1.0, max_delay))

    def _pick_browser_jobs_browse_delay_seconds(self) -> float:
        min_delay = float(
            self.config.getfloat("BrowserJobs", "browse_min_sec", fallback=180.0)
            or 180.0
        )
        max_delay = float(
            self.config.getfloat("BrowserJobs", "browse_max_sec", fallback=420.0)
            or 420.0
        )
        if max_delay < min_delay:
            min_delay, max_delay = max_delay, min_delay
        return random.uniform(max(10.0, min_delay), max(10.0, max_delay))

    def _browser_jobs_mouse_activity_enabled(self) -> bool:
        probability = float(
            self.config.getfloat(
                "BrowserJobs",
                "mouse_activity_probability",
                fallback=0.25,
            )
            or 0.0
        )
        return random.random() < min(1.0, max(0.0, probability))

    def _process_browser_jobs_snapshot(self, snapshot) -> int:
        processed = 0
        candidates = list(snapshot.detected_jobs) + list(snapshot.jobs)
        seen_candidate_ids: set[int] = set()
        for job in candidates:
            if job.job_id in seen_candidate_ids:
                continue
            seen_candidate_ids.add(job.job_id)
            self._process_new_job(
                job.job_id,
                job.title,
                job.reward,
                job.url,
                source="BrowserJobs",
                source_meta={
                    "title": job.title,
                    "reward": job.reward,
                    "url": job.url,
                    "text": job.text,
                    "browser_action": snapshot.action,
                    "browser_page_url": snapshot.url,
                },
            )
            processed += 1
        return processed

    def get_monitor_status(self) -> dict:
        """
        Check health of all monitor threads.

        Returns:
            dict: Mapping of monitor name to status ("alive", "dead", "disabled")
        """
        status = {}
        for name in [
            "rss",
            "websocket",
            "email",
            "website",
            "browser_worker",
            "native_browser",
            "browser_jobs",
        ]:
            thread = self._monitor_threads.get(name)
            if thread is None:
                status[name] = "disabled"
            elif thread.is_alive():
                status[name] = "alive"
            else:
                status[name] = "dead"
        status["email_detail"] = self.email_monitor_status
        status["website_detail"] = self.website_monitor_status
        status["browser_jobs_detail"] = self.browser_jobs_monitor_status
        return status

    def _sync_monitor_metrics(self):
        """Sync metrics from email and website monitors."""
        if hasattr(self, "_email_monitor") and self._email_monitor:
            self.email_monitor_status = getattr(
                self._email_monitor, "status", "Disabled"
            )
            self.email_last_check_time = getattr(
                self._email_monitor, "last_check_time", None
            )
            self.email_jobs_found_session = getattr(
                self._email_monitor, "jobs_found_session", 0
            )

        if hasattr(self, "_website_monitor") and self._website_monitor:
            self.website_monitor_status = getattr(
                self._website_monitor, "status", "Disabled"
            )
            self.website_last_check_time = getattr(
                self._website_monitor, "last_check_time", None
            )
            self.website_jobs_found_session = getattr(
                self._website_monitor, "jobs_found_session", 0
            )

    def _capture_raw_ws_message(self, message: str, direction: str = "recv"):
        """Capture raw WebSocket message for debug output when raw debug is enabled.

        Args:
            message: The raw message string (JSON or otherwise)
            direction: "recv" for received, "send" for sent
        """
        if not self.config.get("DebugCategories", "raw"):
            return

        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        prefix = "→" if direction == "send" else "←"

        # Try to pretty-format JSON
        try:
            parsed = json.loads(message)
            parsed = _redact_raw_ws_value(parsed)
            formatted = json.dumps(parsed, indent=2)
        except (json.JSONDecodeError, TypeError):
            formatted = _redact_raw_ws_text(str(message))

        entry = f"[{timestamp}] {prefix} {formatted}"

        with self._raw_ws_lock:
            self._raw_ws_messages.append(entry)

    def get_raw_ws_messages(self) -> list:
        """Get a copy of the raw WebSocket message buffer.

        Returns:
            List of raw message entries with timestamps
        """
        with self._raw_ws_lock:
            return list(self._raw_ws_messages)

    def clear_raw_ws_messages(self):
        """Clear the raw WebSocket message buffer."""
        with self._raw_ws_lock:
            self._raw_ws_messages.clear()

    def _setup_csv_logging(self):
        """
        Initialise CSV logging for recording RSS feed entries.

        Creates the configured log directory if missing, opens the log file for appending and initialises a CSV writer. If the file is empty a header row ("timestamp", "title", "reward", "link", "summary") is written. If the file cannot be opened, CSV logging is disabled and an error is logged.
        """
        self.logger.debug("Setting up CSV logging.")
        try:
            log_path_str = self.config.get("Paths", "all_entries_log")
            if not log_path_str or not isinstance(log_path_str, (str, Path)):
                self.logger.error("all_entries_log path not configured or invalid")
                return
            log_path = Path(str(log_path_str))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._all_entries_log_file = open(
                log_path, "a", newline="", encoding="utf-8"
            )
            self._csv_writer = csv.writer(self._all_entries_log_file)
            if log_path.stat().st_size == 0:
                self._csv_writer.writerow(
                    ["timestamp", "title", "reward", "link", "summary"]
                )
            self.logger.debug(f"CSV logging enabled at {log_path}")
        except IOError as e:
            self.logger.error(f"Could not open all_entries_log file: {e}")
            self._all_entries_log_file = None
            self._csv_writer = None

    def show_notification(
        self,
        message,
        title="GengoWatcher",
        play_sound=False,
        open_link=False,
        url=None,
        sound_file=None,
    ):
        """
        Send a desktop notification and optionally play a sound or open a URL.

        Parameters:
            message (str): Notification message body.
            title (str): Notification title; defaults to "GengoWatcher".
            play_sound (bool): If True and sound is enabled in configuration, play the configured sound.
            open_link (bool): If True and `url` is provided, open the URL in the configured browser.
            url (str | None): URL to open when `open_link` is True; ignored if not provided.
            sound_file (str | None): Optional override sound path; defaults to Paths.sound_file.
        """
        if self.config.get("Watcher", "enable_notifications"):
            icon_path = self.config.get("Paths", "notification_icon_path")
            notifier.send_notification(title, message, icon_path)

        if play_sound and self.config.get("Watcher", "enable_sound"):
            chosen_sound = sound_file or self.config.get("Paths", "sound_file")
            notifier.play_sound(chosen_sound)

        if open_link and url:
            self.open_in_browser(url)

    @staticmethod
    def _is_gengo_url(url: str) -> bool:
        parsed = urlparse(str(url or "").strip())
        hostname = parsed.hostname or ""
        return hostname == "gengo.com" or hostname.endswith(".gengo.com")

    def _open_in_managed_firefox_debug_session(self, url: str) -> bool:
        if not self._is_gengo_url(url):
            return False

        debug_url = self.config.get("WebSocket", "browser_debug_url") or ""
        try:
            spec = get_firefox_debug_launch_spec(self.config, str(debug_url))
        except Exception as exc:
            self.logger.debug(
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
            self.logger.debug(
                "Opened URL in managed Firefox debug session at %s: %s",
                spec.debug_url,
                url,
            )
            return True
        except Exception as exc:
            last_exc = exc

        if maybe_launch_managed_firefox_debug(
            self.config,
            spec.debug_url,
            logger=self.logger,
        ):
            timeout_sec, retry_interval_sec = get_firefox_debug_retry_window(
                self.config
            )
            deadline = time.monotonic() + timeout_sec
            while time.monotonic() < deadline:
                time.sleep(retry_interval_sec)
                try:
                    open_url_in_browser_debug_sync(spec.debug_url, url)
                    self.logger.debug(
                        "Opened URL in newly launched managed Firefox debug "
                        "session at %s: %s",
                        spec.debug_url,
                        url,
                    )
                    return True
                except Exception as exc:
                    last_exc = exc

        self.logger.warning(
            "Managed Firefox debug session at %s could not open %s (%s); "
            "falling back to configured browser",
            spec.debug_url,
            url,
            last_exc,
        )
        return False

    def open_in_browser(self, url):
        """
        Open the given URL using the configured browser if available, otherwise use the system default browser.

        Parameters:
            url (str): The URL to open. If the configured `browser_args` include formatting placeholders (for example `{url}`), they will be formatted with this URL.
        """
        self.logger.debug(f"Opening URL in browser: {url}")
        try:
            if self._open_in_managed_firefox_debug_session(str(url)):
                return

            browser_path_str = self.config.get("Paths", "browser_path")
            if not browser_path_str or not Path(browser_path_str).is_file():
                webbrowser.open(url)
            else:
                args = [
                    arg.format(url=url)
                    for arg in self.config.get("Paths", "browser_args").split()
                ]
                subprocess.Popen([str(browser_path_str)] + args)
        except Exception as e:
            self.logger.error(f"Browser Error: {e}")

    def _extract_reward(self, entry) -> float:
        """
        Extracts the numeric reward value from an RSS entry.

        Searches the entry's title and summary for a "Reward:" label followed by an optional currency symbol and returns the parsed value.

        Parameters:
            entry (Mapping): RSS entry containing at least 'title' and 'summary' strings.

        Returns:
            float: Reward amount as a float, or 0.0 if no valid reward is found.
        """
        text = entry.get("title", "") + " | " + entry.get("summary", "")
        self.logger.debug(f"Extracting reward from entry: {text}")
        match = re.search(r"Reward:\s*(?:US\$|\$)?\s*(\d+\.?\d*)", text, re.IGNORECASE)
        try:
            return float(match.group(1)) if match else 0.0
        except (ValueError, IndexError):
            return 0.0

    def _log_all_entries(self, entries):
        """Log all RSS entries to the CSV file.

        Writes each entry's timestamp, title, reward, link, and summary to the
        configured CSV log file. Only logs if CSV writer is properly initialized.

        Args:
            entries: List of RSS entry dictionaries to log.
        """
        self.logger.debug(f"Logging {len(entries)} entries to CSV.")
        if not self._csv_writer:
            return
        timestamp = datetime.datetime.now().isoformat()
        for entry in entries:
            self._csv_writer.writerow(
                [
                    timestamp,
                    entry.get("title", "N/A"),
                    self._extract_reward(entry),
                    entry.get("link", "N/A"),
                    entry.get("summary", "N/A"),
                ]
            )
        self._all_entries_log_file.flush()

    def _process_new_job(self, job_id, title, reward, url, source, source_meta=None):
        """Process a newly discovered job from RSS or WebSocket sources.

        Handles job filtering, notification, storage, and auto-acceptance logic.
        Updates session statistics and ensures thread-safe access to shared state.

        Args:
            job_id: Unique identifier for the job.
            title: Job title/description.
            reward: Job reward amount in USD.
            url: URL to access the job.
            source: Source of the job discovery ("RSS" or "WebSocket").
            source_meta: Optional metadata from the source (entry dict, websocket payload, etc.).
        """
        self.logger.debug(
            f"Processing new job: {job_id}, {title}, {reward}, {url}, {source}"
        )
        with self._seen_jobs_lock:
            if job_id in self._seen_jobs_session:
                return
            min_reward = self.config.get("Watcher", "min_reward")
            if min_reward > 0.0 and reward < min_reward:
                self.logger.warning(
                    f"Job '{title}' (US$ {reward:.2f}) ignored due to [yellow]min_reward filter[/]."
                )
                return

            lang_pair = self._derive_lang_pair(title, source_meta)
            word_count = self._derive_word_count(title, source_meta, reward=reward)

            # Prepare job data for storage, callbacks, and acceptance checks
            job_data = {
                "id": str(job_id),
                "title": title,
                "reward": float(reward),
                "currency": "USD",
                "url": url,
                "timestamp": time.time(),
                "source": source,
                "lang_pair": lang_pair,
                "word_count": word_count,
                "source_meta": self._json_safe(source_meta or {}),
                "lifecycle_state": "detected",
                "acceptance_state": "not_requested",
                "workflow_state": "new",
            }

            try:
                inserted = self.state.add_job(job_data)
                if inserted is False:
                    # Job is a duplicate, bail out immediately
                    return

                # Job was successfully inserted, proceed with all side effects
                self.logger.info(
                    f"[success]New job via {source}: {title.split('|')[0].strip()} (US$ {reward:.2f})[/success]"
                )
                self.show_notification(
                    message=title,
                    title="New Gengo Job Available!",
                    play_sound=True,
                    open_link=True,
                    url=url,
                )

                # Update bookkeeping after successful add_job
                self._seen_jobs_session.add(job_id)
                self.state.seen_job_ids.append(job_id)
                self.state.total_new_entries_found += 1
                self.session_new_entries += 1
                self.session_total_value += reward
            except Exception as e:
                self.logger.warning(f"Failed to store job in state: {e}")
                return

        eligible_for_auto_accept = self.job_acceptance_engine.is_job_eligible(job_data)
        allow_http_fallback = self.config.getboolean(
            "AutoAccept", "allow_http_fallback", fallback=False
        )
        self._emit_webhook_event("job.discovered", job_data)
        self._emit_api_event("job.discovered", job_data)
        self._emit_api_event("job.details", job_data)

        if self.browser_worker_enabled and eligible_for_auto_accept:
            self.logger.info(
                "Routing job %s to browser worker via local client", job_id
            )
            if not self.browser_worker_client:
                if allow_http_fallback:
                    self.logger.error(
                        "Browser worker is enabled for job %s but the local client is unavailable;"
                        " falling back to standard acceptance path",
                        job_id,
                    )
                else:
                    self.logger.error(
                        "Browser worker is enabled for job %s but the local client is unavailable;"
                        " HTTP fallback is disabled",
                        job_id,
                    )
            else:
                try:
                    self.browser_worker_client.submit_job(
                        url,
                        source,
                        metadata=job_data,
                    )
                    accept_requested_payload = {
                        **job_data,
                        "accept_path": "browser_worker",
                        "acceptance_state": "requested",
                        "lifecycle_state": "accept_requested",
                    }
                    self._emit_webhook_event(
                        "job.accept_requested",
                        accept_requested_payload,
                    )
                    self.state.update_job(
                        str(job_id),
                        {
                            "acceptance_state": "requested",
                            "lifecycle_state": "accept_requested",
                            "accept_path": "browser_worker",
                        },
                    )
                    self._emit_api_event(
                        "job.accept_requested",
                        accept_requested_payload,
                    )
                    self.state.save_state()
                    if self.on_job_added_callback:
                        try:
                            self.on_job_added_callback(job_data)
                        except Exception as e:
                            self.logger.debug(f"Error in job added callback: {e}")
                    return
                except Exception as e:
                    if allow_http_fallback:
                        self.logger.error(
                            "Failed to submit job %s to browser worker: %s; falling back to"
                            " standard acceptance path",
                            job_id,
                            e,
                        )
                    else:
                        self.logger.error(
                            "Failed to submit job %s to browser worker: %s; HTTP fallback is disabled",
                            job_id,
                            e,
                        )

        # Consider cancelling a current job if this one is better
        try:
            if (
                self.cancellation_manager.cancellation_enabled
                and self.cancellation_manager.should_cancel_for_job(
                    float(job_data.get("reward", 0.0)), str(job_data.get("id"))
                )
            ):
                self.logger.info(
                    "Better opportunity detected - scheduling cancellation of current job before accepting new job"
                )
                threading.Thread(
                    target=self._async_cancel_current_job_wrapper,
                    args=(job_data,),
                    daemon=True,
                ).start()
        except Exception as e:
            self.logger.error(f"Error while evaluating job cancellation: {e}")

        # Check if job should be auto-accepted
        if eligible_for_auto_accept:
            if not allow_http_fallback:
                self.logger.info(
                    "Job %s meets auto-accept criteria, but standard HTTP acceptance is disabled",
                    job_id,
                )
                failed_payload = {
                    **job_data,
                    "acceptance_state": "failed",
                    "lifecycle_state": "accept_failed",
                    "accept_path": "native_browser",
                    "reason": "http fallback disabled",
                }
                self.state.update_job(
                    str(job_id),
                    {
                        "acceptance_state": "failed",
                        "lifecycle_state": "accept_failed",
                        "accept_path": "native_browser",
                        "accept_failure_reason": "http fallback disabled",
                    },
                )
                self.state.save_state()
                self._emit_webhook_event("job.accept_failed", failed_payload)
                self._emit_api_event("job.accept_failed", failed_payload)
                self._submit_job_to_translation_app_async(job_data)
                return

            self.logger.info(
                f"Job {job_id} meets auto-accept criteria, queuing for acceptance"
            )
            accept_requested_payload = {
                **job_data,
                "accept_path": "standard",
                "acceptance_state": "requested",
                "lifecycle_state": "accept_requested",
            }
            self._emit_webhook_event(
                "job.accept_requested",
                accept_requested_payload,
            )
            self.state.update_job(
                str(job_id),
                {
                    "acceptance_state": "requested",
                    "lifecycle_state": "accept_requested",
                    "accept_path": "standard",
                },
            )
            self._emit_api_event("job.accept_requested", accept_requested_payload)
            threading.Thread(
                target=self._async_job_acceptance_wrapper, args=(job_data,), daemon=True
            ).start()
        else:
            self.logger.debug(f"Job {job_id} does not meet auto-accept criteria")

        self._submit_job_to_translation_app_async(job_data)
        self.state.save_state()

        if self.on_job_added_callback:
            try:
                self.on_job_added_callback(job_data)
            except Exception as e:
                self.logger.debug(f"Error in job added callback: {e}")

    def _normalize_meta(self, meta) -> dict:
        return normalize_meta(meta)

    def _pick_meta_value(self, meta: dict, keys: list[str]):
        return pick_meta_value(meta, keys)

    def _format_lang_token(self, token: str) -> str:
        return format_lang_token(token)

    def _normalize_lang_pair_string(self, value) -> str:
        return normalize_lang_pair_string(value)

    def _parse_lang_pair_from_title(self, title) -> str:
        return parse_lang_pair_from_title(title)

    def _derive_lang_pair(self, title, source_meta) -> str:
        return derive_lang_pair(title, source_meta)

    def _coerce_positive_int(self, value) -> int:
        return coerce_positive_int(value)

    def _coerce_positive_float(self, value) -> float:
        return coerce_positive_float(value)

    def _resolve_tier_rate(self, tier_value) -> float:
        return resolve_tier_rate(tier_value)

    def _estimate_word_count_from_reward(self, reward, title, source_meta) -> int:
        return estimate_word_count_from_reward(reward, title, source_meta)

    def _derive_word_count(self, title, source_meta, reward=0.0) -> int:
        return derive_word_count(title, source_meta, reward)

    def _async_job_acceptance_wrapper(self, job_data: dict):
        """
        Wrapper to run async job acceptance in a separate thread.

        Args:
            job_data: Dictionary containing job information
        """
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            success = loop.run_until_complete(
                self.job_acceptance_engine.accept_job(job_data)
            )
            if success:
                self._on_job_accepted(job_data)
            else:
                self.state.update_job(
                    str(job_data.get("id")),
                    {
                        "acceptance_state": "failed",
                        "lifecycle_state": "accept_failed",
                        "accept_failure_reason": "accept_job returned false",
                    },
                )
                self.state.save_state()
                failed_payload = {
                    **job_data,
                    "acceptance_state": "failed",
                    "lifecycle_state": "accept_failed",
                    "reason": "accept_job returned false",
                }
                self._emit_webhook_event(
                    "job.accept_failed",
                    failed_payload,
                )
                self._emit_api_event("job.accept_failed", failed_payload)
        except Exception as e:
            self.logger.error(
                f"Error in job acceptance wrapper for job {job_data.get('id')}: {e}"
            )
            self.state.update_job(
                str(job_data.get("id")),
                {
                    "acceptance_state": "failed",
                    "lifecycle_state": "accept_failed",
                    "accept_failure_reason": str(e),
                },
            )
            self.state.save_state()
            failed_payload = {
                **job_data,
                "acceptance_state": "failed",
                "lifecycle_state": "accept_failed",
                "reason": str(e),
            }
            self._emit_webhook_event(
                "job.accept_failed",
                failed_payload,
            )
            self._emit_api_event("job.accept_failed", failed_payload)
        finally:
            loop.close()

    def _run_browser_worker_event_listener(self) -> None:
        telemetry_path = self._browser_worker_telemetry_path()
        self.logger.info("Browser worker event listener watching %s", telemetry_path)
        initialized = False
        while not self.shutdown_event.is_set():
            if not telemetry_path.exists():
                self.shutdown_event.wait(1.0)
                continue

            try:
                with telemetry_path.open("r", encoding="utf-8") as handle:
        self.logger.info("Browser worker event listener watching %s", telemetry_path)
        initialized = False
        skip_existing_on_open = True
        while not self.shutdown_event.is_set():
            ...
                    opened_stat = os.fstat(handle.fileno())
                    if not initialized:
                        if skip_existing_on_open:
                            handle.seek(0, os.SEEK_END)
                        initialized = True
                        skip_existing_on_open = False
                    while not self.shutdown_event.is_set():
                        line = handle.readline()
                        if not line:
                            try:
                                current_stat = telemetry_path.stat()
                                if (
                                    current_stat.st_size < handle.tell()
                                    or current_stat.st_ino != opened_stat.st_ino
                                    or current_stat.st_dev != opened_stat.st_dev
                                ):
                                    initialized = False
                                    skip_existing_on_open = False
                                    break
                            except OSError:
                                initialized = False
                                break
                            self.shutdown_event.wait(0.5)
                            continue
                        self._handle_browser_worker_telemetry_line(line)
            except OSError as exc:
                self.logger.debug(
                    "Browser worker telemetry listener could not read %s: %s",
                    telemetry_path,
                    exc,
                )
                self.shutdown_event.wait(1.0)
            except Exception:
                self.logger.exception("Browser worker telemetry listener failed")
                self.shutdown_event.wait(1.0)
        self.logger.info("Browser worker event listener stopped.")

    def _handle_browser_worker_telemetry_line(self, line: str) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            self.logger.debug("Ignoring malformed browser worker telemetry line")
            return
        if isinstance(payload, dict):
            self._handle_browser_worker_telemetry_payload(payload)

    def _handle_browser_worker_telemetry_payload(self, event_payload: dict) -> None:
        event = event_payload.get("event")
        if not isinstance(event, dict):
            return
        if event.get("name") != "accepted_workbench_payload":
            return

        payload = event_payload.get("payload")
        if not isinstance(payload, dict):
            return

        summary = payload.get("summary")
        if not isinstance(summary, dict):
            summary = {}
        job_id = str(
            event_payload.get("job_id") or summary.get("order_id") or ""
        ).strip()
        if not job_id:
            return

        accepted_workbench = {
            "source": str(event_payload.get("source") or "browser_worker"),
            "payload": payload,
        }
        updated = self.state.mark_job_accepted(
            job_id,
            accepted_workbench=accepted_workbench,
            workbench_url=event_payload.get("url"),
        )
        if updated:
            self.state.save_state()
            current_job = self.state.get_job(job_id)
            accepted_job = (
                current_job
                if isinstance(current_job, dict)
                else {
                    "id": job_id,
                    "workbench_url": event_payload.get("url"),
                    "accepted_workbench": accepted_workbench,
                    "source": "browser_worker",
                }
            )
            self.logger.info(
                "Browser worker captured accepted job %s; countdown tracking updated",
                job_id,
            )
            self._emit_webhook_event(
                "job.accepted",
                {
                    "id": job_id,
                    "workbench_url": event_payload.get("url"),
                    "accepted_workbench": accepted_workbench,
                    "source": "browser_worker",
                },
            )
            self._emit_api_event("job.accepted", accepted_job)
        else:
            self.logger.debug(
                "Browser worker captured accepted job %s but no stored job matched",
                job_id,
            )

    def _async_cancel_current_job_wrapper(self, upcoming_job: dict):
        """Wrapper to cancel the current job without blocking the main thread."""
        previous_job_id = self.cancellation_manager.current_job_id
        try:
            success = self.cancel_current_job_sync()
            if success:
                self.logger.info(
                    f"Current job {previous_job_id} cancelled. Preparing to accept {upcoming_job.get('id')}"
                )
            else:
                self.logger.warning(
                    "Failed to cancel current job before processing new opportunity"
                )
        except Exception as e:
            self.logger.error(f"Error during automatic job cancellation: {e}")

    def _on_job_accepted(self, job_data: dict):
        """Record that a job has been accepted for future cancellation decisions."""
        try:
            job_id = str(job_data.get("id"))
            reward = float(job_data.get("reward", 0.0))
            try:
                self.state.mark_job_accepted(
                    job_id,
                    accepted_workbench=job_data.get("accepted_workbench"),
                    workbench_url=job_data.get("workbench_url"),
                )
                self.state.save_state()
            except Exception:
                self.logger.exception(
                    "Failed to persist accepted job metadata for job %s",
                    job_id,
                )
            self.cancellation_manager.set_current_job(job_id, reward)
            self.logger.debug(
                f"Tracking job {job_id} (${reward:.2f}) as current engagement"
            )
            current_job = self.state.get_job(job_id)
            accepted_job = (
                current_job
                if isinstance(current_job, dict)
                else {
                    **job_data,
                    "accepted": True,
                    "acceptance_state": "accepted",
                    "lifecycle_state": "accepted",
                }
            )
            self._emit_webhook_event("job.accepted", accepted_job)
            self._emit_api_event("job.accepted", accepted_job)
        except Exception as e:
            self.logger.error(
                f"Failed to record accepted job for cancellation tracking: {e}"
            )

    def _submit_job_to_translation_app_async(self, job_data: dict) -> None:
        """Submit a discovered job to translation-app without blocking monitors."""
        if TranslationAppClient is None:
            self.logger.debug("translation-app client is unavailable")
            return
        if not self.config.getboolean("TranslationApp", "enabled", fallback=False):
            return

        base_url = str(
            self.config.get("TranslationApp", "base_url", fallback="") or ""
        ).strip()
        auth_token = str(
            self.config.get("TranslationApp", "auth_token", fallback="") or ""
        ).strip()
        if not base_url or auth_token in PLACEHOLDER_CONFIG_VALUES:
            self.logger.warning(
                "TranslationApp is enabled but base_url or auth_token is not configured"
            )
            return

        timeout_sec = float(
            self.config.getfloat("TranslationApp", "timeout_sec", fallback=5.0) or 5.0
        )
        verify_tls = self.config.getboolean(
            "TranslationApp", "verify_tls", fallback=True
        )

        def submit() -> None:
            try:
                client = TranslationAppClient(
                    base_url=base_url,
                    auth_token=auth_token,
                    timeout_sec=timeout_sec,
                    verify_tls=verify_tls,
                    logger=self.logger,
                )
                client.submit_job(dict(job_data))
            except Exception:
                self.logger.exception(
                    "Failed to submit job %s to translation-app",
                    job_data.get("id", "unknown"),
                )

        try:
            _submit_translation_app_task(submit)
        except queue.Full:
            self.logger.warning(
                "Translation-app submission queue is full; dropping job %s",
                job_data.get("id", "unknown"),
            )
        except Exception:
            self.logger.exception(
                "Failed to queue job %s for translation-app submission",
                job_data.get("id", "unknown"),
            )

    def _process_feed_entries(self, entries):
        """Process RSS feed entries to identify new jobs.

        Filters entries to find only new ones since the last check, extracts job
        information, and processes each new job. Updates the last seen RSS link
        to avoid duplicate processing.

        Args:
            entries: List of RSS entry dictionaries from the feed parser.
        """
        self.logger.debug(f"Processing {len(entries) if entries else 0} RSS entries.")
        if not entries:
            return
        self._log_all_entries(entries)
        new_entries = []
        for entry in entries:
            link = entry.get("link")
            if not link:
                self.logger.debug(f"Skipping entry with no link: {entry}")
                continue
            if link == self.state.last_seen_rss_link:
                self.logger.debug(f"Reached last seen RSS link: {link}")
                break
            new_entries.append(entry)
        self.logger.debug(f"Found {len(new_entries)} new RSS entries.")
        if not new_entries:
            return
        latest_link = new_entries[0].get("link")
        self.state.last_seen_rss_link = latest_link
        self.state.last_seen_link = latest_link
        for entry in reversed(new_entries):
            title = entry.get("title", "No Title")
            url = entry.get("link")
            self.logger.debug(f"Processing new RSS entry: {title} {url}")
            try:
                match = re.search(r"/jobs/details/(\d+)", url)
                if not match:
                    self.logger.warning(f"Could not parse job ID from RSS link: {url}")
                    continue
                job_id = int(match.group(1))
                reward = self._extract_reward(entry)
                self._process_new_job(
                    job_id,
                    title,
                    reward,
                    url,
                    source="RSS",
                    source_meta=entry,
                )
            except (ValueError, IndexError) as e:
                self.logger.warning(f"Error processing RSS entry {url}: {e}")

    def fetch_rss(self):
        """Fetch and parse the RSS feed from Gengo.

        Retrieves the RSS feed using feedparser with an optional browser-like user agent.
        Handles various error conditions and logs appropriate messages.

        Returns:
            feedparser.FeedParserDict: Parsed RSS feed object, or None if fetch failed.

        Raises:
            Exception: For network or parsing errors (logged internally).
        """
        headers = {}
        if self.config.get("Watcher", "use_custom_user_agent"):
            headers["User-Agent"] = get_preferred_browser_user_agent(
                self.config, self.logger
            )
        self.logger.debug(
            f"Fetching RSS feed: {self.config.get('Watcher', 'feed_url')} with headers: {headers}"
        )
        try:
            feed_url = self.config.get("Watcher", "feed_url")
            # Wrap feedparser in thread with timeout to prevent blocking
            if self._rss_executor is None:
                self._rss_executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1
                )
            if self._rss_future is not None:
                if not self._rss_future.done():
                    elapsed = (
                        time.monotonic() - self._rss_future_started_at
                        if self._rss_future_started_at is not None
                        else 0.0
                    )
                    self.logger.warning(
                        f"Skipping RSS fetch: previous fetch still running ({elapsed:.1f}s elapsed)"
                    )
                    return None
                self._rss_future = None
                self._rss_future_started_at = None
            future = self._rss_executor.submit(
                feedparser.parse,
                feed_url,
                request_headers=headers,
            )
            self._rss_future = future
            self._rss_future_started_at = time.monotonic()
            try:
                feed = future.result(timeout=30)
            except concurrent.futures.TimeoutError:
                cancel_success = future.cancel()
                self.logger.warning("RSS feed fetch timed out after 30 seconds")
                self.logger.info(f"RSS fetch future cancelled: {cancel_success}")
                return None
            finally:
                if future.done():
                    self._rss_future = None
                    self._rss_future_started_at = None
            # Check HTTP status first (feedparser stores it in feed.status)
            http_status = getattr(feed, "status", None)
            if http_status == 429:
                self.logger.warning(
                    "RSS rate limited (HTTP 429). Gengo limits requests to once per 60s. "
                    "Consider increasing check_interval in config."
                )
                return None
            if http_status and http_status >= 400:
                self.logger.error(f"RSS HTTP Error: {http_status}")
                return None

            if feed.bozo:
                # Check if it's a parsing error due to HTML response (rate limit page)
                exc_str = str(feed.bozo_exception).lower()
                if "mismatched tag" in exc_str or "not well-formed" in exc_str:
                    # Likely an HTML error page instead of RSS/XML
                    self.logger.warning(
                        "RSS feed returned invalid XML (likely rate-limited or error page). "
                        "Will retry after backoff."
                    )
                else:
                    self.logger.error(f"Feed Parse Error: {feed.bozo_exception}")
                return None
            self.logger.debug(
                f"RSS feed fetched successfully. Entries: {len(feed.entries)}"
            )
            return feed
        except Exception as e:
            self.logger.error(f"RSS Error: {e}")
            return None

    async def _websocket_logic(self):
        """
        Manage a single WebSocket connection: establish, authenticate, maintain heartbeat, receive events and handle clean disconnects.

        Establishes a connection to the configured WebSocket URL, sends authentication payload (user/session and optional key), and updates connection state. Maintains a periodic heartbeat to measure latency and detect stalls, monitors for manual test commands, and listens for incoming messages; when an "available_collection" event is received it extracts job details and delegates handling to the watcher. Records socket close codes and reasons, performs a retry without custom headers when handshakes fail due to header restrictions, and sets websocket_status to reflect connection state or offline on failure.
        """
        ws_url = (
            self.config.get("WebSocket", "wss_url") or "wss://live-dashboard.gengo.com/"
        )
        self.websocket_status = "Connecting"
        self.logger.info(f"WebSocket: Initializing connection to {ws_url}")

        try:
            if not await asyncio.to_thread(self._sync_session_before_websocket_connect):
                return
            # Determine User-Agent
            user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
            custom_ua = self.config.get("Network", "browser_user_agent")
            accept_language = (
                self.config.get("Network", "browser_accept_language")
                or "en-GB,en-US;q=0.9,en;q=0.8"
            )
            if custom_ua:
                user_agent = custom_ua
                self.logger.info(
                    f"WebSocket: Using configured browser User-Agent: {user_agent[:30]}..."
                )
            else:
                self.logger.debug(
                    f"WebSocket: Using default User-Agent: {user_agent[:30]}..."
                )

            session_token = self.config.get("WebSocket", "user_session")
            user_key = self.config.get("WebSocket", "user_key")
            masked_token = (
                f"{session_token[:4]}...{session_token[-4:]}"
                if session_token and len(session_token) > 8
                else "NOT_SET"
            )
            additional_headers = build_browser_aligned_websocket_headers(
                session_token=session_token,
                user_agent=user_agent,
                origin="https://gengo.com",
                accept_language=accept_language,
            )
            ua_only_headers = {"User-Agent": user_agent} if user_agent else None

            # Log headers (masking sensitive info)
            safe_headers = []
            for k, v in additional_headers.items():
                if k == "Cookie":
                    safe_headers.append((k, f"my_gengo_session={masked_token}"))
                else:
                    safe_headers.append((k, v))
            self.logger.debug(f"WebSocket: Preparing headers: {safe_headers}")

            async def run_session(headers):
                """
                Run a single WebSocket session: connect, authenticate, monitor heartbeat and test commands, and process incoming messages.

                Parameters:
                    headers (dict | None): Optional additional HTTP headers to include in the WebSocket handshake; pass None to omit custom headers.

                Detailed behaviour:
                    - Connects to the configured WebSocket URL and sends an authentication payload containing the configured `user_id` and stored session token.
                    - Starts a heartbeat task that measures ping/pong latency and updates connection timing/state attributes.
                    - Starts a test-monitor task that responds to manual UI test commands (e.g. ping, notify).
                    - Listens for incoming messages and invokes the watcher's message handling for recognised events (notably `available_collection` events, which are forwarded to `_process_new_job`).
                    - Records the socket close code and reason on disconnect, cancels auxiliary tasks and performs orderly cleanup while logging notable conditions and errors.
                """
                header_desc = (
                    "with custom headers" if headers else "with no custom headers"
                )
                messages_received = False
                self.websocket_status = "Connecting"
                self.websocket_connected_at_ts = None
                self.websocket_last_message_ts = None
                self.websocket_last_pong_ts = None
                self.websocket_ping_latency_ms = None
                self.websocket_next_ping_ts = None
                self._next_quiet_socket_sync_ts = None
                self.logger.debug(
                    f"WebSocket: Attempting connection to {ws_url} ({header_desc})"
                )
                async with websockets.connect(  # type: ignore
                    ws_url,
                    additional_headers=headers,
                    open_timeout=20,
                    ping_interval=20,
                    ping_timeout=10,
                ) as websocket:
                    connected_at = time.time()
                    self.websocket_connected_at_ts = connected_at
                    self.websocket_status = "Authenticating"
                    user_id = self.config.get("WebSocket", "user_id")

                    auth_payload = build_websocket_auth_payload(
                        user_id=user_id,
                        session_token=session_token,
                    )
                    self.logger.debug(
                        "WebSocket: Sending auth payload for user_id=%s",
                        user_id,
                    )

                    auth_json = json.dumps(auth_payload)
                    self._capture_raw_ws_message(auth_json, direction="send")
                    await websocket.send(auth_json)

                    self.websocket_status = "Live"
                    self.logger.info(
                        "WebSocket: Connection established and authenticated."
                    )

                    sync_fail_hard = self.config.getboolean(
                        "WebSocket", "session_sync_fail_hard", fallback=True
                    )
                    sync_alert_on_failure = self.config.getboolean(
                        "WebSocket",
                        "session_sync_alert_on_failure",
                        fallback=True,
                    )
                    debug_url = self.config.get("WebSocket", "browser_debug_url")

                    # Heartbeat task: send periodic ping to measure latency and expose countdown to UI
                    HEARTBEAT_INTERVAL = 25  # seconds

                    async def heartbeat():
                        """
                        Periodically sends WebSocket pings to measure connectivity and update heartbeat metrics.

                        This coroutine runs an infinite loop that sends a ping at the configured heartbeat interval, measures round-trip latency, and updates the instance attributes used for uptime/diagnostics (next scheduled ping timestamp, last pong timestamp and last measured ping latency in milliseconds). It will propagate asyncio.CancelledError when cancelled; other exceptions are caught and logged so the outer connection loop can handle disconnects.
                        """
                        while True:
                            try:
                                self.websocket_next_ping_ts = (
                                    time.time() + HEARTBEAT_INTERVAL
                                )
                                await asyncio.sleep(HEARTBEAT_INTERVAL)
                                t0 = time.perf_counter()
                                self.logger.debug(
                                    "WebSocket: Sending heartbeat ping..."
                                )
                                self._capture_raw_ws_message("PING", direction="send")
                                waiter = await websocket.ping()
                                await asyncio.wait_for(waiter, timeout=5)
                                self._capture_raw_ws_message("PONG", direction="recv")
                                latency = (time.perf_counter() - t0) * 1000.0
                                pong_received_at = time.time()
                                self.websocket_last_pong_ts = pong_received_at
                                self.websocket_ping_latency_ms = latency
                                self.logger.debug(
                                    f"WebSocket: Heartbeat pong received. Latency: {latency:.2f}ms"
                                )
                                changed = await asyncio.to_thread(
                                    self._sync_browser_session_for_quiet_socket,
                                    current_time=pong_received_at,
                                    fail_hard=sync_fail_hard,
                                    alert_on_failure=sync_alert_on_failure,
                                )
                                if self._websocket_sync_failed:
                                    self.logger.error(
                                        "WebSocket: Quiet-socket browser session sync"
                                        " failed; closing realtime connection immediately."
                                    )
                                    await websocket.close(
                                        code=4002,
                                        reason="browser session sync failed",
                                    )
                                    return
                                if changed:
                                    self._websocket_session_refresh_requested = True
                                    self.logger.warning(
                                        "WebSocket: Quiet-socket browser session refresh"
                                        " requested; reconnecting now."
                                    )
                                    await websocket.close(
                                        code=4001,
                                        reason="browser session token refreshed",
                                    )
                                    return
                            except asyncio.CancelledError:
                                raise
                            except Exception as e:
                                # Log and continue; the main loop will handle real disconnects
                                self.logger.warning(f"WebSocket: Heartbeat failed: {e}")

                    heartbeat_task = asyncio.create_task(heartbeat())

                    session_refresh_task = None
                    sync_interval = self._get_session_sync_interval_seconds()

                    if debug_url and sync_interval > 0:

                        async def refresh_session_token_periodically():
                            while True:
                                await asyncio.sleep(sync_interval)
                                changed = await asyncio.to_thread(
                                    self._sync_session_from_browser,
                                    fail_hard=sync_fail_hard,
                                    alert_on_failure=sync_alert_on_failure,
                                )
                                if self._websocket_sync_failed:
                                    self.logger.error(
                                        "WebSocket: Browser session sync failed; closing realtime connection immediately."
                                    )
                                    await websocket.close(
                                        code=4002,
                                        reason="browser session sync failed",
                                    )
                                    return
                                if changed:
                                    self._websocket_session_refresh_requested = True
                                    self.logger.warning(
                                        "WebSocket: Session token refreshed from browser; reconnecting now."
                                    )
                                    await websocket.close(
                                        code=4001,
                                        reason="browser session token refreshed",
                                    )
                                    return

                        session_refresh_task = asyncio.create_task(
                            refresh_session_token_periodically()
                        )

                    try:
                        self.logger.debug("WebSocket: Waiting for first message...")
                        first_message = await asyncio.wait_for(
                            websocket.recv(), timeout=5
                        )
                        messages_received = True
                        self.websocket_last_message_ts = time.time()
                        self.logger.debug(
                            f"WebSocket: First message received: {first_message[:100]}..."
                        )
                        # Capture raw message
                        self._capture_raw_ws_message(first_message, direction="recv")
                        try:
                            data = json.loads(first_message)
                            self.logger.debug(
                                f"WebSocket: First message type: {data.get('type', 'unknown')}"
                            )
                        except Exception as e:
                            self.logger.warning(
                                f"WebSocket: Could not parse first message as JSON: {e}. Raw: {first_message[:100]}..."
                            )
                    except asyncio.TimeoutError:
                        self.logger.debug(
                            "WebSocket: No message received immediately after authentication (this is normal)."
                        )
                        self._capture_raw_ws_message(
                            "TIMEOUT: No initial message from server", direction="recv"
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"WebSocket: Error receiving first message: {e}"
                        )

                    async def monitor_test_request():
                        """
                        Monitor the UI for manual test commands and execute the corresponding test actions.

                        This coroutine runs continuously until cancelled. When a pending test command is detected it:
                        - Executes "ping": sends a WebSocket ping, awaits a pong and logs success or timeout/failure.
                        - Executes "notify": triggers a simulated new-job notification via _simulate_new_job_notification().

                        No parameters or return value.
                        """
                        self.logger.debug("WebSocket: Test command monitor started.")
                        while True:
                            command = None
                            with self._test_command_lock:
                                if self._test_command:
                                    command = self._test_command
                                    self._test_command = None
                            if command == "ping":
                                self.logger.info(
                                    "WebSocket: PING test initiated by user."
                                )
                                try:
                                    self._capture_raw_ws_message(
                                        "PING (Manual)", direction="send"
                                    )
                                    pong_waiter = await websocket.ping()
                                    await asyncio.wait_for(pong_waiter, timeout=5)
                                    self._capture_raw_ws_message(
                                        "PONG (Manual)", direction="recv"
                                    )
                                    self.logger.info(
                                        "[bold green]WebSocket: PING test successful. Connection is live.[/bold green]"
                                    )
                                except asyncio.TimeoutError:
                                    self.logger.warning(
                                        "[bold red]WebSocket: PING test failed (timeout). Connection may be stalled.[/bold red]"
                                    )
                                except Exception as e:
                                    self.logger.error(
                                        f"WebSocket: PING test failed: {e}"
                                    )
                            elif command == "notify":
                                self._simulate_new_job_notification()
                            await asyncio.sleep(0.2)

                    test_monitor_task = asyncio.create_task(monitor_test_request())
                    try:
                        async for message in websocket:
                            messages_received = True
                            self.websocket_last_message_ts = time.time()
                            self.logger.debug(
                                f"WebSocket: Message received (len={len(message)})"
                            )
                            # Capture raw message for debug output
                            self._capture_raw_ws_message(message, direction="recv")

                            data = None
                            try:
                                data = json.loads(message)
                            except Exception as e:
                                self.logger.warning(
                                    f"WebSocket: Could not parse message as JSON: {e}"
                                )
                                continue

                            if isinstance(data, dict):
                                msg_type = data.get("type")
                                if msg_type == "available_collection":
                                    job = data.get("collection", {})
                                    job_id = job.get("id")
                                    self.logger.info(
                                        f"WebSocket: 'available_collection' event for job ID {job_id}"
                                    )
                                    if job_id:
                                        reward = float(job.get("rewards", 0.0))
                                        title = (
                                            f"{job.get('lc_src')} > {job.get('lc_tgt')}"
                                        )
                                        url = (
                                            f"https://gengo.com/t/jobs/details/{job_id}"
                                        )
                                        self._process_new_job(
                                            job_id,
                                            title,
                                            reward,
                                            url,
                                            source="WebSocket",
                                            source_meta=job,
                                        )
                                else:
                                    self.logger.debug(
                                        f"WebSocket: Ignoring message type '{msg_type}'"
                                    )
                            else:
                                self.logger.debug(
                                    f"WebSocket: Ignoring non-dict message: {str(data)[:50]}..."
                                )

                    except ConnectionClosed as e:
                        self.websocket_last_close_code = getattr(e, "code", None)
                        self.websocket_last_close_reason = getattr(e, "reason", None)
                        log_method = (
                            self.logger.info
                            if getattr(e, "code", None) == 1000
                            else self.logger.warning
                        )
                        log_method(
                            f"WebSocket: Disconnected by server: code={getattr(e, 'code', None)}, reason={getattr(e, 'reason', None)}"
                        )
                    except Exception as e:
                        self.logger.error(f"WebSocket: Error in main message loop: {e}")
                    finally:
                        test_monitor_task.cancel()
                        heartbeat_task.cancel()
                        if session_refresh_task is not None:
                            session_refresh_task.cancel()
                        try:
                            await test_monitor_task
                            await heartbeat_task
                            if session_refresh_task is not None:
                                await session_refresh_task
                        except asyncio.CancelledError:
                            self.logger.debug(
                                "WebSocket: Auxiliary tasks cancelled cleanly."
                            )
                        except Exception as e:
                            self.logger.warning(
                                f"WebSocket: Exception while awaiting tasks cleanup: {e}"
                            )
                    if hasattr(websocket, "close_code") or hasattr(
                        websocket, "close_reason"
                    ):
                        close_code = getattr(websocket, "close_code", None)
                        close_reason = getattr(websocket, "close_reason", None)
                        self.websocket_last_close_code = close_code
                        self.websocket_last_close_reason = close_reason
                        connection_age = time.time() - connected_at
                        self.logger.info(
                            f"WebSocket: Socket Closed: code={close_code}, reason={close_reason}"
                        )
                        if (
                            close_code in (1000, 1001)
                            and not messages_received
                            and connection_age < 20
                        ):
                            self.logger.warning(
                                "WebSocket closed cleanly %.1fs after auth with no messages. "
                                "This can indicate session/auth mismatch or server-side filtering.",
                                connection_age,
                            )
                    self.websocket_connected_at_ts = None
                    self.websocket_next_ping_ts = None

            header_profiles = [
                ("browser-aligned headers", additional_headers),
                ("user-agent only headers", ua_only_headers),
                ("no custom headers", None),
            ]
            last_error = None
            for index, (profile_name, headers) in enumerate(header_profiles):
                if headers is None and index == 1 and ua_only_headers is None:
                    continue
                try:
                    if index > 0:
                        self.logger.warning(
                            "WebSocket: Retrying handshake with %s.",
                            profile_name,
                        )
                    await run_session(headers)
                    last_error = None
                    break
                except (InvalidStatusCode, InvalidHandshake, TimeoutError) as e:
                    last_error = e
                    if index == len(header_profiles) - 1:
                        raise
                    self.logger.warning(
                        "WebSocket handshake failed using %s: %s",
                        profile_name,
                        e,
                    )
            if last_error is not None:
                raise last_error
        except (
            ConnectionClosed,
            InvalidStatusCode,
            InvalidHandshake,
            ConnectionRefusedError,
        ) as e:
            code = getattr(e, "code", None)
            reason = getattr(e, "reason", None)
            self.logger.warning(
                f"WebSocket: Connection failed: code={code}, reason={reason}, error={e}"
            )
            self.websocket_status = "Offline"
        except TimeoutError as e:
            self.logger.warning(
                f"WebSocket: Connection timed out during handshake/open: {e}"
            )
            self.websocket_status = "Offline"
        except Exception as e:
            self.logger.error(f"WebSocket: Unexpected error: {e}", exc_info=True)
            self.websocket_status = "Offline"

    def _run_websocket_monitor(self):
        """
        Manage the persistent WebSocket connection lifecycle, including configuration validation, connection attempts, reconnection with exponential backoff, and orderly shutdown.

        On each loop iteration this method:
        - Verifies required WebSocket credentials are configured; if missing, marks the WebSocket as disabled and waits for shutdown.
        - Runs the asynchronous connection logic and records the last close code and reason.
        - Distinguishes clean closes (codes 1000/1001) from abnormal closes and applies exponential backoff (bounded by the configured `Network.max_backoff`) before reconnecting.
        - Observes `shutdown_event` to exit promptly and updates `websocket_status` to reflect current state.

        This method does not return a value.
        """
        self.logger.debug("Starting WebSocket monitor thread.")
        # Exponential backoff on reconnect to avoid hammering server
        base_backoff = 5
        backoff = base_backoff
        max_backoff = int(self.config.get("Network", "max_backoff"))
        clean_close_backoff_min = self.config.getint(
            "Network", "clean_close_backoff_min", fallback=20
        )
        clean_close_backoff_max = self.config.getint(
            "Network", "clean_close_backoff_max", fallback=45
        )
        reconnect_jitter_max = self.config.getint(
            "Network", "reconnect_jitter_max", fallback=5
        )
        session_placeholder = "REPLACE_WITH_YOUR_SESSION_TOKEN"
        key_placeholder = "REPLACE_WITH_YOUR_USER_KEY"
        while not self.shutdown_event.is_set():
            self._websocket_session_refresh_requested = False
            self._websocket_sync_failed = False
            self._websocket_sync_failure_reason = None

            debug_url = self.config.get("WebSocket", "browser_debug_url")
            if debug_url:
                self._sync_session_from_browser(
                    fail_hard=self.config.getboolean(
                        "WebSocket", "session_sync_fail_hard", fallback=True
                    ),
                    alert_on_failure=self.config.getboolean(
                        "WebSocket",
                        "session_sync_alert_on_failure",
                        fallback=True,
                    ),
                )
                if self._websocket_sync_failed:
                    self.logger.error(
                        "WebSocket monitor stopped after browser session sync failure: %s",
                        self._websocket_sync_failure_reason,
                    )
                    self.websocket_status = "Session Sync Failed"
                    break

            session_token = self.config.get("WebSocket", "user_session")
            user_key = self.config.get("WebSocket", "user_key")

            # Validate session token (required)
            if not session_token or session_token == session_placeholder:
                self.logger.warning(
                    "WebSocket disabled: Please set 'user_session' in config.toml."
                )
                self.websocket_status = "Disabled"
                self.shutdown_event.wait()
                break

            # Validate user_key (optional but recommended)
            if user_key == key_placeholder:
                self.logger.info(
                    "WebSocket: user_key is set to placeholder value. "
                    "Authentication will rely only on session token."
                )

            try:
                self.logger.debug("Running websocket logic (asyncio.run)")
                self.websocket_last_close_code = None
                self.websocket_last_close_reason = None
                session_started_at = time.time()
                asyncio.run(self._websocket_logic())
                session_duration = time.time() - session_started_at
                if self.shutdown_event.is_set():
                    break
                if self.websocket_status != "Disabled":
                    self.websocket_reconnect_count += 1
                if self._websocket_sync_failed:
                    self.logger.error(
                        "WebSocket monitor stopped after browser session sync failure: %s",
                        self._websocket_sync_failure_reason,
                    )
                    self.websocket_status = "Session Sync Failed"
                    break
                if self._websocket_session_refresh_requested:
                    self.logger.info(
                        "WebSocket: Reconnecting immediately after browser session refresh."
                    )
                    backoff = base_backoff
                    continue
                self.websocket_status = "Offline"
                close_code = self.websocket_last_close_code
                close_reason = self.websocket_last_close_reason
                normal_close = close_code in (1000, 1001)
                if normal_close:
                    wait_time = min(
                        max_backoff,
                        random.uniform(
                            clean_close_backoff_min, clean_close_backoff_max
                        ),
                    )
                    # If we churn quickly, extend the delay to avoid hammering the endpoint.
                    if session_duration < 10:
                        wait_time = max(wait_time, clean_close_backoff_max)
                        self.logger.warning(
                            "WebSocket connection closed cleanly after %.1fs. "
                            "Backing off to %.1fs before reconnecting.",
                            session_duration,
                            wait_time,
                        )
                    else:
                        self.logger.info(
                            "WebSocket connection closed cleanly (code=%s, reason=%s). "
                            "Reconnecting in %.1f seconds...",
                            close_code,
                            close_reason,
                            wait_time,
                        )
                    backoff = base_backoff
                else:
                    wait_time = min(
                        max_backoff, backoff + random.uniform(0, reconnect_jitter_max)
                    )
                    self.logger.info(
                        f"WebSocket connection closed. Reconnecting in {wait_time:.1f} seconds..."
                    )
                    backoff = min(backoff * 2, max_backoff)
                if self.shutdown_event.wait(wait_time):
                    break
            except Exception as e:
                self.logger.error(f"Critical error in WebSocket runner: {e}")
                wait_time = min(
                    max_backoff, backoff + random.uniform(0, reconnect_jitter_max)
                )
                if self.shutdown_event.wait(wait_time):
                    break
                backoff = min(backoff * 2, max_backoff)
        self.logger.info("WebSocket monitor thread stopped.")
        if not self._websocket_sync_failed:
            self.websocket_status = "Stopped"

    def run(self):
        self.logger.debug("Starting watcher parent thread.")
        self.logger.info("Watcher parent thread started. Launching monitors...")

        if self.browser_worker_enabled:
            browser_worker_thread = threading.Thread(
                target=self._run_browser_worker_event_listener,
                daemon=True,
                name="BrowserWorkerEventListener",
            )
            browser_worker_thread.start()
            self._monitor_threads["browser_worker"] = browser_worker_thread

        rss_thread = threading.Thread(target=self._run_rss_monitor, daemon=True)
        rss_thread.start()
        self._monitor_threads["rss"] = rss_thread

        # Check for gateway mode
        use_gateway = self.config.getboolean("WebSocket", "use_gateway", fallback=False)
        if use_gateway:
            gateway_url = self.config.get(
                "WebSocket", "gateway_url", fallback="http://127.0.0.1:8000"
            )
            self.websocket_status = "Gateway Connected"
            self.logger.info(f"WebSocket using external gateway at {gateway_url}")
        elif self.config.get("WebSocket", "enable_websocket"):
            ws_thread = threading.Thread(
                target=self._run_websocket_monitor, daemon=True
            )
            ws_thread.start()
            self._monitor_threads["websocket"] = ws_thread
            self.websocket_status = "Enabled"
        else:
            self.websocket_status = "Disabled"

        # Native Browser Listener (replaces WebsiteMonitor)
        use_native_browser = self.config.getboolean(
            "NativeBrowserListener", "enabled", fallback=False
        )
        if use_native_browser:
            from .native_browser_listener import NativeBrowserListener
            from .state_projector import StateProjector

            debug_url = self.config.get(
                "Browser", "debug_url", fallback="ws://127.0.0.1:6000"
            )
            maybe_launch_managed_firefox_debug(
                self.config,
                str(debug_url),
                logger=self.logger,
            )
            interval_ms = self.config.getint(
                "NativeBrowserListener", "capture_interval_ms", fallback=750
            )

            self._native_listener = NativeBrowserListener(
                debug_url=debug_url,
                capture_interval_ms=interval_ms,
            )
            self._state_projector = StateProjector(self.state, notifier=self)

            native_thread = threading.Thread(
                target=self._run_native_browser_listener, daemon=True
            )
            native_thread.start()
            self._monitor_threads["native_browser"] = native_thread
            self.native_browser_status = "Started"
            self.logger.info(
                "Native browser listener started (replaces WebsiteMonitor)"
            )
        else:
            self.native_browser_status = "Disabled"

        if self.config.get("EmailMonitor", "enabled"):
            email_thread = threading.Thread(target=self._run_email_monitor, daemon=True)
            email_thread.start()
            self._monitor_threads["email"] = email_thread
            self.logger.info("Email monitor thread started")

        if self.config.get("WebsiteMonitor", "enabled"):
            # HARD DISABLE: Cannot run with native browser backend
            backend = self.config.get("Browser", "backend", fallback="native")
            if backend == "native":
                self.logger.warning(
                    "WebsiteMonitor disabled - native browser mode requires "
                    "NativeBrowserListener"
                )
            else:
                # DEPRECATED: WebsiteMonitor is deprecated; use NativeBrowserListener
                self.logger.warning(
                    "WebsiteMonitor is deprecated; use NativeBrowserListener instead"
                )
                website_thread = threading.Thread(
                    target=self._run_website_monitor, daemon=True
                )
                website_thread.start()
                self._monitor_threads["website"] = website_thread
                self.logger.info("Website monitor thread started (deprecated)")

        if self._browser_jobs_monitor_enabled():
            browser_jobs_thread = threading.Thread(
                target=self._run_browser_jobs_monitor, daemon=True
            )
            browser_jobs_thread.start()
            self._monitor_threads["browser_jobs"] = browser_jobs_thread
            self.logger.info("Browser available-jobs monitor thread started")
        else:
            self.browser_jobs_monitor_status = "Disabled"

        self.shutdown_event.wait()
        self.logger.info("Watcher parent thread shutting down.")

    def _run_browser_jobs_monitor(self):
        self.logger.info("Browser available-jobs monitor thread started.")
        debug_url = str(self.config.get("WebSocket", "browser_debug_url", fallback=""))
        if not debug_url:
            self.browser_jobs_monitor_status = "Disabled"
            return

        allow_navigation = self._browser_jobs_navigation_enabled()
        if allow_navigation:
            self._open_in_managed_firefox_debug_session(GENGO_AVAILABLE_JOBS_URL)
        self.browser_jobs_monitor_status = "Starting"
        next_refresh_ts = time.time() + self._pick_browser_jobs_refresh_delay_seconds()
        next_browse_ts = time.time() + self._pick_browser_jobs_browse_delay_seconds()
        error_count = 0

        while not self.shutdown_event.is_set():
            try:
                now = time.time()
                force_refresh = allow_navigation and now >= next_refresh_ts
                browse_url = None
                if allow_navigation and now >= next_browse_ts:
                    browse_url = random.choice(GENGO_BROWSER_BROWSE_URLS)

                snapshot = inspect_available_jobs_page_sync(
                    debug_url,
                    force_refresh=force_refresh,
                    browse_url=browse_url,
                    interact=(
                        allow_navigation
                        and (
                            force_refresh
                            or bool(browse_url)
                            or self._browser_jobs_mouse_activity_enabled()
                        )
                    ),
                    allow_navigation=allow_navigation,
                )
                error_count = 0
                self.browser_jobs_last_check_time = time.time()
                self.browser_jobs_last_action = snapshot.action
                if snapshot.action == "manual_browse":
                    self.browser_jobs_monitor_status = "Paused: browser in manual use"
                else:
                    self.browser_jobs_monitor_status = "Watching"

                    processed = self._process_browser_jobs_snapshot(snapshot)
                    if processed:
                        self.browser_jobs_found_session += processed
                        self.logger.info(
                            "Browser available-jobs page reported %d candidate job(s).",
                            processed,
                        )

                    if force_refresh:
                        next_refresh_ts = (
                            time.time()
                            + self._pick_browser_jobs_refresh_delay_seconds()
                        )
                    if browse_url:
                        next_browse_ts = (
                            time.time() + self._pick_browser_jobs_browse_delay_seconds()
                        )
            except Exception as exc:
                error_count += 1
                self.browser_jobs_monitor_status = f"Error: {exc}"
                log_method = (
                    self.logger.warning if error_count == 1 else self.logger.debug
                )
                log_method(
                    "Browser available-jobs monitor check failed: %s",
                    exc,
                    exc_info=error_count == 1,
                )

            if self.shutdown_event.wait(self._get_browser_jobs_poll_interval_seconds()):
                break

        self.browser_jobs_monitor_status = "Stopped"
        self.logger.info("Browser available-jobs monitor thread stopped.")

    def _run_rss_monitor(self):
        self.logger.debug("Starting RSS monitor thread.")
        self.logger.info("RSS monitor thread started.")
        state_updated = False
        if not self.state.last_seen_rss_link:
            if self.state.last_seen_link:
                self.state.last_seen_rss_link = self.state.last_seen_link
                self.logger.debug(
                    "Migrated legacy last_seen_link value to last_seen_rss_link."
                )
                state_updated = True
            else:
                self.rss_action = "Priming feed"
                initial_feed = self.fetch_rss()
                if initial_feed and initial_feed.entries:
                    first_link = initial_feed.entries[0].get("link")
                    self.state.last_seen_rss_link = first_link
                    self.state.last_seen_link = first_link
                    self.logger.info("Initial RSS feed primed successfully.")
                    state_updated = True
        if state_updated:
            self.state.save_state()

        while not self.shutdown_event.is_set():
            is_paused = os.path.exists(self.PAUSE_FILE)
            time_to_next_check = self.next_check_time - time.time()
            wait_duration = max(0, time_to_next_check)
            self.logger.debug(
                f"Waiting for next RSS check: {wait_duration:.2f}s (paused={is_paused})"
            )

            triggered = self.check_now_event.wait(timeout=wait_duration)
            if self.shutdown_event.is_set():
                break

            if triggered or time.time() >= self.next_check_time:
                self.logger.debug("RSS check triggered.")
                self.check_now_event.clear()

                if os.path.exists(self.PAUSE_FILE):
                    self.rss_action = "Paused"
                    wait_time = 5
                else:
                    self.rss_action = "Fetching RSS"
                    feed = self.fetch_rss()
                    if feed is None:
                        self.failure_count += 1
                        wait_time = min(
                            self._pick_next_rss_wait_seconds()
                            * (2**self.failure_count),
                            self.config.get("Network", "max_backoff"),
                        )
                        self.rss_action = f"RSS Backoff ({int(wait_time)}s)"
                    else:
                        if self.failure_count > 0:
                            self.logger.info("RSS Connection re-established.")
                        self.failure_count = 0
                        self.last_check_time = datetime.datetime.now()
                        self.rss_action = "Processing RSS"
                        self._process_feed_entries(feed.entries)
                        wait_time = self._pick_next_rss_wait_seconds()
                        self.rss_action = "Waiting"
                self.next_check_time = time.time() + wait_time

        self.logger.info("RSS monitor thread stopped.")

    def _run_native_browser_listener(self):
        """Run native browser listener loop - drains events into state projector."""
        from queue import Empty

        self.logger.info("Native browser listener starting...")
        while not self.shutdown_event.is_set():
            try:
                # Poll native listener (publishes events)
                if hasattr(self, "_native_listener"):
                    self._native_listener.run_once()

                # Drain events into state projector
                if hasattr(self, "_state_projector"):
                    try:
                        from .event_bus import get_native_events_queue
                        from .events import EventEnvelope

                        q = get_native_events_queue()
                        while True:
                            try:
                                event_dict = q.get_nowait()
                                event = EventEnvelope.from_dict(event_dict)
                                self._state_projector.project(event)
                            except Empty:
                                break
                            except Exception as e:
                                self.logger.debug(f"Event projection error: {e}")
                    except Exception as e:
                        self.logger.debug(f"Event bus drain error: {e}")

            except Exception as e:
                self.logger.debug(f"Native browser listener error: {e}")
            capture_interval = (
                getattr(self, "_native_listener", None).capture_interval
                if hasattr(self, "_native_listener")
                and hasattr(getattr(self, "_native_listener", None), "capture_interval")
                else 0.75
            )
            time.sleep(capture_interval)

    def run_notify_test(self):
        self.logger.info("Sending a test notification...")
        self.show_notification(
            message="This is a test notification!",
            title="GengoWatcher Test",
            play_sound=True,
            open_link=True,
            url="https://gengo.com/t/jobs/status/available",
        )

    def pause_monitoring(self):
        """Pause RSS monitoring and wake the monitor so state updates immediately."""
        Path(self.PAUSE_FILE).write_text("", encoding="utf-8")
        self.rss_action = "Paused"
        self.check_now_event.set()
        self.logger.info("Watcher paused.")

    def resume_monitoring(self):
        """Resume RSS monitoring and wake the monitor so it re-checks promptly."""
        try:
            os.remove(self.PAUSE_FILE)
        except FileNotFoundError:
            pass
        self.rss_action = "Resume requested"
        self.check_now_event.set()
        self.logger.info("Watcher resumed.")

    def queue_websocket_test_command(self, command: str):
        """Queue a diagnostic command for the websocket monitor task."""
        with self._test_command_lock:
            self._test_command = command
        self.logger.info("WebSocket %s test queued.", command)

    def restart(self):
        self.handle_exit()
        python = sys.executable
        os.execv(python, [python] + sys.argv)

    def set_config_value(self, section, option, value):
        self.logger.debug(f"Setting config value: [{section}] {option} = {value}")
        self.config.set(section, option, value)
        self.config.save_config()
        self.logger.info(f"Config updated: [{section}] {option} = {value}")
        if section.lower() == "cancellation":
            self._configure_cancellation_manager()

    def get_config_value(self, section, option):
        value = self.config.get(section, option)
        self.logger.debug(f"Getting config value: [{section}] {option} = {value}")
        return value

    def list_config_values(self):
        config_dict = self.config.list_all()
        if not isinstance(config_dict, dict):
            fallback_config = getattr(self.config, "config", None)
            config_dict = fallback_config if isinstance(fallback_config, dict) else {}
        self.logger.debug(
            "Listing all config values: %s",
            _redact_config_for_log(config_dict),
        )
        return config_dict

    def get_cancellation_stats(self):
        """Expose cancellation statistics for external callers."""
        try:
            return self.cancellation_manager.get_stats()
        except Exception as e:
            self.logger.error(f"Failed to gather cancellation stats: {e}")
            return None

    async def cancel_current_job_async(self) -> bool:
        """Asynchronously cancel the currently tracked job."""
        return await self.cancellation_manager.cancel_current_job()

    def cancel_current_job_sync(self) -> bool:
        """Synchronously cancel the currently tracked job."""
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(
                self.cancellation_manager.cancel_current_job()
            )
        finally:
            loop.close()

    def _configure_cancellation_manager(self):
        """Apply configuration settings to the cancellation manager."""
        try:
            settings = {
                "cancellation_enabled": self.cancellation_manager._config_getboolean(
                    "Cancellation", "enabled", fallback=False
                ),
                "min_improvement_ratio": self.cancellation_manager._config_getfloat(
                    "Cancellation", "min_improvement_ratio", fallback=2.0
                ),
                "extreme_threshold": self.cancellation_manager._config_getfloat(
                    "Cancellation", "extreme_threshold", fallback=1000.0
                ),
            }
            self.cancellation_manager.update_settings(**settings)
        except Exception as e:
            self.logger.error(f"Failed to configure cancellation manager: {e}")

    def prompt_for_config_values(self, required_fields=None):
        """
        Interactively prompt the user to supply missing configuration values.

        If `required_fields` is not provided, the method scans the current configuration for values that match
        module-level placeholder markers and prompts for each missing item. For a fresh or small config file a
        welcome message is printed. Prompts are grouped by section and sensitive fields (containing "password",
        "session" or "key") are read without echo. Provided values are saved via set_config_value; skipped entries
        leave existing values unchanged. Progress and completion messages are printed and the action is logged.

        Parameters:
            required_fields (iterable[(str, str)], optional): Iterable of (section, option) pairs to prompt.
                If omitted or None, missing values are auto-detected from placeholder constants.
        """
        import getpass

        self.logger.debug("Prompting for config values interactively.")

        # Check if this is a fresh config
        config_file = Path(self.config.CONFIG_FILE)
        is_new_config = (
            config_file.stat().st_size < 1000
        )  # Rough check for new/small config

        if is_new_config:
            print("\n" + "=" * 60)
            print("🎉 Welcome to GengoWatcher!")
            print("=" * 60)
            print("A default configuration file has been created.")
            print("Let's set up the essential settings to get you started.")
            print("=" * 60 + "\n")

        if required_fields is None:
            required_fields = [
                field
                for field in self._get_default_required_config_fields()
                if self.config.get(field[0], field[1]) in PLACEHOLDER_CONFIG_VALUES
            ]

        if not required_fields:
            print("✅ All configuration values are set!")
            return

        print(
            f"\n📝 Please provide values for {len(required_fields)} required configuration settings:"
        )
        print("-" * 60)

        # Group fields by section for better organization
        fields_by_section = {}
        for section, option in required_fields:
            if section not in fields_by_section:
                fields_by_section[section] = []
            fields_by_section[section].append(option)

        for section, options in fields_by_section.items():
            print(f"\n[{section}] Section:")
            for option in options:
                current = self.config.get(section, option)
                display_current = (
                    current if current not in PLACEHOLDER_CONFIG_VALUES else "(not set)"
                )

                # Provide helpful descriptions for common fields
                descriptions = {
                    "user_session": "Your Gengo session token (found in browser dev tools)",
                    "user_id": "Your Gengo user ID number",
                    "feed_url": "RSS feed URL for job monitoring",
                    "min_reward": "Minimum job reward to monitor (USD)",
                    "check_interval": "How often to check for new jobs (seconds)",
                    "api_key": "CAPTCHA service API key",
                    "browser_path": "Path to your preferred browser executable",
                }

                desc = descriptions.get(option, "")
                desc_text = f" - {desc}" if desc else ""

                prompt = f"  {option} (current: {display_current}){desc_text}: "

                is_sensitive = any(
                    keyword in option.lower() for keyword in SENSITIVE_KEYWORDS
                )

                if is_sensitive:
                    value = getpass.getpass(prompt)
                else:
                    value = input(prompt).strip()

                if value:
                    self.set_config_value(section, option, value)
                    if is_sensitive:
                        print(f"  ✅ Set {option} (value stored securely)")
                    else:
                        print(f"  ✅ Set {option} = {value}")
                else:
                    print(f"  ⚠️  Skipped {option} (keeping current value)")

        print("\n" + "=" * 60)
        print("✅ Configuration setup complete!")
        print(
            "You can always reconfigure later with: python -m gengowatcher.main --configure"
        )
        print("=" * 60 + "\n")

        self.logger.info("Config interactive prompt complete.")

    def is_config_complete(self, required_fields=None):
        """
        Determine whether required configuration fields are set to non-placeholder values.

        If `required_fields` is omitted, every section/option present in the loaded config is validated against the module's placeholder sentinel values.

        Parameters:
            required_fields (list[tuple[str, str]]|None): Optional iterable of (section, option) pairs to validate. If `None`, all loaded config options are checked.

        Returns:
            bool: `True` if all specified fields are set to values other than the placeholder sentinels, `False` otherwise.
        """
        self.logger.debug("Checking if config is complete.")
        if required_fields is None:
            required_fields = self._get_default_required_config_fields()

        for section, option in required_fields:
            try:
                val = self.config.get(section, option)
                if val in PLACEHOLDER_CONFIG_VALUES:
                    self.logger.debug(
                        f"Config incomplete: [{section}] {option} is unset or placeholder."
                    )
                    return False
            except KeyError:
                # Section or option doesn't exist in loaded config
                self.logger.debug(
                    f"Config incomplete: [{section}] {option} is missing from loaded config."
                )
                return False

        return True

    def get_job_acceptance_stats(self):
        """Get job acceptance engine statistics"""
        if hasattr(self, "job_acceptance_engine"):
            return self.job_acceptance_engine.get_stats()
        else:
            return {
                "accepted_jobs": 0,
                "failed_acceptances": 0,
                "rate_limited": 0,
                "current_rate": 0.0,
                "enabled": False,
            }

    def _simulate_new_job_notification(self):
        """Injects a fake job into the processing pipeline to test notifications."""
        self.logger.info("Simulating a new job notification...")
        fake_job_id = int(time.time())
        fake_title = "TEST JOB: English > Japanese"
        fake_reward = 12.34
        fake_url = f"https://gengo.com/t/jobs/details/{fake_job_id}"
        self._process_new_job(
            fake_job_id, fake_title, fake_reward, fake_url, source="Test Simulation"
        )
        self.logger.info(
            "[bold green]Test job notification sent. Please check your system notifications.[/bold green]"
        )

    def handle_exit(self):
        """Handle application exit"""
        if getattr(self, "_shutdown_initiated", False):
            return

        self._shutdown_initiated = True
        self.logger.info("GengoWatcher shutting down...")
        self.shutdown_event.set()
        self.check_now_event.set()

        def _run_coro_safely(coro, description):
            try:
                loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(coro)
                finally:
                    asyncio.set_event_loop(None)
                    loop.close()
            except Exception as error:
                self.logger.exception(
                    "Failed to %s during shutdown: %s", description, error
                )

        if getattr(self, "job_acceptance_engine", None) and hasattr(
            self.job_acceptance_engine, "close_session"
        ):
            _run_coro_safely(
                self.job_acceptance_engine.close_session(),
                "close job acceptance session",
            )

        if getattr(self, "cancellation_manager", None) and hasattr(
            self.cancellation_manager, "close_session"
        ):
            _run_coro_safely(
                self.cancellation_manager.close_session(),
                "close cancellation session",
            )

        if self._all_entries_log_file:
            try:
                self._all_entries_log_file.flush()
                self._all_entries_log_file.close()
            except Exception as error:
                self.logger.exception("Failed to close CSV log file: %s", error)
            finally:
                self._all_entries_log_file = None
                self._csv_writer = None
        if self._rss_executor is not None:
            try:
                self._rss_executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                self._rss_executor.shutdown(wait=False)
            self._rss_executor = None
        self._rss_future = None
        self._rss_future_started_at = None

        try:
            self.state.save_state()
        except Exception as error:
            self.logger.exception("Failed to save state during shutdown: %s", error)

        self.logger.info("GengoWatcher shutdown complete")

    def _run_email_monitor(self):
        """Run email monitor in a dedicated thread with its own event loop."""
        if EmailMonitor is None:
            self.logger.error("Email monitor dependencies not installed")
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def job_callback(job_id, title, reward, url, source):
            await asyncio.to_thread(
                self._process_new_job, job_id, title, reward, url, source
            )

        self.email_monitor = EmailMonitor(
            config=self.config,
            logger=self.logger,
            job_callback=job_callback,
            shutdown_event=asyncio.Event(),
        )

        def check_shutdown():
            while not self.shutdown_event.is_set():
                time.sleep(1)
            if self.email_monitor:
                loop.call_soon_threadsafe(self.email_monitor.shutdown_event.set)

        shutdown_thread = threading.Thread(target=check_shutdown, daemon=True)
        shutdown_thread.start()

        try:
            loop.run_until_complete(self.email_monitor.start())
        except Exception as e:
            self.logger.error(f"Email monitor error: {e}")
        finally:
            loop.close()

    def _run_website_monitor(self):
        """Run website monitor in a dedicated thread with its own event loop."""
        if WebsiteMonitor is None:
            self.logger.error("Website monitor dependencies not installed (playwright)")
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def job_callback(job_id, title, reward, url, source):
            await asyncio.to_thread(
                self._process_new_job, job_id, title, reward, url, source
            )

        self.website_monitor = WebsiteMonitor(
            config=self.config,
            logger=self.logger,
            job_callback=job_callback,
            shutdown_event=asyncio.Event(),
        )

        def check_shutdown():
            while not self.shutdown_event.is_set():
                time.sleep(1)
            if self.website_monitor:
                loop.call_soon_threadsafe(self.website_monitor.shutdown_event.set)

        shutdown_thread = threading.Thread(target=check_shutdown, daemon=True)
        shutdown_thread.start()

        try:
            loop.run_until_complete(self.website_monitor.start())
        except Exception as e:
            self.logger.error(f"Website monitor error: {e}")
        finally:
            loop.close()
