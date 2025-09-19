__version__ = "2.1.5"
__release_date__ = "2025-06-22"

import feedparser
import time
import webbrowser
from plyer import notification
import os
import sys
import threading
import logging
from pathlib import Path
import datetime
import subprocess
import re
import csv
import asyncio
import websockets
import json
from .config import AppConfig
from .state import AppState
from .captcha_manager import CaptchaSolverManager
from .job_cancellation_manager import JobCancellationManager
try:
    from .browser_automation import BrowserAutomationEngine
except ImportError:
    # Placeholder for BrowserAutomationEngine if import fails
    class BrowserAutomationEngine:
        def __init__(self, *args, **kwargs):
            pass

try:
    from .job_acceptance import JobAcceptanceEngine
    _JOB_ACCEPTANCE_IMPORT_ERROR = None
except ImportError as import_error:
    _JOB_ACCEPTANCE_IMPORT_ERROR = import_error

    class JobAcceptanceEngine:
        """Fallback job acceptance engine used when dependencies are missing."""

        def __init__(self, config, logger, captcha_solver=None):
            self.config = config
            self.logger = logger or logging.getLogger(__name__)
            self.captcha_solver = captcha_solver
            self._enabled = False
            self.logger.warning(
                "Auto-accept disabled: failed to import job_acceptance module (%s). "
                "Install required dependencies such as aiohttp and beautifulsoup4 to enable auto-accept.",
                import_error,
            )

        @property
        def enabled(self):
            return self._enabled

        @enabled.setter
        def enabled(self, value):
            if value:
                self.logger.warning(
                    "Cannot enable auto-accept because required dependencies are missing."
                )
                self._enabled = False
            else:
                self._enabled = False

        def is_job_eligible(self, job_data):
            return False

        async def accept_job(self, job_data):
            return False

        async def close_session(self):
            return

        def get_stats(self):
            return {
                "accepted_jobs": 0,
                "failed_acceptances": 0,
                "rate_limited": 0,
                "current_rate": 0.0,
                "enabled": self._enabled,
            }

if sys.platform == "win32":
    try:
        import winsound

        SOUND_PLAYER = "winsound"
    except ImportError:
        SOUND_PLAYER = "none"


