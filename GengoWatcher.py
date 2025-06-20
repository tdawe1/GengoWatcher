__version__ = "1.1.2"
__release_date__ = "2025-06-21"

import feedparser
import time
import webbrowser
import os
import winsound
from win10toast import ToastNotifier
import signal
import sys
import threading
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import configparser
import datetime
import subprocess
import colorama
from colorama import Fore, Style
colorama.init()

class ColoredFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': Style.DIM + Fore.CYAN,
        'INFO': Fore.CYAN,
        'WARNING': Fore.YELLOW,
        'ERROR': Fore.RED,
        'CRITICAL': Style.BRIGHT + Fore.RED
    }
    RESET = Style.RESET_ALL

    def format(self, record):
        log_message = super().format(record)
        return self.COLORS.get(record.levelname, self.RESET) + log_message + self.RESET

class GengoWatcher:
    CONFIG_FILE = "config.ini"
    PAUSE_FILE = "gengowatcher.pause"

    DEFAULT_CONFIG = {
        "Watcher": {
            "feed_url": "https://www.theguardian.com/uk/rss",
            "check_interval": "31",
            "enable_notifications": "True",
            "use_custom_user_agent": "False",
            "enable_sound": "True"  
        },
        "Paths": {
            "sound_file": r"C:\path\to\your\sound.wav",
            "vivaldi_path": r"C:\path\to\your\vivaldi.exe",
            "log_file": "rss_check_log.txt",
            "notification_icon_path": ""
        },
        "Logging": {
            "log_max_bytes": "1000000",
            "log_backup_count": "3"
        },
        "Network": {
            "max_backoff": "300",
            "user_agent_email": "your_email@example.com"
        },
        "State": {
            "last_seen_link": "",
            "total_new_entries_found": "0"
        }
    }

    def __init__(self):
        self.config = {}
        self._config_parser = configparser.ConfigParser()
        self.last_seen_link = None
        self.shutdown_event = threading.Event()
        self.check_now_event = threading.Event()
        self.last_check_time = None
        self.notifier = ToastNotifier()
        self.total_new_entries_found = 0
        self.failure_count = 0
        self.current_action = "Initializing"

        self._load_config()
        self.last_seen_link = self.config["State"]["last_seen_link"] if self.config["State"]["last_seen_link"] else None
        self.total_new_entries_found = int(self.config["State"]["total_new_entries_found"])

        self._setup_logging()
        self._setup_signal_handlers()
        self.last_error_message = "None"

        self.logger.info("-" * 40)
        self.logger.info("GengoWatcher Initialized with Settings:")
        for section_name, section_dict in self.config.items():
            if isinstance(section_dict, dict):
                for key, value in section_dict.items():
                    if key in ["sound_file", "vivaldi_path", "log_file", "notification_icon_path"]:
                        self.logger.info(f"   {section_name}.{key}: [PATH_HIDDEN]")
                    elif key == "user_agent_email":
                        if "@" in value:
                            parts = value.split("@")
                            self.logger.info(f"   {section_name}.{key}: {parts[0][:2]}...@{parts[1]}")
                        else:
                            self.logger.info(f"   {section_name}.{key}: [EMAIL_HIDDEN]")
                    else:
                        self.logger.info(f"   {section_name}.{key}: {value}")
            else:
                self.logger.info(f"   {section_name}: {self.config[section_name]}")
        self.logger.info("-" * 40)
        self.logger.info("Command listener active. Type 'help' for commands.")
        self.start_time = time.time()


    def _create_default_config(self):
        parser = configparser.ConfigParser()
        for section, settings in self.DEFAULT_CONFIG.items():
            parser.add_section(section)
            for key, value in settings.items():
                parser.set(section, key, value)

        with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
            parser.write(f)

        print(f"\nCreated default '{self.CONFIG_FILE}'.")
        print("Please edit this file with your specific paths and preferences, then restart the script.")
        print("Ensure 'feed_url' has your correct RSS key.")
        print("Remember to change 'user_agent_email' if 'use_custom_user_agent' is enabled.")
        sys.exit(0)

    def _load_config(self):
        if not Path(self.CONFIG_FILE).is_file():
            self._create_default_config()

        self._config_parser.read(self.CONFIG_FILE, encoding='utf-8')

        try:
            self.config["Watcher"] = {
                "feed_url": self._config_parser.get("Watcher", "feed_url"),
                "check_interval": self._config_parser.getint("Watcher", "check_interval"),
                "enable_notifications": self._config_parser.getboolean("Watcher", "enable_notifications"),
                "use_custom_user_agent": self._config_parser.getboolean("Watcher", "use_custom_user_agent", fallback=False),
                "enable_sound": self._config_parser.getboolean("Watcher", "enable_sound", fallback=True)  # Load enable_sound
            }

            notification_icon_path_str = self._config_parser.get("Paths", "notification_icon_path").strip()
            self.config["Paths"] = {
                "sound_file": Path(self._config_parser.get("Paths", "sound_file")),
                "vivaldi_path": Path(self._config_parser.get("Paths", "vivaldi_path")),
                "log_file": Path(self._config_parser.get("Paths", "log_file")),
                "notification_icon_path": Path(notification_icon_path_str) if notification_icon_path_str else None
            }

            self.config["Logging"] = {
                "log_max_bytes": self._config_parser.getint("Logging", "log_max_bytes"),
                "log_backup_count": self._config_parser.getint("Logging", "log_backup_count")
            }

            self.config["Network"] = {
                "max_backoff": self._config_parser.getint("Network", "max_backoff"),
                "user_agent_email": self._config_parser.get("Network", "user_agent_email", fallback=self.DEFAULT_CONFIG["Network"]["user_agent_email"])
            }

            self.config["State"] = {
                "last_seen_link": self._config_parser.get("State", "last_seen_link", fallback=""),
                "total_new_entries_found": self._config_parser.getint("State", "total_new_entries_found", fallback=0)
            }

        except configparser.Error as e:
            print(f"Error reading configuration file '{self.CONFIG_FILE}': {e}")
            print("Please check the file's format and content. If unsure, delete it to regenerate a default.")
            sys.exit(1)

    def _save_runtime_state(self):
        if not self._config_parser.has_section("State"):
            self._config_parser.add_section("State")

        self._config_parser.set("State", "last_seen_link", self.last_seen_link if self.last_seen_link else "")
        self._config_parser.set("State", "total_new_entries_found", str(self.total_new_entries_found))

        if not self._config_parser.has_section("Watcher"):
            self._config_parser.add_section("Watcher")
        self._config_parser.set("Watcher", "enable_sound", str(self.config["Watcher"].get("enable_sound", True)))
        self._config_parser.set("Watcher", "enable_notifications", str(self.config["Watcher"].get("enable_notifications", True)))

        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                self._config_parser.write(f)
            self.logger.debug("Runtime state saved.")
        except IOError as e:
            self.logger.error(f"Failed to save runtime state to {self.CONFIG_FILE}: {e}")

    def _setup_logging(self):
        self.logger = logging.getLogger("GengoWatcher")
        self.logger.setLevel(logging.INFO)

        if not self.logger.handlers:
            file_handler = RotatingFileHandler(
                self.config["Paths"]["log_file"],
                maxBytes=self.config["Logging"]["log_max_bytes"],
                backupCount=self.config["Logging"]["log_backup_count"],
                encoding="utf-8"
            )
            file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)

            console_handler = logging.StreamHandler(sys.stdout)
            colored_formatter = ColoredFormatter('%(asctime)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(colored_formatter)
            self.logger.addHandler(console_handler)

    def _setup_signal_handlers(self):
        signal.signal(signal.SIGINT, self.handle_exit)

    def _smart_wait(self, total_seconds: float) -> bool:
        """Waits up to total_seconds for shutdown or manual check."""
        # Wait for either shutdown or manual check, but only break loop if shutdown_event is set
        self.check_now_event.wait(timeout=total_seconds)
        return self.shutdown_event.is_set()

    def handle_exit(self, signum=None, frame=None):
        if not self.shutdown_event.is_set():
            self.logger.info("Shutdown signal received.")
            self.shutdown_event.set()
            self.logger.debug("Saving runtime state...")
            self._save_runtime_state()
            self.logger.debug("Shutdown complete.")
        sys.exit(0)

    def play_sound(self):
        try:
            if not self.config["Watcher"].get("enable_sound", True):
                self.logger.debug("Sound is disabled in config.")
                return
            if self.config["Paths"]["sound_file"].is_file():
                winsound.PlaySound(str(self.config["Paths"]["sound_file"]), winsound.SND_FILENAME)
            else:
                winsound.MessageBeep()
                self.logger.warning(f"Sound file not found: {self.config['Paths']['sound_file']}. Playing default beep.")
        except Exception as e:
            self.logger.error(f"Sound error: {e}")

    def play_sound_async(self):
        threading.Thread(target=self.play_sound, daemon=True).start()

    def open_in_vivaldi(self, url):
        vivaldi_path = self.config["Paths"]["vivaldi_path"]

        if not vivaldi_path or not vivaldi_path.is_file():
            self.logger.warning(f"Vivaldi path invalid or not set: {vivaldi_path}")
            return

        try:
            # Pass executable and args as a list to avoid shell quoting issues
            subprocess.Popen([str(vivaldi_path), f'--app={url}'])
            self.logger.debug(f"Opened URL in Vivaldi: {url}")
        except Exception as e:
            self.logger.error(f"Failed to open URL in Vivaldi: {e}")

    def notify(self, title, message):
        if not self.config["Watcher"]["enable_notifications"]:
            self.logger.debug("Notifications are disabled in config.")
            return

        icon = None
        if self.config["Paths"]["notification_icon_path"] and self.config["Paths"]["notification_icon_path"].is_file():
            icon = str(self.config["Paths"]["notification_icon_path"])

        try:
            self.notifier.show_toast(title, message, icon_path=icon, duration=8, threaded=True)
            self.logger.debug(f"Notification shown: {title} - {message}")
        except Exception as e:
            self.logger.error(f"Notification error: {e}")
            
    def print_status(self):
        status = "Running" if not self.shutdown_event.is_set() else "Stopped"
        new_posts_count = self.total_new_entries_found
        last_check = self.last_check_time.strftime("%Y-%m-%d %H:%M:%S") if self.last_check_time else "Never"
        polling_interval = self.config["Watcher"]["check_interval"]
        notif_enabled = self.config["Watcher"]["enable_notifications"]
        sound_enabled = self.config["Watcher"].get("enable_sound", True)
        vivaldi_configured = bool(self.config["Paths"]["vivaldi_path"] and self.config["Paths"]["vivaldi_path"].is_file())
        last_error = getattr(self, 'last_error_message', "None")
        uptime_seconds = int(time.time() - self.start_time) if hasattr(self, 'start_time') else 0
        uptime_str = str(datetime.timedelta(seconds=uptime_seconds))
        version = globals().get("__version__", "?")
        release_date = globals().get("__release_date__", "?")
        current_action = getattr(self, 'current_action', "Idle")

        print("\n=== GengoWatcher Status ===")
        print(f"Version:              {version}")
        print(f"Release date:         {release_date}")
        print(f"Status:               {status}")
        print(f"Current action:       {current_action}")
        print(f"New posts detected:   {new_posts_count}")
        print(f"Last check time:      {last_check}")
        print(f"Polling interval (s): {polling_interval}")
        print(f"Notifications:        {'Enabled' if notif_enabled else 'Disabled'}")
        print(f"Sound:                {'Enabled' if sound_enabled else 'Disabled'}")
        print(f"Vivaldi path set:     {'Yes' if vivaldi_configured else 'No'}")
        print(f"Last error logged:    {last_error}")
        print(f"Uptime:               {uptime_str}")
        print("===========================\n")


    def fetch_rss(self):
        headers = {}
        if self.config["Watcher"]["use_custom_user_agent"]:
            user_agent = f"GengoWatcher/1.0 (mailto:{self.config['Network']['user_agent_email']})"
            headers['User-Agent'] = user_agent

        url = self.config["Watcher"]["feed_url"]

        try:
            feed = feedparser.parse(url, request_headers=headers)
            if feed.bozo:
                self.logger.warning(f"Malformed feed or parsing error: {feed.bozo_exception}")
                if not hasattr(feed, 'entries') or not feed.entries:
                    return None  # Treat as failure only if entries are truly missing
            return feed
        except Exception as e:
            self.logger.error(f"RSS fetch error: {e}")
            self.last_error_message = str(e) # Store the error
            return None

    def process_entries(self, entries):
        """
        Processes entries from the RSS feed to find and handle new items.

        This method iterates through the feed entries (which are newest-first),
        collects all entries until it finds the last one it has already seen,
        and then processes the collected new entries in chronological order.
        """
        if not entries:
            self.logger.info("Feed was fetched, but it contains no entries to process.")
            return

        # Collect all entries that are newer than our last_seen_link
        new_entries_to_process = []
        for entry in entries:  # feedparser entries are sorted newest to oldest
            link = entry.get("link")
            if not link:
                self.logger.warning("Found an entry with no link, skipping.")
                continue

            if link == self.last_seen_link:
                # We've found the last job we processed. Everything before this is new.
                break
            
            # This is a new entry, add it to our list
            new_entries_to_process.append(entry)

        if not new_entries_to_process:
            self.logger.info("No new entries detected since last check.")
            return

        # We have new entries. Log the count and process them.
        entry_count = len(new_entries_to_process)
        plural = "entries" if entry_count > 1 else "entry"
        self.logger.info(f"Discovered {entry_count} new {plural}. Processing...")

        # Reverse the list so we process from oldest-new to newest-new
        for entry in reversed(new_entries_to_process):
            title = entry.get("title", "(No Title)")
            link = entry.get("link")  # We know this exists from the check above

            self.logger.info(f"  -> New Job: '{title}'")
            self.total_new_entries_found += 1

            # Trigger combined notification and action
            self.show_notification(
                message=title,
                title="New Gengo Job Available!",
                play_sound=True,
                open_link=True,
                url=link
            )

        # IMPORTANT: After processing, update the last_seen_link to the newest one
        # from this batch, which is the first one we saw in the original list.
        self.last_seen_link = new_entries_to_process[0].get("link")

        self.logger.info(f"Processing complete. Total jobs found this session: {self.total_new_entries_found}")
        
        # Persist the new state to the config file for the next run
        self._save_runtime_state()

    def show_notification(self, message, title="GengoWatcher", play_sound=False, open_link=False, url=None):
        self.notify(title, message)
        if play_sound:
            self.play_sound_async()
        if open_link and url:
            self.open_in_vivaldi(url)

    def run(self):
        self.logger.info("Starting main RSS check loop...")
        self.current_action = "Starting main loop"
        backoff = 31
        max_backoff = self.config["Network"]["max_backoff"]
        is_paused = False

        while not self.shutdown_event.is_set():
            try:
                # --- Pause/Resume Logic ---
                if os.path.exists(self.PAUSE_FILE):
                    if not is_paused:
                        msg = f"Pause file '{self.PAUSE_FILE}' detected. Pausing RSS checks."
                        self.logger.info(msg)
                        print(f"[PAUSED] {msg}")
                        is_paused = True
                    self.current_action = "Paused (waiting for resume)"
                    while os.path.exists(self.PAUSE_FILE) and not self.shutdown_event.is_set():
                        time.sleep(1)
                    if self.shutdown_event.is_set():
                        break
                    msg = f"Pause file '{self.PAUSE_FILE}' removed. Resuming RSS checks."
                    self.logger.info(msg)
                    print(f"[RESUMED] {msg}")
                    is_paused = False
                    self.current_action = "Resumed (preparing to fetch RSS)"
                    continue
                # --- End Pause/Resume Logic ---
                self.current_action = "Fetching RSS feed"
                self.logger.info("Fetching RSS feed...")
                feed = self.fetch_rss()
                if feed is None:
                    self.logger.warning(f"RSS fetch failed or no entries. Failure count: {self.failure_count + 1}")
                    self.failure_count += 1
                    wait_time = min(backoff, max_backoff)
                    self.logger.info(f"Backing off for {wait_time} seconds.")
                    self.current_action = f"Waiting {wait_time}s (backoff after failure)"
                    if self._smart_wait(wait_time):
                        break
                    self.check_now_event.clear()
                    backoff *= 2
                    continue
                self.last_check_time = datetime.datetime.now()
                self.failure_count = 0
                backoff = 31
                if not feed.entries:
                    self.logger.info("RSS feed fetched successfully but no new entries found.")
                    wait_seconds = self.config["Watcher"]["check_interval"]
                    self.logger.info(f"Waiting {wait_seconds} seconds before next check.")
                    self.current_action = f"Waiting {wait_seconds}s (no new entries)"
                    self.check_now_event.clear()
                    if self._smart_wait(wait_seconds):
                        break
                    continue
                self.current_action = f"Processing {len(feed.entries)} new entries"
                self.process_entries(feed.entries)
                wait_seconds = self.config["Watcher"]["check_interval"]
                self.logger.info(f"Next check in {wait_seconds} seconds.")
                self.current_action = f"Waiting {wait_seconds}s (after processing entries)"
                self.check_now_event.clear()
                if self._smart_wait(wait_seconds):
                    break
            except Exception as e:
                self.logger.error(f"Unexpected error: {e}")
                self.last_error_message = str(e)
                self.current_action = f"Error: {e}"
                time.sleep(10)
        self.logger.info("Exiting main loop.")
        self.current_action = "Stopped"

if __name__ == "__main__":
    watcher = GengoWatcher()

    # Start the main watcher loop in a daemon thread so it doesn't block
    watcher_thread = threading.Thread(target=watcher.run, daemon=True, name="WatcherThread")
    watcher_thread.start()

    print("Type 'help' for commands. Type 'exit' to quit.")

    try:
        while not watcher.shutdown_event.is_set():
            cmd = input(">>> ").strip().lower()

            if cmd in ("exit", "quit", "stop", "end", "ex", "qu"):
                print("Exiting...")
                watcher.shutdown_event.set()
                break

            elif cmd == "check":
                watcher.logger.info("Manual check requested via command.")
                watcher.check_now_event.set()

            elif cmd == "status":
                watcher.print_status()

            elif cmd == "pause":
                if not os.path.exists(watcher.PAUSE_FILE):
                    with open(watcher.PAUSE_FILE, "w") as f:
                        f.write("Paused by user command.\n")
                    print(f"Watcher paused. Enter 'resume' to continue.")
                    watcher.logger.info(f"Pause file '{watcher.PAUSE_FILE}' created by user command.")
                else:
                    print(f"Watcher is already paused (pause file exists).")

            elif cmd == "resume":
                if os.path.exists(watcher.PAUSE_FILE):
                    try:
                        os.remove(watcher.PAUSE_FILE)
                        print(f"Watcher resumed.")
                        watcher.logger.info(f"Pause file '{watcher.PAUSE_FILE}' removed by user command.")
                    except Exception as e:
                        print(f"Failed to remove pause file: {e}")
                        watcher.logger.error(f"Failed to remove pause file: {e}")
                else:
                    print(f"Watcher is not paused (pause file does not exist).")

            elif cmd == "togglesound":
                current = watcher.config["Watcher"].get("enable_sound", True)
                new_val = not current
                watcher.config["Watcher"]["enable_sound"] = new_val
                watcher._config_parser.set("Watcher", "enable_sound", str(new_val))
                watcher._save_runtime_state()
                print(f"Sound {'enabled' if new_val else 'disabled'}.")
                watcher.logger.info(f"Sound {'enabled' if new_val else 'disabled'} by user command.")

            elif cmd == "togglenotifications":
                current = watcher.config["Watcher"].get("enable_notifications", True)
                new_val = not current
                watcher.config["Watcher"]["enable_notifications"] = new_val
                watcher._config_parser.set("Watcher", "enable_notifications", str(new_val))
                watcher._save_runtime_state()
                print(f"Notifications {'enabled' if new_val else 'disabled'}.")
                watcher.logger.info(f"Notifications {'enabled' if new_val else 'disabled'} by user command.")

            elif cmd == "help":
                print("Commands:\n  check   - Check RSS immediately\n  status  - Show status\n  pause   - Pause RSS checks\n  resume  - Resume RSS checks\n  togglesound - Toggle sound on/off\n  togglenotifications - Toggle notifications on/off\n  restart - Restart the script\n  reloadconfig - Reload the configuration file\n  exit    - Quit\n  help    - Show this message\n  notifytest - Test the notification functionality")

            elif cmd == "notifytest":
                watcher.logger.info("Notification test command triggered.")
                test_url = "https://gengo.com/t/jobs/status/available" # Example URL
                watcher.show_notification(
                    "This is a notification test!",
                    title="GengoWatcher Test",
                    play_sound=True,
                    open_link=True,
                    url=test_url
                )

            elif cmd == "restart":
                print("Restarting GengoWatcher...")
                watcher.logger.info("Restart command received. Restarting script.")
                watcher.shutdown_event.set()
                watcher._save_runtime_state()
                watcher_thread.join(timeout=5)
                python = sys.executable
                os.execv(python, [python] + sys.argv)

            elif cmd == "reloadconfig":
                try:
                    watcher._load_config()
                    watcher._setup_logging()
                    print("Configuration reloaded.")
                    watcher.logger.info("Configuration reloaded by user command.")
                except Exception as e:
                    print(f"Failed to reload configuration: {e}")
                    watcher.logger.error(f"Failed to reload configuration: {e}")

            else:
                print(f"Unknown command: {cmd}")

    except KeyboardInterrupt:
        watcher.logger.info("Keyboard interrupt received in main thread.")
        watcher.handle_exit() # Ensure graceful shutdown on Ctrl+C

    # Wait for the watcher thread to finish if it's not already
    watcher_thread.join(timeout=5)
    watcher.logger.info("Program exited cleanly.")
    sys.exit(0)

