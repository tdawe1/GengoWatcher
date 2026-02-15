__version__ = "2.1.5"
__release_date__ = "2025-06-22"

import asyncio
import concurrent.futures
import csv
import datetime
import json
import logging
import os
import re
import random
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from pathlib import Path

import feedparser
import websockets
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatusCode

from .config import AppConfig
from .job_acceptance import JobAcceptanceEngine
from .job_cancellation_manager import JobCancellationManager
from .state import AppState
from .browser_detector import BrowserDetector

from . import notifier

try:
    from .email_monitor import EmailMonitor
except ImportError:
    EmailMonitor = None

try:
    from .website_monitor import WebsiteMonitor
except ImportError:
    WebsiteMonitor = None

PLACEHOLDER_CONFIG_VALUES = {
    None,
    "",
    "REPLACE_WITH_YOUR_SESSION_TOKEN",
    "REPLACE_WITH_YOUR_USER_KEY",
}

SENSITIVE_KEYWORDS = {"password", "session", "key"}


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
        self.websocket_last_close_code = None
        self.websocket_last_close_reason = None
        # Email monitor metrics (read by UI)
        self.email_monitor_status = "Disabled"
        self.email_last_check_time = None
        self.email_jobs_found_session = 0

        # Website monitor metrics (read by UI)
        self.website_monitor_status = "Disabled"
        self.website_last_check_time = None
        self.website_jobs_found_session = 0
        self._seen_jobs_session = set(state.seen_job_ids)
        self._seen_jobs_lock = threading.Lock()
        self._all_entries_log_file = None
        self._csv_writer = None
        self._shutdown_initiated = False
        self._rss_executor = None
        self._rss_future = None
        self._rss_future_started_at = None
        # Thread references for health monitoring
        self._monitor_threads = {}  # name -> threading.Thread
        # Raw WebSocket message buffer for debug output
        self._raw_ws_messages = deque(maxlen=50)
        self._raw_ws_lock = threading.Lock()
        self.logger.debug(
            f"Initializing GengoWatcher with config: {self.config.config}"
        )
        if self.config.get("Logging", "log_all_entries_enabled"):
            self._setup_csv_logging()

        # Initialize job acceptance engine (without CAPTCHA support)
        self.job_acceptance_engine = JobAcceptanceEngine(
            config,
            logger,
        )

        # Initialize job cancellation manager
        self.cancellation_manager = JobCancellationManager(config, logger)
        self.cancellation_manager.load_job_state()
        self._configure_cancellation_manager()

        # Browser detector for dynamic User-Agent
        self.browser_detector = BrowserDetector(config.list_all(), logger)

        self.logger.info(f"GengoWatcher v{__version__} initialized.")

    def get_monitor_status(self) -> dict:
        """
        Check health of all monitor threads.

        Returns:
            dict: Mapping of monitor name to status ("alive", "dead", "disabled")
        """
        status = {}
        for name in ["rss", "websocket", "email", "website"]:
            thread = self._monitor_threads.get(name)
            if thread is None:
                status[name] = "disabled"
            elif thread.is_alive():
                status[name] = "alive"
            else:
                status[name] = "dead"
        status["email_detail"] = self.email_monitor_status
        status["website_detail"] = self.website_monitor_status
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
            formatted = json.dumps(parsed, indent=2)
        except (json.JSONDecodeError, TypeError):
            formatted = message

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
            if not log_path_str:
                self.logger.error("all_entries_log path not configured")
                return
            log_path = Path(log_path_str)
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
        self, message, title="GengoWatcher", play_sound=False, open_link=False, url=None
    ):
        """
        Send a desktop notification and optionally play a sound or open a URL.

        Parameters:
            message (str): Notification message body.
            title (str): Notification title; defaults to "GengoWatcher".
            play_sound (bool): If True and sound is enabled in configuration, play the configured sound.
            open_link (bool): If True and `url` is provided, open the URL in the configured browser.
            url (str | None): URL to open when `open_link` is True; ignored if not provided.
        """
        if self.config.get("Watcher", "enable_notifications"):
            icon_path = self.config.get("Paths", "notification_icon_path")
            notifier.send_notification(title, message, icon_path)

        if play_sound and self.config.get("Watcher", "enable_sound"):
            sound_file = self.config.get("Paths", "sound_file")
            notifier.play_sound(sound_file)

        if open_link and url:
            self.open_in_browser(url)

    def open_in_browser(self, url):
        """
        Open the given URL using the configured browser if available, otherwise use the system default browser.

        Parameters:
            url (str): The URL to open. If the configured `browser_args` include formatting placeholders (for example `{url}`), they will be formatted with this URL.
        """
        self.logger.debug(f"Opening URL in browser: {url}")
        try:
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

    def _process_new_job(self, job_id, title, reward, url, source):
        """Process a newly discovered job from RSS or WebSocket sources.

        Handles job filtering, notification, storage, and auto-acceptance logic.
        Updates session statistics and ensures thread-safe access to shared state.

        Args:
            job_id: Unique identifier for the job.
            title: Job title/description.
            reward: Job reward amount in USD.
            url: URL to access the job.
            source: Source of the job discovery ("RSS" or "WebSocket").
        """
        self.logger.debug(
            f"Processing new job: {job_id}, {title}, {reward}, {url}, {source}"
        )
        with self._seen_jobs_lock:
            if job_id in self._seen_jobs_session:
                return
            self._seen_jobs_session.add(job_id)
            self.state.seen_job_ids.append(job_id)
            min_reward = self.config.get("Watcher", "min_reward")
            if min_reward > 0.0 and reward < min_reward:
                self.logger.warning(
                    f"Job '{title}' (US$ {reward:.2f}) ignored due to [yellow]min_reward filter[/]."
                )
                return
            self.state.total_new_entries_found += 1
            self.session_new_entries += 1
            self.session_total_value += reward

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

        # Store job in state for web API access
        try:
            job_data = {
                "id": str(job_id),
                "title": title,
                "reward": float(reward),
                "currency": "USD",
                "url": url,
                "timestamp": time.time(),
                "source": source,
            }
            self.state.add_job(job_data)
        except Exception as e:
            self.logger.warning(f"Failed to store job in state: {e}")

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
        if self.job_acceptance_engine.is_job_eligible(job_data):
            self.logger.info(
                f"Job {job_id} meets auto-accept criteria, queuing for acceptance"
            )
            threading.Thread(
                target=self._async_job_acceptance_wrapper, args=(job_data,), daemon=True
            ).start()
        else:
            self.logger.debug(f"Job {job_id} does not meet auto-accept criteria")

        self.state.save_state()

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
        except Exception as e:
            self.logger.error(
                f"Error in job acceptance wrapper for job {job_data.get('id')}: {e}"
            )
        finally:
            loop.close()

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
            self.cancellation_manager.set_current_job(job_id, reward)
            self.logger.debug(
                f"Tracking job {job_id} (${reward:.2f}) as current engagement"
            )
        except Exception as e:
            self.logger.error(
                f"Failed to record accepted job for cancellation tracking: {e}"
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
                self._process_new_job(job_id, title, reward, url, source="RSS")
            except (ValueError, IndexError) as e:
                self.logger.warning(f"Error processing RSS entry {url}: {e}")

    def fetch_rss(self):
        """Fetch and parse the RSS feed from Gengo.

        Retrieves the RSS feed using feedparser with optional custom user agent.
        Handles various error conditions and logs appropriate messages.

        Returns:
            feedparser.FeedParserDict: Parsed RSS feed object, or None if fetch failed.

        Raises:
            Exception: For network or parsing errors (logged internally).
        """
        headers = {}
        if self.config.get("Watcher", "use_custom_user_agent"):
            email = self.config.get("Network", "user_agent_email")
            headers["User-Agent"] = self.browser_detector.get_user_agent()
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
            self.config.get("WebSocket", "wss_url") or "wss://live-dashboard.gengo.com"
        )
        self.websocket_status = "Connecting"
        self.logger.info(f"WebSocket: Initializing connection to {ws_url}")

        try:
            # Determine User-Agent
            user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
            custom_ua = self.config.get("Network", "browser_user_agent")
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
            masked_user_key = (
                f"{user_key[:4]}...{user_key[-4:]}"
                if user_key and len(user_key) > 8
                else "NOT_SET"
            )

            extra_headers = [
                (
                    "Cookie",
                    f"myG_myGSession_={session_token}; myG_rdsessID={session_token}",
                ),
                ("Origin", "https://gengo.com"),
                ("Pragma", "no-cache"),
                ("Cache-Control", "no-cache"),
                ("User-Agent", user_agent),
                ("Accept-Language", "en-GB,en-US;q=0.9,en;q=0.8"),
                ("Accept-Encoding", "gzip, deflate, br, zstd"),
            ]

            # Log headers (masking sensitive info)
            safe_headers = []
            for k, v in extra_headers:
                if k == "Cookie":
                    safe_headers.append((k, f"my_gengo_session={masked_token}"))
                else:
                    safe_headers.append((k, v))
            self.logger.debug(f"WebSocket: Preparing headers: {safe_headers}")

            # websockets 12+ renamed extra_headers -> additional_headers.
            ws_header_key = (
                "additional_headers"
                if int(str(getattr(websockets, "__version__", "0").split(".")[0])) >= 12
                else "extra_headers"
            )

            async def run_session(headers):
                """
                Run a single WebSocket session: connect, authenticate, monitor heartbeat and test commands, and process incoming messages.

                Parameters:
                    headers (dict | None): Optional extra HTTP headers to include in the WebSocket handshake; pass None to omit custom headers.

                Detailed behaviour:
                    - Connects to the configured WebSocket URL and sends an authentication payload containing the configured `user_id`, the stored session token and, if present, the `user_key`.
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
                self.logger.debug(
                    f"WebSocket: Attempting connection to {ws_url} ({header_desc})"
                )
                async with websockets.connect(  # type: ignore
                    ws_url,
                    **{ws_header_key: headers},
                    ping_interval=20,
                    ping_timeout=10,
                    compression=None,
                ) as websocket:
                    connected_at = time.time()
                    self.websocket_status = "Authenticating"
                    user_id = self.config.get("WebSocket", "user_id")

                    auth_payload = {
                        "user_id": user_id,
                        "user_session": session_token,
                    }
                    # Log auth attempt safely
                    self.logger.debug(
                        "WebSocket: Sending auth payload for user_id=%s (user_key=%s)",
                        user_id,
                        masked_user_key,
                    )

                    auth_json = json.dumps(auth_payload)
                    self._capture_raw_ws_message(auth_json, direction="send")
                    await websocket.send(auth_json)

                    self.websocket_status = "Live"
                    self.logger.info(
                        "WebSocket: Connection established and authenticated."
                    )

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
                                self.websocket_last_pong_ts = time.time()
                                self.websocket_ping_latency_ms = latency
                                self.logger.debug(
                                    f"WebSocket: Heartbeat pong received. Latency: {latency:.2f}ms"
                                )
                            except asyncio.CancelledError:
                                raise
                            except Exception as e:
                                # Log and continue; the main loop will handle real disconnects
                                self.logger.warning(f"WebSocket: Heartbeat failed: {e}")

                    heartbeat_task = asyncio.create_task(heartbeat())

                    try:
                        self.logger.debug("WebSocket: Waiting for first message...")
                        first_message = await asyncio.wait_for(
                            websocket.recv(), timeout=5
                        )
                        messages_received = True
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
                        try:
                            await test_monitor_task
                            await heartbeat_task
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

            try:
                await run_session(extra_headers)
            except (InvalidStatusCode, InvalidHandshake) as e:
                # Some load balancers/proxies reject any custom headers; retry without them.
                message = str(e).lower()
                if "extra headers" in message or "extra header" in message:
                    self.logger.warning(
                        "WebSocket handshake rejected due to extra headers; retrying without custom headers."
                    )
                    await run_session(None)
                else:
                    raise
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
            session_token = self.config.get("WebSocket", "user_session")
            user_key = self.config.get("WebSocket", "user_key")

            # Validate session token (required)
            if not session_token or session_token == session_placeholder:
                self.logger.warning(
                    "WebSocket disabled: Please set 'user_session' in config.ini."
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
        self.websocket_status = "Stopped"

    def run(self):
        self.logger.debug("Starting watcher parent thread.")
        self.logger.info("Watcher parent thread started. Launching monitors...")

        rss_thread = threading.Thread(target=self._run_rss_monitor, daemon=True)
        rss_thread.start()
        self._monitor_threads["rss"] = rss_thread

        if self.config.get("WebSocket", "enable_websocket"):
            ws_thread = threading.Thread(
                target=self._run_websocket_monitor, daemon=True
            )
            ws_thread.start()
            self._monitor_threads["websocket"] = ws_thread
            self.websocket_status = "Enabled"
        else:
            self.websocket_status = "Disabled"

        if self.config.get("EmailMonitor", "enabled"):
            email_thread = threading.Thread(target=self._run_email_monitor, daemon=True)
            email_thread.start()
            self._monitor_threads["email"] = email_thread
            self.logger.info("Email monitor thread started")

        if self.config.get("WebsiteMonitor", "enabled"):
            website_thread = threading.Thread(
                target=self._run_website_monitor, daemon=True
            )
            website_thread.start()
            self._monitor_threads["website"] = website_thread
            self.logger.info("Website monitor thread started")

        self.shutdown_event.wait()
        self.logger.info("Watcher parent thread shutting down.")

    def _run_rss_monitor(self):
        self.logger.debug("Starting RSS monitor thread.")
        self.logger.info("RSS monitor thread started.")
        if not self.state.last_seen_rss_link:
            if self.state.last_seen_link:
                self.state.last_seen_rss_link = self.state.last_seen_link
                self.logger.debug(
                    "Migrated legacy last_seen_link value to last_seen_rss_link."
                )
            else:
                self.rss_action = "Priming feed"
                initial_feed = self.fetch_rss()
                if initial_feed and initial_feed.entries:
                    first_link = initial_feed.entries[0].get("link")
                    self.state.last_seen_rss_link = first_link
                    self.state.last_seen_link = first_link
                    self.logger.info("Initial RSS feed primed successfully.")
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
                            self.config.get("Watcher", "check_interval")
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
                        wait_time = self.config.get("Watcher", "check_interval")
                        self.rss_action = "Waiting"
                self.next_check_time = time.time() + wait_time

        self.logger.info("RSS monitor thread stopped.")

    def run_notify_test(self):
        self.logger.info("Sending a test notification...")
        self.show_notification(
            message="This is a test notification!",
            title="GengoWatcher Test",
            play_sound=True,
            open_link=True,
            url="https://gengo.com/t/jobs/status/available",
        )

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
        config_dict = {}
        for section in self.config._config_parser.sections():
            config_dict[section] = dict(self.config._config_parser.items(section))
        self.logger.debug(f"Listing all config values: {config_dict}")
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
                "cancellation_enabled": self.config.getboolean(
                    "Cancellation", "enabled", fallback=True
                ),
                "min_improvement_ratio": self.config.getfloat(
                    "Cancellation", "min_improvement_ratio", fallback=2.0
                ),
                "extreme_threshold": self.config.getfloat(
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
            required_fields = []
            for section in self.config._config_parser.sections():
                for option in self.config._config_parser.options(section):
                    value = self.config.get(section, option)
                    # Skip lists (like cors_origins) - they can't be placeholder values
                    if isinstance(value, list):
                        continue
                    if value in PLACEHOLDER_CONFIG_VALUES:
                        required_fields.append((section, option))

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
            required_fields = []
            # Only check sections that exist in our loaded config
            for section in self.config.config.keys():
                for option in self.config.config[section].keys():
                    required_fields.append((section, option))

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