class GengoWatcher:
    PAUSE_FILE = "gengowatcher.pause"

    def __init__(self, config: AppConfig, state: AppState, logger: logging.Logger):
        """Initialize the GengoWatcher instance.

        Sets up the watcher with configuration, state management, logging, and initializes
        various components including CAPTCHA solver, job acceptance engine, and browser
        automation engine.

        Args:
            config: Application configuration object containing all settings.
            state: Application state object for managing persistent data.
            logger: Logger instance for recording application events.
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
        self._seen_jobs_session = set(state.seen_job_ids)
        self._seen_jobs_lock = threading.Lock()
        self._all_entries_log_file = None
        self._csv_writer = None
        self._shutdown_initiated = False
        self.logger.debug(
            f"Initializing GengoWatcher with config: {self.config.config}"
        )
        if self.config.get("Logging", "log_all_entries_enabled"):
            self._setup_csv_logging()

        # Initialize CAPTCHA solver
        self.captcha_solver = CaptchaSolverManager(self.config.config, logger)

        # Register alert callback for CAPTCHA monitoring
        def captcha_alert_callback(service_name: str, level: str, message: str):
            """Handle CAPTCHA service alerts"""
            # Log the alert
            getattr(self.logger, level.lower(), self.logger.info)(f"CAPTCHA Alert [{service_name}]: {message}")

            # Show notification for critical alerts
            if level in ["ERROR", "CRITICAL"]:
                self.show_notification(
                    message,
                    title=f"CAPTCHA Service Alert ({service_name})",
                    play_sound=True
                )

        self.captcha_solver.monitor.add_alert_callback(captcha_alert_callback)

        # Initialize browser automation engine
        self.browser_automation_engine = BrowserAutomationEngine(config, logger, self.captcha_solver)
        try:
            session_token = self.config.get("WebSocket", "user_session")
            if session_token and session_token != "REPLACE_WITH_YOUR_SESSION_TOKEN":
                if self.browser_automation_engine.login_with_session(str(session_token)):
                    # Start monitors if configured
                    try:
                        if self.config.get("SeleniumMonitoring", "enable_live_dashboard"):
                            self.browser_automation_engine.start_live_dashboard_monitor(
                                on_new_job=lambda jid, url: self.browser_automation_engine.open_job_details_and_arm_accept(url)
                            )
                        if self.config.get("SeleniumMonitoring", "enable_list_refresh"):
                            interval_ms = self.config.getint("SeleniumMonitoring", "refresh_interval_ms")
                            self.browser_automation_engine.start_jobs_page_refresher(
                                on_new_job=lambda jid, url: self.browser_automation_engine.open_job_details_and_arm_accept(url),
                                interval_sec=max(0.25, float(interval_ms) / 1000.0),
                            )
                    except Exception as e:
                        self.logger.warning(f"Failed to start Selenium monitors: {e}")
        except Exception as e:
            self.logger.debug(f"Selenium login not initialized: {e}")

        # Initialize job acceptance engine (pass browser engine for fallbacks)
        self.job_acceptance_engine = JobAcceptanceEngine(
            config, logger, self.captcha_solver, browser_engine=self.browser_automation_engine
        )

        # Initialize job cancellation manager
        self.cancellation_manager = JobCancellationManager(config, logger)
        self.cancellation_manager.load_job_state()
        self._configure_cancellation_manager()

        self.logger.info(f"GengoWatcher v{__version__} initialized.")

    def start_captcha_monitoring(self, interval: int = 300):
        """Start monitoring CAPTCHA service health and performance"""
        self.captcha_solver.start_monitoring(interval)
    
    def stop_captcha_monitoring(self):
        """Stop monitoring CAPTCHA service health and performance"""
        self.captcha_solver.stop_monitoring()
    
    def show_captcha_health_status(self):
        """Show current CAPTCHA service health status"""
        self.captcha_solver.monitor.log_health_status()
    
    def show_captcha_performance_metrics(self):
        """Show CAPTCHA service performance metrics"""
        self.captcha_solver.monitor.log_performance_metrics()

    def _setup_csv_logging(self):
        """Set up CSV logging for recording all RSS feed entries.

        Creates the log directory if it doesn't exist and initializes the CSV writer
        with appropriate headers if the file is empty.

        Raises:
            IOError: If the log file cannot be opened or created.
        """
        self.logger.debug("Setting up CSV logging.")
        try:
            log_path = Path(self.config.get("Paths", "all_entries_log"))
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
    
    def play_sound(self):
        """Play notification sound using paplay.

        Attempts to play the configured sound file using the paplay command.
        Logs warnings if the sound file is not found or if paplay is not available.

        Raises:
            FileNotFoundError: If paplay command is not found in system PATH.
            Exception: For other errors during sound playback.
        """
        sound_file_path = self.config.get("Paths", "sound_file")
        self.logger.debug(f"Attempting to play sound with paplay: {sound_file_path}")

        if not Path(sound_file_path).is_file():
            self.logger.warning(f"Sound file not found at: {sound_file_path}")
            return

        try:
            subprocess.Popen(
                ['paplay', sound_file_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            self.logger.error("`paplay` command not found. Please install `libpulse` (sudo pacman -S libpulse).")
        except Exception as e:
            self.logger.error(f"Error playing sound with paplay: {e}")


    def open_in_browser(self, url):
        """Open a URL in the configured browser.

        Uses the configured browser path and arguments if available, otherwise
        falls back to the system default browser.

        Args:
            url: The URL to open in the browser.

        Raises:
            Exception: If there's an error opening the browser.
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

    def show_notification(
        self, message, title="GengoWatcher", play_sound=False, open_link=False, url=None
    ):
        """Show a desktop notification with optional sound and browser opening.

        Displays a notification using the plyer library if notifications are enabled.
        Can optionally play a sound and/or open a URL in the browser.

        Args:
            message: The notification message text.
            title: The notification title (default: "GengoWatcher").
            play_sound: Whether to play a notification sound (default: False).
            open_link: Whether to open the provided URL in browser (default: False).
            url: The URL to open if open_link is True (default: None).

        Raises:
            Exception: If there's an error displaying the notification.
        """
        self.logger.debug(f"Showing notification: {title} - {message}")
        if self.config.get("Watcher", "enable_notifications"):
            try:
                icon_path = self.config.get("Paths", "notification_icon_path")
                app_icon = str(icon_path) if Path(icon_path).is_file() else None
                notification.notify(
                    title=title,
                    message=message,
                    app_name="GengoWatcher",
                    app_icon=app_icon,
                    timeout=8,
                )
            except Exception as e:
                self.logger.error(f"Notify Error: {e}")
        if play_sound and self.config.get("Watcher", "enable_sound"):
            threading.Thread(target=self.play_sound, daemon=True).start()
        if open_link and url:
            self.open_in_browser(url)


    def _extract_reward(self, entry) -> float:
        """Extract the reward amount from an RSS feed entry.

        Parses the title and summary of an RSS entry to find reward information
        using a regular expression pattern.

        Args:
            entry: Dictionary containing RSS entry data with 'title' and 'summary' keys.

        Returns:
            float: The extracted reward amount, or 0.0 if not found or invalid.
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
                "source": source
            }
            self.state.add_job(job_data)
        except Exception as e:
            self.logger.warning(f"Failed to store job in state: {e}")

        # Consider cancelling a current job if this one is better
        try:
            if self.cancellation_manager.cancellation_enabled and self.cancellation_manager.should_cancel_for_job(
                float(job_data.get("reward", 0.0)), str(job_data.get("id"))
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
            self.logger.info(f"Job {job_id} meets auto-accept criteria, queuing for acceptance")
            # Fire Selenium accept watcher immediately
            try:
                if hasattr(self, 'browser_automation_engine') and self.browser_automation_engine:
                    self.browser_automation_engine.open_job_details_and_arm_accept(url)
            except Exception as e:
                self.logger.debug(f"Selenium accept watcher start failed: {e}")
            # Run job acceptance in a separate thread to avoid blocking
            threading.Thread(
                target=self._async_job_acceptance_wrapper,
                args=(job_data,),
                daemon=True
            ).start()
        elif hasattr(self.browser_automation_engine, 'is_job_eligible') and self.browser_automation_engine.is_job_eligible(job_data):
            self.logger.info(f"Job {job_id} meets browser automation criteria, queuing for acceptance")
            try:
                self.browser_automation_engine.open_job_details_and_arm_accept(url)
            except Exception as e:
                self.logger.debug(f"Selenium accept watcher start failed: {e}")
            # Run browser automation in a separate thread to avoid blocking
            threading.Thread(
                target=self._async_browser_automation_wrapper,
                args=(job_data,),
                daemon=True
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
            success = loop.run_until_complete(self.job_acceptance_engine.accept_job(job_data))
            if success:
                self._on_job_accepted(job_data)
        except Exception as e:
            self.logger.error(f"Error in job acceptance wrapper for job {job_data.get('id')}: {e}")
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
                self.logger.warning("Failed to cancel current job before processing new opportunity")
        except Exception as e:
            self.logger.error(f"Error during automatic job cancellation: {e}")

    def _on_job_accepted(self, job_data: dict):
        """Record that a job has been accepted for future cancellation decisions."""
        try:
            job_id = str(job_data.get("id"))
            reward = float(job_data.get("reward", 0.0))
            self.cancellation_manager.set_current_job(job_id, reward)
            self.logger.debug(f"Tracking job {job_id} (${reward:.2f}) as current engagement")
        except Exception as e:
            self.logger.error(f"Failed to record accepted job for cancellation tracking: {e}")

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
                match = re.search(r"/jobs/(?:details/)?(\d+)", url)
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
            headers["User-Agent"] = f"GengoWatcher/{__version__} ({email})"
        self.logger.debug(
            f"Fetching RSS feed: {self.config.get('Watcher', 'feed_url')} with headers: {headers}"
        )
        try:
            feed = feedparser.parse(
                self.config.get("Watcher", "feed_url"), request_headers=headers
            )
            if feed.bozo:
                self.logger.error(f"Feed Error: {feed.bozo_exception}")
                return None
            self.logger.debug(
                f"RSS feed fetched successfully. Entries: {len(feed.entries)}"
            )
            return feed
        except Exception as e:
            self.logger.error(f"RSS Error: {e}")
            return None

    async def _websocket_logic(self):
        """The core async logic for a single WebSocket connection attempt, with close code/reason logging and keepalive pings."""
        ws_url = "wss://live-dashboard.gengo.com"
        self.websocket_status = "Connecting"
        self.logger.debug(f"Attempting WebSocket connection to {ws_url}")
        try:
            extra_headers = [
                (
                    "Cookie",
                    f"my_gengo_session={self.config.get('WebSocket', 'user_session')}",
                ),
                ("Origin", "https://gengo.com"),
                (
                    "User-Agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
                ),
            ]
            async with websockets.connect(
                    ws_url,
                    extra_headers=extra_headers,
                    ping_interval=20,
                    ping_timeout=10,
            ) as websocket:
                self.websocket_status = "Authenticating"
                auth_payload = {
                    "user_id": self.config.get("WebSocket", "user_id"),
                    "user_session": self.config.get("WebSocket", "user_session"),
                }
                self.logger.debug(f"WebSocket: Sending auth payload: {auth_payload}")
                await websocket.send(json.dumps(auth_payload))

                self.websocket_status = "Live"
                self.logger.info("WebSocket connection is live and listening.")

                try:
                    first_message = await asyncio.wait_for(websocket.recv(), timeout=5)
                    self.logger.debug(
                        f"WebSocket: First message after auth: {first_message}"
                    )
                    try:
                        data = json.loads(first_message)
                        self.logger.debug(f"WebSocket: First message JSON: {data}")
                    except Exception as e:
                        self.logger.warning(
                            f"WebSocket: Could not parse first message as JSON: {e}"
                        )
                except asyncio.TimeoutError:
                    self.logger.debug(
                        "WebSocket: No message received immediately after authentication."
                    )
                except Exception as e:
                    self.logger.warning(
                        f"WebSocket: Error receiving first message: {e}"
                    )

                async def monitor_test_request():
                    """Monitors for a manual test request from the UI."""
                    self.logger.debug("WebSocket: Test command monitor started.")
                    while True:
                        command = None
                        with self._test_command_lock:
                            if self._test_command:
                                command = self._test_command
                                self._test_command = None
                        if command == "ping":
                            self.logger.info("WebSocket: PING test initiated by user.")
                            try:
                                pong_waiter = await websocket.ping()
                                await asyncio.wait_for(pong_waiter, timeout=5)
                                self.logger.info(
                                    "[bold green]WebSocket: PING test successful. Connection is live.[/bold green]"
                                )
                            except asyncio.TimeoutError:
                                self.logger.warning(
                                    "[bold red]WebSocket: PING test failed (timeout). Connection may be stalled.[/bold red]"
                                )
                            except Exception as e:
                                self.logger.error(f"WebSocket: PING test failed: {e}")
                        elif command == "notify":
                            self._simulate_new_job_notification()
                        await asyncio.sleep(0.2)

                test_monitor_task = asyncio.create_task(monitor_test_request())
                try:
                    async for message in websocket:
                        self.logger.debug(f"WebSocket: Message received: {message}")
                        try:
                            data = json.loads(message)
                            self.logger.debug(f"WebSocket: Message JSON: {data}")
                        except Exception as e:
                            self.logger.warning(
                                f"WebSocket: Could not parse message as JSON: {e}"
                            )
                        if (
                            isinstance(data, dict)
                            and data.get("type") == "available_collection"
                        ):
                            job = data.get("collection", {})
                            job_id = job.get("id")
                            self.logger.debug(f"WebSocket: Job data: {job}")
                            if job_id:
                                reward = float(job.get("rewards", 0.0))
                                title = f"{job.get('lc_src')} > {job.get('lc_tgt')}"
                                url = f"https://gengo.com/t/jobs/details/{job_id}"
                                self._process_new_job(
                                    job_id, title, reward, url, source="WebSocket"
                                )
                except websockets.exceptions.ConnectionClosed as e:
                    self.logger.warning(
                        f"WebSocket: Disconnected: code={e.code}, reason={e.reason}"
                    )
                except Exception as e:
                    self.logger.error(f"WebSocket: Error in main loop: {e}")
                finally:
                    test_monitor_task.cancel()
                    try:
                        await test_monitor_task
                    except asyncio.CancelledError:
                        self.logger.debug(
                            "WebSocket: keepalive_task and test_monitor_task cancelled and awaited cleanly."
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"WebSocket: Exception while awaiting tasks: {e}"
                        )
                if hasattr(websocket, "close_code") or hasattr(
                    websocket, "close_reason"
                ):
                    self.logger.info(
                        f"WebSocket: Closed: code={getattr(websocket, 'close_code', None)}, reason={getattr(websocket, 'close_reason', None)}"
                    )
        except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError) as e:
            code = getattr(e, "code", None)
            reason = getattr(e, "reason", None)
            self.logger.warning(
                f"WebSocket: Outer disconnect: code={code}, reason={reason}, error={e}"
            )
        except Exception as e:
            self.logger.error(f"WebSocket: Outer error: {e}")

    def _run_websocket_monitor(self):
        """The main loop for the WebSocket connection, designed to run in a thread."""
        self.logger.debug("Starting WebSocket monitor thread.")
        while not self.shutdown_event.is_set():
            if (
                self.config.get("WebSocket", "user_session")
                == "REPLACE_WITH_YOUR_SESSION_TOKEN"
            ):
                self.logger.warning(
                    "WebSocket disabled: Please set 'user_session' in config.ini."
                )
                self.websocket_status = "Disabled"
                self.shutdown_event.wait()
                break
            try:
                self.logger.debug("Running websocket logic (asyncio.run)")
                asyncio.run(self._websocket_logic())
                if self.shutdown_event.is_set():
                    break
                self.websocket_status = "Offline"
                self.logger.info(
                    "WebSocket connection closed. Reconnecting in 20 seconds..."
                )
                if self.shutdown_event.wait(20):
                    break
            except Exception as e:
                self.logger.error(f"Critical error in WebSocket runner: {e}")
                if self.shutdown_event.wait(20):
                    break
        self.logger.info("WebSocket monitor thread stopped.")
        self.websocket_status = "Stopped"

    def run(self):
        self.logger.debug("Starting watcher parent thread.")
        self.logger.info("Watcher parent thread started. Launching monitors...")

        rss_thread = threading.Thread(target=self._run_rss_monitor, daemon=True)
        rss_thread.start()

        if self.config.get("WebSocket", "enable_websocket"):
            ws_thread = threading.Thread(
                target=self._run_websocket_monitor, daemon=True
            )
            ws_thread.start()
            self.websocket_status = "Enabled"
        else:
            self.websocket_status = "Disabled"

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
            return loop.run_until_complete(self.cancellation_manager.cancel_current_job())
        finally:
            loop.close()

    def _configure_cancellation_manager(self):
        """Apply configuration settings to the cancellation manager."""
        try:
            settings = {
                "cancellation_enabled": self.config.getboolean("Cancellation", "enabled", fallback=True),
                "min_improvement_ratio": self.config.getfloat("Cancellation", "min_improvement_ratio", fallback=2.0),
                "extreme_threshold": self.config.getfloat("Cancellation", "extreme_threshold", fallback=1000.0),
            }
            self.cancellation_manager.update_settings(**settings)
        except Exception as e:
            self.logger.error(f"Failed to configure cancellation manager: {e}")

    def prompt_for_config_values(self, required_fields=None):
        import getpass

        self.logger.debug("Prompting for config values interactively.")

        # Check if this is a fresh config
        config_file = Path(self.config.CONFIG_FILE)
        is_new_config = config_file.stat().st_size < 1000  # Rough check for new/small config

        if is_new_config:
            print("\n" + "="*60)
            print("🎉 Welcome to GengoWatcher!")
            print("="*60)
            print("A default configuration file has been created.")
            print("Let's set up the essential settings to get you started.")
            print("="*60 + "\n")

        if required_fields is None:
            required_fields = []
            for section in self.config._config_parser.sections():
                for option in self.config._config_parser.options(section):
                    if self.config.get(section, option) in (
                        None,
                        "",
                        "REPLACE_WITH_YOUR_SESSION_TOKEN",
                    ):
                        required_fields.append((section, option))

        if not required_fields:
            print("✅ All configuration values are set!")
            return

        print(f"\n📝 Please provide values for {len(required_fields)} required configuration settings:")
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
                display_current = current if current != "REPLACE_WITH_YOUR_SESSION_TOKEN" else "(not set)"

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

                if "password" in option.lower() or "session" in option.lower() or "key" in option.lower():
                    value = getpass.getpass(prompt)
                else:
                    value = input(prompt).strip()

                if value:
                    self.set_config_value(section, option, value)
                    print(f"  ✅ Set {option} = {value}")
                else:
                    print(f"  ⚠️  Skipped {option} (keeping current value)")

        print("\n" + "="*60)
        print("✅ Configuration setup complete!")
        print("You can always reconfigure later with: python -m gengowatcher.main --configure")
        print("="*60 + "\n")

        self.logger.info("Config interactive prompt complete.")

    def is_config_complete(self, required_fields=None):
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
                if val in (None, "", "REPLACE_WITH_YOUR_SESSION_TOKEN"):
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

    def get_captcha_stats(self):
        """Get CAPTCHA solver statistics"""
        if self.captcha_solver.is_configured():
            return {
                'configured': True,
                'balance': self.captcha_solver.get_balance(),
                'stats': self.captcha_solver.get_stats()
            }
        else:
            return {
                'configured': False,
                'balance': 0.0,
                'stats': {}
            }
    
    def get_job_acceptance_stats(self):
        """Get job acceptance engine statistics"""
        if hasattr(self, 'job_acceptance_engine'):
            return self.job_acceptance_engine.get_stats()
        else:
            return {
                'accepted_jobs': 0,
                'failed_acceptances': 0,
                'rate_limited': 0,
                'current_rate': 0.0,
                'enabled': False
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
    
    def handle_job_rejection(self, job_data: dict):
        """Handle job rejection that might require CAPTCHA solving"""
        self.logger.info(f"Handling job rejection for job ID: {job_data.get('id')}")
        
        # Check if CAPTCHA solver is configured
        if not self.captcha_solver.is_configured():
            self.logger.warning("CAPTCHA solver not configured, cannot handle job rejection")
            return False
        
        # Let the CAPTCHA manager handle the rejection
        success = self.captcha_solver.handle_job_rejection(job_data)
        
        if success:
            self.logger.info(f"Successfully handled CAPTCHA for rejected job {job_data.get('id')}")
            # Here you would implement logic to resubmit the job or notify the user
            # For example:
            # self._resubmit_job(job_data)
        else:
            self.logger.error(f"Failed to handle CAPTCHA for rejected job {job_data.get('id')}")
            
        return success

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
                self.logger.exception("Failed to %s during shutdown: %s", description, error)

        if getattr(self, "captcha_solver", None):
            try:
                self.captcha_solver.stop_monitoring()
            except Exception as error:
                self.logger.exception("Failed to stop CAPTCHA monitoring: %s", error)
            try:
                self.captcha_solver.close()
            except Exception as error:
                self.logger.exception("Failed to close CAPTCHA solver: %s", error)

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

        if getattr(self, "browser_automation_engine", None):
            try:
                self.browser_automation_engine.close()
            except Exception as error:
                self.logger.exception("Failed to close browser automation engine: %s", error)

        if self._all_entries_log_file:
            try:
                self._all_entries_log_file.flush()
                self._all_entries_log_file.close()
            except Exception as error:
                self.logger.exception("Failed to close CSV log file: %s", error)
            finally:
                self._all_entries_log_file = None
                self._csv_writer = None

        try:
            self.state.save_state()
        except Exception as error:
            self.logger.exception("Failed to save state during shutdown: %s", error)

        self.logger.info("GengoWatcher shutdown complete")
