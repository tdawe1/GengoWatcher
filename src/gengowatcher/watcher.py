__version__ = "2.1.0"
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
        from playsound import playsound

        SOUND_PLAYER = "playsound"
    except ImportError:
        SOUND_PLAYER = "none"


class GengoWatcher:
    PAUSE_FILE = "gengowatcher.pause"

    def __init__(self, config: AppConfig, state: AppState, logger: logging.Logger):
        self.logger = logger
        self.config = config
        self.state = state
        self.shutdown_event = threading.Event()
        self.check_now_event = threading.Event()
        self.last_check_time = None
        self.next_check_time = time.time()
        self.failure_count = 0
        self.current_action = "Initializing"
        self.start_time = time.time()
        self.session_new_entries = 0
        self.session_total_value = 0.0
        self.websocket_status = "Disabled"
        self._seen_jobs_session = set()
        self._seen_jobs_lock = threading.Lock()
        self._all_entries_log_file = None
        self._csv_writer = None
        if self.config.get("Logging", "log_all_entries_enabled"):
            self._setup_csv_logging()
        self.logger.info(f"GengoWatcher v{__version__} initialized.")

    def handle_exit(self, signum=None, frame=None):
        if not self.shutdown_event.is_set():
            self.logger.info("Shutdown initiated. Saving state...")
            self.shutdown_event.set()
            self.state.save_state()
            self.config.save_config()

    def _setup_csv_logging(self):
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
        except IOError as e:
            self.logger.error(f"Could not open all_entries_log file: {e}")
            self._all_entries_log_file = None
            self._csv_writer = None

    def play_sound(self):
        sound_file_path = self.config.get("Paths", "sound_file")
        if not Path(sound_file_path).is_file():
            self.logger.warning(f"Sound file not found at: {sound_file_path}")
            return
        if SOUND_PLAYER == "playsound":
            try:
                playsound(sound_file_path)
            except Exception as e:
                self.logger.error(f"playsound error: {e}")
        elif SOUND_PLAYER == "winsound":
            winsound.PlaySound(sound_file_path, winsound.SND_FILENAME)
        else:
            self.logger.warning("No sound library available. Skipping sound.")

    def open_in_browser(self, url):
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
        match = re.search(r"Reward:\s*(?:US\$|\$)?\s*(\d+\.?\d*)", text, re.IGNORECASE)
        try:
            return float(match.group(1)) if match else 0.0
        except (ValueError, IndexError):
            return 0.0

    def _log_all_entries(self, entries):
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
        """A centralized, thread-safe method to process a newly found job."""

        with self._seen_jobs_lock:
            if job_id in self._seen_jobs_session:
                return
            self._seen_jobs_session.add(job_id)

        min_reward = self.config.get("Watcher", "min_reward")
        if min_reward > 0.0 and reward < min_reward:
            self.logger.info(
                f"Job '{title}' (US$ {reward:.2f}) ignored due to min_reward filter."
            )
            return

        self.state.total_new_entries_found += 1
        self.session_new_entries += 1
        self.session_total_value += reward

        self.logger.info(
            f"New job via {source}: {title.split('|')[0].strip()} (US$ {reward:.2f})"
        )
        self.show_notification(
            message=title,
            title="New Gengo Job Available!",
            play_sound=True,
            open_link=True,
            url=url,
        )

        self.state.last_seen_link = url
        self.state.save_state()

    def _process_feed_entries(self, entries):
        if not entries:
            return

        self._log_all_entries(entries)

        new_entries = []
        for entry in entries:
            link = entry.get("link")
            if not link:
                continue
            if link == self.state.last_seen_link:
                break
            new_entries.append(entry)

        if not new_entries:
            return

        for entry in reversed(new_entries):
            title = entry.get("title", "No Title")
            url = entry.get("link")
            try:
                job_id = int(url.split("/jobs/")[1].strip("/"))
                reward = self._extract_reward(entry)
                self._process_new_job(job_id, title, reward, url, source="RSS")
            except (ValueError, IndexError):
                self.logger.warning(f"Could not parse job ID from RSS link: {url}")

    def fetch_rss(self):
        headers = {}
        if self.config.get("Watcher", "use_custom_user_agent"):
            email = self.config.get("Network", "user_agent_email")
            headers["User-Agent"] = f"GengoWatcher/{__version__} ({email})"
        try:
            feed = feedparser.parse(
                self.config.get("Watcher", "feed_url"), request_headers=headers
            )
            if feed.bozo:
                self.logger.error(f"Feed Error: {feed.bozo_exception}")
                return None
            return feed
        except Exception as e:
            self.logger.error(f"RSS Error: {e}")
            return None

    def _run_websocket_monitor(self):
        # Add this check at the very beginning
        user_session = self.config.get("WebSocket", "user_session")
        if user_session == "REPLACE_WITH_YOUR_SESSION_TOKEN":
            self.logger.warning(
                "WebSocket monitor disabled: Please set 'user_session' in config.ini."
            )
            self.websocket_status = "Disabled"
            return

        """The main loop for the WebSocket connection, designed to run in a thread."""

        async def websocket_logic():
            ws_url = "wss://live-dashboard.gengo.com"
            self.websocket_status = "Connecting"

            try:
                async with websockets.connect(ws_url) as websocket:
                    self.websocket_status = "Authenticating"
                    auth_payload = {
                        "user_id": self.config.get("WebSocket", "user_id"),
                        "user_session": self.config.get("WebSocket", "user_session"),
                    }
                    await websocket.send(json.dumps(auth_payload))

                    self.websocket_status = "Live"
                    self.logger.info("WebSocket connection is live and listening.")

                    async for message in websocket:
                        data = json.loads(message)
                        if data.get("type") == "available_collection":
                            job = data.get("collection", {})
                            job_id = job.get("id")
                            if job_id:
                                reward = float(job.get("rewards", 0.0))
                                title = f"{job.get('lc_src')} > {job.get('lc_tgt')}"
                                url = f"https://gengo.com/t/jobs/details/{job_id}"
                                self._process_new_job(
                                    job_id, title, reward, url, source="WebSocket"
                                )

            except (
                websockets.exceptions.ConnectionClosed,
                ConnectionRefusedError,
            ) as e:
                self.logger.warning(f"WebSocket disconnected: {e}")
            except Exception as e:
                self.logger.error(f"WebSocket error: {e}")

        # --- REVISED SYNCHRONOUS WRAPPER ---
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        while not self.shutdown_event.is_set():
            try:
                loop.run_until_complete(websocket_logic())

                if self.shutdown_event.is_set():
                    break

                self.websocket_status = "Offline"
                self.logger.info(
                    "WebSocket connection closed. Reconnecting in 20 seconds..."
                )
                if self.shutdown_event.wait(20):
                    break

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"Error in WebSocket runner: {e}")
                if self.shutdown_event.wait(20):
                    break

        loop.close()
        self.logger.info("WebSocket monitor thread stopped.")
        self.websocket_status = "Stopped"

    def run(self):
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
        """This is the original 'run' method, now dedicated to RSS checking."""
        self.logger.info("RSS monitor thread started.")
        if not self.state.last_seen_link:
            self.current_action = "Priming feed"
            initial_feed = self.fetch_rss()
            if initial_feed and initial_feed.entries:
                self.state.last_seen_link = initial_feed.entries[0].get("link")
                self.logger.info("Initial RSS feed primed successfully.")
                self.state.save_state()

        while not self.shutdown_event.is_set():
            is_paused = os.path.exists(self.PAUSE_FILE)
            time_to_next_check = self.next_check_time - time.time()
            wait_duration = max(0, time_to_next_check)

            triggered = self.check_now_event.wait(timeout=wait_duration)
            if self.shutdown_event.is_set():
                break

            if triggered or time.time() >= self.next_check_time:
                self.check_now_event.clear()

                if is_paused:
                    self.current_action = "Paused"
                    wait_time = 5
                else:
                    self.current_action = "Fetching RSS"
                    feed = self.fetch_rss()
                    if feed is None:
                        self.failure_count += 1
                        wait_time = min(
                            self.config.get("Watcher", "check_interval")
                            * (2**self.failure_count),
                            self.config.get("Network", "max_backoff"),
                        )
                        self.current_action = f"RSS Backoff ({int(wait_time)}s)"
                    else:
                        if self.failure_count > 0:
                            self.logger.info("RSS Connection re-established.")
                        self.failure_count = 0
                        self.last_check_time = datetime.datetime.now()
                        self.current_action = "Processing RSS"
                        self._process_feed_entries(feed.entries)
                        wait_time = self.config.get("Watcher", "check_interval")
                        self.current_action = "Waiting"
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
