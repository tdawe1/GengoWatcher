__version__ = "2.1.4"
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

if sys.platform == "win32":
    try:
        import winsound

        SOUND_PLAYER = "winsound"
    except ImportError:
        SOUND_PLAYER = "none"
else:
    try:
        import playsound

        SOUND_PLAYER = "playsound"
    except ImportError:
        SOUND_PLAYER = "none"


class GengoWatcher:
    PAUSE_FILE = "gengowatcher.pause"

    def __init__(self, config: AppConfig, state: AppState, logger: logging.Logger):
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
        # VVV REPLACE THE EVENT WITH A SHARED VARIABLE AND LOCK VVV
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
        self.logger.debug(
            f"Initializing GengoWatcher with config: {self.config.config}"
        )
        if self.config.get("Logging", "log_all_entries_enabled"):
            self._setup_csv_logging()
        self.logger.info(f"GengoWatcher v{__version__} initialized.")

    def handle_exit(self, signum=None, frame=None):
        self.logger.debug("handle_exit called.")
        if not self.shutdown_event.is_set():
            self.logger.info("Shutdown initiated. Saving state...")
            self.shutdown_event.set()
            self.state.save_state()
            self.config.save_config()

    def _setup_csv_logging(self):
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
        sound_file_path = self.config.get("Paths", "sound_file")
        self.logger.debug(f"Attempting to play sound: {sound_file_path}")
        if not Path(sound_file_path).is_file():
            self.logger.warning(f"Sound file not found at: {sound_file_path}")
            return
        if SOUND_PLAYER == "playsound":
            try:
                playsound.playsound(sound_file_path)
            except Exception as e:
                self.logger.error(f"playsound error: {e}")
        elif SOUND_PLAYER == "winsound":
            winsound.PlaySound(sound_file_path, winsound.SND_FILENAME)
        else:
            self.logger.warning("No sound library available. Skipping sound.")

    def open_in_browser(self, url):
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
        text = entry.get("title", "") + " | " + entry.get("summary", "")
        self.logger.debug(f"Extracting reward from entry: {text}")
        match = re.search(r"Reward:\s*(?:US\$|\$)?\s*(\d+\.?\d*)", text, re.IGNORECASE)
        try:
            return float(match.group(1)) if match else 0.0
        except (ValueError, IndexError):
            return 0.0

    def _log_all_entries(self, entries):
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

        self.logger.info(  # Using the 'success' style for new jobs
            f"[success]New job via {source}: {title.split('|')[0].strip()} (US$ {reward:.2f})[/success]"
        )
        self.show_notification(
            message=title,
            title="New Gengo Job Available!",
            play_sound=True,
            open_link=True,
            url=url,
        )
        self.state.save_state()

    def _process_feed_entries(self, entries):
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
        # Update last_seen_rss_link with the newest link from this batch
        self.state.last_seen_rss_link = new_entries[0].get("link")
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
                ws_url, extra_headers=extra_headers, ping_interval=None
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

                async def keepalive():
                    self.logger.debug("WebSocket: Keepalive task started.")
                    try:
                        while True:
                            await asyncio.sleep(30)
                            try:
                                self.logger.debug("WebSocket: Sending keepalive ping.")
                                pong_waiter = await websocket.ping()
                                await asyncio.wait_for(pong_waiter, timeout=10)
                                self.logger.debug("WebSocket: Pong received.")
                            except Exception as e:
                                self.logger.warning(
                                    f"WebSocket: Keepalive ping failed: {e}"
                                )
                                break
                    except asyncio.CancelledError:
                        self.logger.debug("WebSocket: Keepalive task cancelled.")

                async def monitor_test_request():
                    """Monitors for a manual test request from the UI."""
                    self.logger.debug("WebSocket: Test command monitor started.")
                    while True:
                        command = None
                        with self._test_command_lock:
                            if self._test_command:
                                command = self._test_command
                                self._test_command = None  # Consume the command
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

                keepalive_task = asyncio.create_task(keepalive())
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
                    keepalive_task.cancel()
                    test_monitor_task.cancel()
                    try:
                        await keepalive_task
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
        if not self.state.last_seen_link:
            self.rss_action = "Priming feed"
            initial_feed = self.fetch_rss()
            if initial_feed and initial_feed.entries:
                self.state.last_seen_link = initial_feed.entries[0].get("link")
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

    def prompt_for_config_values(self, required_fields=None):
        import getpass

        self.logger.debug("Prompting for config values interactively.")
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
        for section, option in required_fields:
            current = self.config.get(section, option)
            prompt = f"Enter value for [{section}] {option} (current: {current}): "
            if "password" in option or "session" in option:
                value = getpass.getpass(prompt)
            else:
                value = input(prompt)
            if value:
                self.set_config_value(section, option, value)
        self.logger.info("Config interactive prompt complete.")

    def is_config_complete(self, required_fields=None):
        self.logger.debug("Checking if config is complete.")
        if required_fields is None:
            required_fields = []
            for section in self.config._config_parser.sections():
                for option in self.config._config_parser.options(section):
                    required_fields.append((section, option))
        for section, option in required_fields:
            val = self.config.get(section, option)
            if val in (None, "", "REPLACE_WITH_YOUR_SESSION_TOKEN"):
                self.logger.debug(
                    f"Config incomplete: [{section}] {option} is unset or placeholder."
                )
                return False
        return True

    def _simulate_new_job_notification(self):
        """Injects a fake job into the processing pipeline to test notifications."""
        self.logger.info("Simulating a new job notification...")
        fake_job_id = int(time.time())  # Use timestamp for a unique-ish ID
        fake_title = "TEST JOB: English > Japanese"
        fake_reward = 12.34
        fake_url = f"https://gengo.com/t/jobs/details/{fake_job_id}"
        self._process_new_job(
            fake_job_id, fake_title, fake_reward, fake_url, source="Test Simulation"
        )
        self.logger.info(
            "[bold green]Test job notification sent. Please check your system notifications.[/bold green]"
        )
