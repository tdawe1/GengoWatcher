__version__ = "2.9.3"
__release_date__ = "2026-07-08"

import asyncio
import logging
import os
import random
import sys
import threading
import time
from typing import Any, Callable, Optional
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

import websockets

import subprocess  # noqa: F401  -- still patched by tests via watcher.subprocess
import webbrowser  # noqa: F401  -- still patched by tests via watcher.webbrowser
import feedparser  # noqa: F401  -- still patched by tests via watcher.feedparser

from .browser_session import (
    fetch_browser_session_snapshot_sync,  # noqa: F401  -- still patched by tests via watcher.<name>
    open_url_in_browser_debug_sync,  # noqa: F401  -- still patched by tests via watcher.<name>
    refresh_browser_page_activity_sync,
)
from .browser_debug_launcher import (  # noqa: F401  -- re-exported for tests / watcher_firefox.py
    get_firefox_debug_launch_spec,
    get_firefox_debug_retry_window,
    maybe_launch_managed_firefox_debug,
)
from .orchestration.watcher_firefox import open_in_managed_firefox_debug_session
from .orchestration.watcher_browser_jobs import (
    run_browser_jobs_monitor,
    trigger_browser_jobs_refresh as _bj_trigger,
)
from .orchestration.watcher_feed import (
    extract_reward as _extract_reward_impl,
    log_all_entries as _log_all_entries_impl,
    process_feed_entries as _process_feed_entries_impl,
    run_rss_monitor as _run_rss_monitor_impl,
)
from .orchestration.watcher_job_processor import (
    process_new_job as _process_new_job_impl,
    async_job_acceptance_wrapper as _async_job_acceptance_wrapper_impl,
    async_cancel_current_job_wrapper as _async_cancel_current_job_wrapper_impl,
    submit_job_to_translation_app_async as _submit_job_to_translation_app_async_impl,
)
from .orchestration.watcher_ws_debug import (
    capture_raw_ws_message as _capture_raw_ws_message_impl,
    get_raw_ws_messages as _get_raw_ws_messages_impl,
    clear_raw_ws_messages as _clear_raw_ws_messages_impl,
    handle_browser_worker_telemetry_line as _handle_telemetry_line_impl,
    handle_browser_worker_telemetry_payload as _handle_telemetry_payload_impl,
)

from .orchestration.watcher_ws_monitor import run_websocket_monitor as _run_websocket_monitor_impl
from .orchestration.watcher_ws_logic import websocket_logic as _websocket_logic_impl
from .orchestration.watcher_session_sync import (
    sync_session_from_browser as _sync_session_from_browser_impl,
    sync_session_before_websocket_connect as _sync_session_before_websocket_connect_impl,
)

from .orchestration.watcher_config_io import (
    set_config_value as _set_config_value_impl,
    get_config_value as _get_config_value_impl,
    prompt_for_config_values as _prompt_for_config_values_impl,
    is_config_complete as _is_config_complete_impl,
)

from .orchestration.watcher_monitors import (
    run_email_monitor as _run_email_monitor_impl,
    run_website_monitor as _run_website_monitor_impl,
    run_native_browser_listener as _run_native_browser_listener_impl,
)

from .orchestration.watcher_io import (
    fetch_rss as _fetch_rss_impl,
    handle_exit as _handle_exit_impl,
)

from .orchestration.watcher_worker_events import (
    run_browser_worker_event_listener as _run_browser_worker_event_listener_impl,
    on_job_accepted as _on_job_accepted_impl,
)

from .orchestration.watcher_user_feedback import (
    _setup_csv_logging as _setup_csv_logging_impl,
    show_notification as _show_notification_impl,
    open_in_browser as _open_in_browser_impl,
)

from .orchestration.watcher_monitor_status import (
    get_monitor_status as _get_monitor_status_impl,
    sync_monitor_metrics as _sync_monitor_metrics_impl,
    process_browser_jobs_snapshot as _process_browser_jobs_snapshot_impl,
)

from .orchestration.watcher_orchestration_helpers import (
    sync_browser_session_for_quiet_socket as _sync_browser_session_for_quiet_socket_impl,
    warn_if_browser_session_mismatch as _warn_if_browser_session_mismatch_impl,
    get_default_required_config_fields as _get_default_required_config_fields_impl,
    get_effective_rss_wait_range_seconds as _get_effective_rss_wait_range_seconds_impl,
    configure_cancellation_manager as _configure_cancellation_manager_impl,
)



from .orchestration.watcher_alerting import json_safe as _json_safe_impl
import concurrent.futures  # noqa: F401  -- still patched by tests via watcher.concurrent.futures

from .config import AppConfig
from .job_acceptance import JobAcceptanceEngine
from .job_cancellation_manager import JobCancellationManager
from .state import AppState

