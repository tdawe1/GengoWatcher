__version__ = "1.2.1" # Incremented version
__release_date__ = "2025-06-23"

import feedparser
import time
import webbrowser
from plyer import notification
import os
import signal
import sys
import threading
import logging
from pathlib import Path
import datetime
import subprocess
import re
import csv

# Tier 1 Fix: Make sound cross-platform compatible
try:
    # Use a cross-platform library if available
    from playsound import playsound
    SOUND_PLAYER = "playsound"
except ImportError:
    try:
        # Fallback to winsound on Windows
        import winsound
        SOUND_PLAYER = "winsound"
    except ImportError:
        # If no sound library is available
        SOUND_PLAYER = "none"

# Local imports
from config import AppConfig
from state import AppState

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

        self._all_entries_log_file = None
        self._csv_writer = None
        if self.config.get("Logging", "log_all_entries_enabled"):
            self._setup_csv_logging()

        self.logger.info(f"GengoWatcher v{__version__} initialized.")

    def handle_exit(self, signum=None, frame=None):
        if not self.shutdown_event.is_set():
            self.logger.info("Shutdown initiated. Saving state...")
            self.shutdown_event.set()
            # Tier 1 Fix: State is saved via the AppState object
            self.state.save_state()
            self.config.save_config()

    def _setup_csv_logging(self):
        # Tier 3 Feature: Implement All-Entries CSV Log
        try:
            log_path = Path(self.config.get("Paths", "all_entries_log"))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Open file in append mode, create if it doesn't exist
            self._all_entries_log_file = open(log_path, 'a', newline='', encoding='utf-8')
            self._csv_writer = csv.writer(self._all_entries_log_file)
            
            # Write header if the file is new/empty
            if log_path.stat().st_size == 0:
                self._csv_writer.writerow(["timestamp", "title", "reward", "link", "summary"])
        except IOError as e:
            self.logger.error(f"Could not open all_entries_log file: {e}")
            self._all_entries_log_file = None
            self._csv_writer = None

    def play_sound(self):
        # Tier 1 Fix: Cross-platform sound handling
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
            self.logger.warning("No sound library installed. Skipping sound.")

    def open_in_browser(self, url):
        try:
            browser_path_str = self.config.get("Paths", "browser_path")
            if not browser_path_str or not Path(browser_path_str).is_file():
                webbrowser.open(url)
            else:
                args = [arg.format(url=url) for arg in self.config.get("Paths", "browser_args").split()]
                subprocess.Popen([str(browser_path_str)] + args)
        except Exception as e:
            self.logger.error(f"Browser Error: {e}")

    def show_notification(self, message, title="GengoWatcher", play_sound=False, open_link=False, url=None):
        if self.config.get("Watcher", "enable_notifications"):
            try:
                icon_path = self.config.get("Paths", "notification_icon_path")
                app_icon = str(icon_path) if Path(icon_path).is_file() else None
                notification.notify(title=title, message=message, app_name='GengoWatcher', app_icon=app_icon, timeout=8)
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
        # Tier 3 Feature: Log all entries to CSV if enabled
        if not self._csv_writer:
            return
        
        timestamp = datetime.datetime.now().isoformat()
        for entry in entries:
            self._csv_writer.writerow([
                timestamp,
                entry.get("title", "N/A"),
                self._extract_reward(entry),
                entry.get("link", "N/A"),
                entry.get("summary", "N/A")
            ])
        # Ensure data is written to disk
        self._all_entries_log_file.flush()

    def _process_feed_entries(self, entries):
        if not entries:
            return

        self._log_all_entries(entries)

        new_entries = []
        for entry in entries:
            if entry.get("link") == self.state.last_seen_link:
                break
            new_entries.append(entry)
        
        if not new_entries:
            return

        min_reward = self.config.get("Watcher", "min_reward")
        processed_count = 0
        for entry in reversed(new_entries):
            reward = self._extract_reward(entry)
            if min_reward > 0.0 and reward < min_reward:
                continue
            
            processed_count += 1
            self.state.total_new_entries_found += 1 # Tier 1 Fix: Update state object
            self.session_new_entries += 1
            self.session_total_value += reward
            
            title = entry.get("title", "No Title")
            self.logger.info(f"New job: {title.split('|')[0].strip()} (US$ {reward:.2f})")
            self.show_notification(
                message=title, 
                title="New Gengo Job Available!", 
                play_sound=True, 
                open_link=True, 
                url=entry.get("link")
            )

        if processed_count > 0:
            self.state.last_seen_link = new_entries[0].get("link") # Tier 1 Fix: Update state object
            self.state.save_state()

    def fetch_rss(self):
        headers = {}
        if self.config.get("Watcher", "use_custom_user_agent"):
            email = self.config.get("Network", "user_agent_email")
            headers['User-Agent'] = f"GengoWatcher/{__version__} ({email})"
        
        try:
            feed = feedparser.parse(self.config.get("Watcher", "feed_url"), request_headers=headers)
            if feed.bozo:
                self.logger.error(f"Feed Error: {feed.bozo_exception}")
                return None
            return feed
        except Exception as e:
            self.logger.error(f"RSS Error: {e}")
            return None

    def run(self):
        self.logger.info("Watcher thread started.")
        if not self.state.last_seen_link:
            self.current_action = "Priming feed"
            initial_feed = self.fetch_rss()
            if initial_feed and initial_feed.entries:
                self.state.last_seen_link = initial_feed.entries[0].get("link")
                self.logger.info("Initial feed primed successfully.")
                self.state.save_state()
        
        # Tier 3 Fix: Use event.wait() for efficient idling
        while not self.shutdown_event.is_set():
            is_paused = os.path.exists(self.PAUSE_FILE)
            time_to_next_check = self.next_check_time - time.time()
            wait_duration = max(0, time_to_next_check)

            # Wait for either the check interval to pass, or a check/shutdown event
            triggered = self.shutdown_event.wait(timeout=wait_duration)
            if triggered: break # Exit loop if shutdown was called

            if self.check_now_event.is_set() or time.time() >= self.next_check_time:
                self.check_now_event.clear()
                
                if is_paused:
                    self.current_action = "Paused"
                    wait_time = 5 # Check for pause file changes every 5s
                else:
                    self.current_action = "Fetching"
                    feed = self.fetch_rss()
                    if feed is None:
                        self.failure_count += 1
                        wait_time = min(self.config.get("Watcher", "check_interval") * (2**self.failure_count), self.config.get("Network", "max_backoff"))
                        self.current_action = f"Backoff ({int(wait_time)}s)"
                    else:
                        if self.failure_count > 0: self.logger.info("Connection re-established.")
                        self.failure_count = 0
                        self.last_check_time = datetime.datetime.now()
                        self.current_action = "Processing"
                        self._process_feed_entries(feed.entries)
                        wait_time = self.config.get("Watcher", "check_interval")
                        self.current_action = "Waiting"
                self.next_check_time = time.time() + wait_time

    def run_notify_test(self):
        self.logger.info("Sending a test notification...")
        self.show_notification(
            message="This is a test notification!",
            title="GengoWatcher Test",
            play_sound=True,
            open_link=True,
            url="https://gengo.com/t/jobs/status/available"
        )

    def restart(self):
        self.handle_exit()
        python = sys.executable
        os.execv(python, [python] + sys.argv)