from .orchestration.watcher_health import (
    alert_on_health_snapshot as _alert_on_health_snapshot,
    build_health_snapshot,
    get_websocket_quiet_age,
    has_error_message,
    timestamp_or_none,
)
from .webhooks import WebhookAuditLogger, WebhookDispatcher


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

from .orchestration.watcher_config_values import (
    PLACEHOLDER_CONFIG_VALUES,  # noqa: F401
    SENSITIVE_KEYWORDS,
)


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
        self._browser_cookies = []
        self._next_quiet_socket_sync_ts = None
        self._health_alert_states = {}
        # BrowserJobs monitor wakes from this event when a workbench becomes
        # visible (or an explicit manual trigger fires). The monitor does NOT
        # poll the browser on a fixed timer by default.
        self._browser_jobs_refresh_event = threading.Event()
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
        """Emit an in-process API websocket event without blocking monitors.

        Delegates to watcher_alerting.emit_api_event for the actual
        implementation, while keeping the method on the class so existing
        call sites and tests continue to work.
        """
        from .orchestration.watcher_alerting import emit_api_event
        emit_api_event(self, event_type, payload)

    @staticmethod
    def _json_safe(value):
        return _json_safe_impl(value)

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
        """Log a warning when the configured session differs from the live browser."""
        return _warn_if_browser_session_mismatch_impl(self)


    def _get_default_required_config_fields(self) -> list[tuple[str, str]]:
        """Return the required config fields for currently enabled features."""
        return _get_default_required_config_fields_impl(self)


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
        return _sync_session_from_browser_impl(
            self,
            fail_hard=fail_hard,
            alert_on_failure=alert_on_failure,
        )

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
        return _sync_browser_session_for_quiet_socket_impl(
            self,
            current_time=current_time,
            fail_hard=fail_hard,
            alert_on_failure=alert_on_failure,
        )


    def _sync_session_before_websocket_connect(self) -> bool:
        """Try to sync browser session once before building websocket auth."""
        return _sync_session_before_websocket_connect_impl(self)

    def _is_gengo_rss_feed(self) -> bool:
        feed_url = str(self.config.get("Watcher", "feed_url") or "")
        return "gengo.com" in feed_url.lower()

    def _get_effective_rss_wait_range_seconds(self) -> tuple[float, float]:
        """Compute the effective RSS wait range from config + adaptive state."""
        return _get_effective_rss_wait_range_seconds_impl(self)


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
        """Dispatch newly-detected browser-jobs through process_new_job."""
        return _process_browser_jobs_snapshot_impl(self, snapshot)


    def get_monitor_status(self) -> dict:
        """Check health of all monitor threads."""
        return _get_monitor_status_impl(self)


    def _sync_monitor_metrics(self):
        """Sync metrics from email and website monitors."""
        return _sync_monitor_metrics_impl(self)


    def _capture_raw_ws_message(self, message: str, direction: str = "recv"):
        """Capture raw WebSocket message for debug output when raw debug is enabled."""
        return _capture_raw_ws_message_impl(self, message, direction)

    def get_raw_ws_messages(self) -> list:
        """Get a copy of the raw WebSocket message buffer."""
        return _get_raw_ws_messages_impl(self)

    def clear_raw_ws_messages(self):
        """Clear the raw WebSocket message buffer."""
        return _clear_raw_ws_messages_impl(self)
    def _setup_csv_logging(self):
        """Initialise CSV logging for RSS feed entries."""
        return _setup_csv_logging_impl(self)

    def show_notification(
        self,
        message,
        title="GengoWatcher",
        play_sound=False,
        open_link=False,
        url=None,
        sound_file=None,
    ):
        """Send a desktop notification + optional sound + browser open."""
        return _show_notification_impl(self, message, title=title, play_sound=play_sound, open_link=open_link, url=url, sound_file=sound_file)


    @staticmethod
    def _is_gengo_url(url: str) -> bool:
        parsed = urlparse(str(url or "").strip())
        hostname = parsed.hostname or ""
        return hostname == "gengo.com" or hostname.endswith(".gengo.com")

    def _open_in_managed_firefox_debug_session(self, url: str) -> bool:
        return open_in_managed_firefox_debug_session(self, url)
    def open_in_browser(self, url):
        """Open the given URL using the configured browser if available."""
        return _open_in_browser_impl(self, url)


    def _extract_reward(self, entry) -> float:
        return _extract_reward_impl(entry)

    def _log_all_entries(self, entries):
        return _log_all_entries_impl(self, entries)

    def _process_new_job(self, job_id, title, reward, url, source, source_meta=None):
        """Process a newly discovered job from RSS or WebSocket sources.

        Delegates to watcher_job_processor.process_new_job for the actual
        implementation, while keeping the method on the class so call
        sites such as WebAPI discovery handling, monitor callbacks, and tests
        continue to work unchanged.
        """
        return _process_new_job_impl(self, job_id, title, reward, url, source, source_meta)

    def _async_job_acceptance_wrapper(self, job_data: dict):
        """Wrapper to run async job acceptance in a separate thread."""
        return _async_job_acceptance_wrapper_impl(self, job_data)

    def _run_browser_worker_event_listener(self) -> None:
        """Tails the browser-worker telemetry JSONL file and forwards each line to the handler."""
        return _run_browser_worker_event_listener_impl(self)

    def _handle_browser_worker_telemetry_line(self, line: str) -> None:
        return _handle_telemetry_line_impl(self, line)

    def _handle_browser_worker_telemetry_payload(self, event_payload: dict) -> None:
        return _handle_telemetry_payload_impl(self, event_payload)


    def _async_cancel_current_job_wrapper(self, upcoming_job: dict):
        """Wrapper to cancel the current job without blocking the main thread."""
        return _async_cancel_current_job_wrapper_impl(self, upcoming_job)

    def _on_job_accepted(self, job_data: dict):
        """Record that a job has been accepted for future cancellation decisions."""
        return _on_job_accepted_impl(self, job_data)

    def _submit_job_to_translation_app_async(self, job_data: dict) -> None:
        """Submit a discovered job to translation-app without blocking monitors."""
        return _submit_job_to_translation_app_async_impl(self, job_data)

    def _process_feed_entries(self, entries):
        """Process RSS feed entries to identify new jobs."""
        return _process_feed_entries_impl(self, entries)

    def fetch_rss(self):
        """Fetch and parse the RSS feed from Gengo."""
        return _fetch_rss_impl(self)

    async def _websocket_logic(self):
        """Single WebSocket connection lifecycle - delegates to watcher_ws_logic.websocket_logic."""
        return await _websocket_logic_impl(self)

    def _run_websocket_monitor(self):
        """Persistent WebSocket connection lifecycle - delegates to watcher_ws_monitor.run_websocket_monitor."""
        return _run_websocket_monitor_impl(self)

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
        return run_browser_jobs_monitor(self)

    def _get_browser_jobs_idle_cap_seconds(self) -> float:
        """Long sleep between idle-cap keepalive pings. Default 30 minutes."""
        return float(
            self.config.getfloat("BrowserJobs", "idle_cap_sec", fallback=1800.0)
            or 1800.0
        )

    def trigger_browser_jobs_refresh(self, *, reason: str = "manual") -> None:
        """Public hook to wake the BrowserJobs monitor from external triggers."""
        return _bj_trigger(self, reason=reason)

    def _run_browser_jobs_triggered_refresh(
        self,
        debug_url: str,
        allow_navigation: bool,
    ) -> None:
        from .orchestration.watcher_browser_jobs import run_browser_jobs_triggered_refresh
        return run_browser_jobs_triggered_refresh(self, debug_url, allow_navigation)

    def _run_browser_jobs_passive_keepalive(self, debug_url: str) -> None:
        from .orchestration.watcher_browser_jobs import run_browser_jobs_passive_keepalive
        return run_browser_jobs_passive_keepalive(self, debug_url)

    def _run_browser_jobs_scrape(
        self,
        debug_url: str,
        *,
        force_refresh: bool,
        browse_url: str | None,
        interact: bool,
        allow_navigation: bool,
        is_keepalive: bool,
    ) -> None:
        from .orchestration.watcher_browser_jobs import _run_browser_jobs_scrape as _bj_scrape
        return _bj_scrape(
            self,
            debug_url,
            force_refresh=force_refresh,
            browse_url=browse_url,
            interact=interact,
            allow_navigation=allow_navigation,
            is_keepalive=is_keepalive,
        )

    def _run_rss_monitor(self):
        """RSS monitor thread - delegates to watcher_feed.run_rss_monitor."""
        return _run_rss_monitor_impl(self)

    def _run_native_browser_listener(self):
        """Optional side-channel monitor thread - delegates to watcher_monitors.run_native_browser_listener."""
        return _run_native_browser_listener_impl(self)

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
        """Set a config value and persist it."""
        return _set_config_value_impl(self, section, option, value)

    def get_config_value(self, section, option):
        """Get a config value."""
        return _get_config_value_impl(self, section, option)

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
        return _configure_cancellation_manager_impl(self)


    def prompt_for_config_values(self, required_fields=None):
        """Prompt the user for missing required config values."""
        return _prompt_for_config_values_impl(self, required_fields)

    def is_config_complete(self, required_fields=None):
        """Return True when every required config field has a usable value."""
        return _is_config_complete_impl(self, required_fields)

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
        """Run the shutdown sequence for the watcher."""
        return _handle_exit_impl(self)

    def _run_email_monitor(self):
        """Optional side-channel monitor thread - delegates to watcher_monitors.run_email_monitor."""
        return _run_email_monitor_impl(self)

    def _run_website_monitor(self):
        """Optional side-channel monitor thread - delegates to watcher_monitors.run_website_monitor."""
        return _run_website_monitor_impl(self)
