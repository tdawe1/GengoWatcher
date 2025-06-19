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
import msvcrt

class GengoWatcher:
    CONFIG_FILE = "config.ini"

    # template ini settings
    DEFAULT_CONFIG = {
        "Watcher": {
            "feed_url": "https://www.theguardian.com/uk/rss", #the feed you want to watch
            "check_interval": "31", #seconds
            "enable_notifications": "True",
            "use_custom_user_agent": "False" #use if RSS feed rejects feedparser
        },
        "Paths": {
            "sound_file": r"C:\path\to\your\sound.wav",
            "vivaldi_path": r"C:\path\to\your\vivaldi.exe", #will open default browser if no vivaldi
            "log_file": "rss_check_log.txt",
            "notification_icon_path": ""
        },
        "Logging": {
            "log_max_bytes": "1000000",
            "log_backup_count": "3"
        },
        "Network": {
            "max_backoff": "300",
            "user_agent_email": "your_email@example.com" # Required if use_custom_user_agent is True
        },
        "State": { 
            "last_seen_link": "", # Persisted across runs
            "total_new_entries_found": "0" 
        }
    }

    def __init__(self):
        self.config = {}
        self.last_seen_link = None
        self.shutdown_event = threading.Event()
        self.check_now_event = threading.Event()
        self.last_check_time = None
        self.notifier = ToastNotifier()
        self.total_new_entries_found = 0
        self.failure_count = 0

        self._load_config()
        self.last_seen_link = self.config["State"]["last_seen_link"] if self.config["State"]["last_seen_link"] else None
        self.total_new_entries_found = self.config["State"]["total_new_entries_found"]

        self._setup_logging()
        self._setup_signal_handlers()

        self.command_thread = threading.Thread(target=self.command_listener, name="CommandListener")
        self.command_thread.start()

        self.logger.info("-" * 40)
        self.logger.info("GengoWatcher Initialized with Settings:")
        for section_name, section_dict in self.config.items():
            if isinstance(section_dict, dict):
                for key, value in section_dict.items():
                    if key in ["sound_file", "vivaldi_path", "log_file", "notification_icon_path"]:
                        self.logger.info(f"  {section_name}.{key}: [PATH_HIDDEN]")
                    elif key == "user_agent_email":
                        if "@" in value:
                            parts = value.split("@")
                            self.logger.info(f"  {section_name}.{key}: {parts[0][:2]}...@{parts[1]}")
                        else:
                            self.logger.info(f"  {section_name}.{key}: [EMAIL_HIDDEN]")
                    else:
                        self.logger.info(f"  {section_name}.{key}: {value}")
            else:
                self.logger.info(f"  {section_name}: {self.config[section_name]}")
        self.logger.info("-" * 40)
        self.logger.info("Command listener active. Type 'help' for commands.")

    def _create_default_config(self):
        """Creates a default ini if none found."""
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
        """Loads settings from config.ini."""
        parser = configparser.ConfigParser()

        if not Path(self.CONFIG_FILE).is_file():
            self._create_default_config()

        parser.read(self.CONFIG_FILE, encoding='utf-8')

        try:
            self.config["Watcher"] = {
                "feed_url": parser.get("Watcher", "feed_url"),
                "check_interval": parser.getint("Watcher", "check_interval"),
                "enable_notifications": parser.getboolean("Watcher", "enable_notifications"),
                "use_custom_user_agent": parser.getboolean("Watcher", "use_custom_user_agent", fallback=False)
            }

            notification_icon_path_str = parser.get("Paths", "notification_icon_path").strip()
            self.config["Paths"] = {
                "sound_file": Path(parser.get("Paths", "sound_file")),
                "vivaldi_path": Path(parser.get("Paths", "vivaldi_path")),
                "log_file": Path(parser.get("Paths", "log_file")),
                "notification_icon_path": Path(notification_icon_path_str) if notification_icon_path_str else None
            }

            self.config["Logging"] = {
                "log_max_bytes": parser.getint("Logging", "log_max_bytes"),
                "log_backup_count": parser.getint("Logging", "log_backup_count")
            }

            self.config["Network"] = {
                "max_backoff": parser.getint("Network", "max_backoff"),
                "user_agent_email": parser.get("Network", "user_agent_email", fallback=self.DEFAULT_CONFIG["Network"]["user_agent_email"])
            }
            
            self.config["State"] = {
                "last_seen_link": parser.get("State", "last_seen_link", fallback=""),
                "total_new_entries_found": parser.getint("State", "total_new_entries_found", fallback=0)
            }
            
        except configparser.Error as e:
            print(f"Error reading configuration file '{self.CONFIG_FILE}': {e}")
            print("Please check the file's format and content. If unsure, delete it to regenerate a default.")
            sys.exit(1)

    def _save_runtime_state(self):
        """Saves to config.ini."""
        parser = configparser.ConfigParser()
        parser.read(self.CONFIG_FILE, encoding='utf-8')

        if not parser.has_section("State"):
            parser.add_section("State")
        
        parser.set("State", "last_seen_link", self.last_seen_link if self.last_seen_link else "")
        parser.set("State", "total_new_entries_found", str(self.total_new_entries_found))

        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                parser.write(f)
            self.logger.debug("Runtime state saved.")
        except IOError as e:
            self.logger.error(f"Failed to save runtime state to {self.CONFIG_FILE}: {e}")


    def _setup_logging(self):
        """logging configuration set up"""
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
            console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)

    def _setup_signal_handlers(self):
        """ for graceful exit"""
        signal.signal(signal.SIGINT, self.handle_exit)

    def handle_exit(self, signum=None, frame=None):
        self.logger.info("Exiting script...")
        self._save_runtime_state()
        self.shutdown_event.set()

    def play_sound(self):
        """Alert sound via winsound."""
        try:
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
        """Opens a URL in Vivaldi or the default browser if Vivaldi path is not set."""
        if not self.config["Paths"]["vivaldi_path"] or not self.config["Paths"]["vivaldi_path"].is_file():
            self.logger.warning("Vivaldi path not set or invalid. Opening with default browser.")
            try:
                webbrowser.open_new_tab(url)
            except Exception as e:
                self.logger.error(f"Default browser open error: {e}")
            return

        try:
            webbrowser.register('vivaldi', None, webbrowser.BackgroundBrowser(str(self.config["Paths"]["vivaldi_path"])))
            webbrowser.get('vivaldi').open_new_tab(url)
        except Exception as e:
            self.logger.error(f"Vivaldi open error: {e}")

    def bring_vivaldi_to_foreground(self):
        try:
            os.system('powershell -command "$wshell = New-Object -ComObject WScript.Shell; $wshell.AppActivate(\'Vivaldi\')"')
        except Exception as e:
            self.logger.error(f"Failed to bring Vivaldi to foreground: {e}")

    def bring_vivaldi_to_foreground_async(self):
        threading.Thread(target=self.bring_vivaldi_to_foreground, daemon=True).start()

    def notify(self, title, url):
        if not self.config["Watcher"]["enable_notifications"]:
            self.logger.info(f"New entry found: '{title}' but notifications are disabled in config.")
            return

        self.logger.info(f"New entry: {title}")
        self.play_sound_async()

        try:
            icon_path_for_toast = str(self.config["Paths"]["notification_icon_path"]) if self.config["Paths"]["notification_icon_path"] else None

            self.notifier.show_toast(
                "New Entry Found",
                title,
                icon_path=icon_path_for_toast,
                duration=5,
                threaded=True
            )
        except Exception as e:
            self.logger.error(f"Notification error: {e}")

        threading.Thread(target=self.open_in_vivaldi, args=(url,), daemon=True).start()
        self.bring_vivaldi_to_foreground_async()

    def test_notify(self):
        """Sends a test notification."""
        test_title = "Test Notification"
        test_url = "https://gengo.com/t/jobs/status/available" # placeholder
        self.notify(test_title, test_url)
        self.logger.info("Test notification sent.")

    def display_help(self):
        help_message = """
Available Commands:
  help        - Display this help message.
  test        - Send a test desktop notification.
  status      - Show current watcher status (last checked, next check, total entries found, etc.).
  check_now   - Immediately trigger an RSS feed check.
  exit / quit - Stop the watcher and exit the script.
"""
        self.logger.info(help_message)

    def display_status(self):
        status_message = f"""
Watcher Status:
  Last seen link: {self.last_seen_link if self.last_seen_link else 'None (first run or not yet seen)'}
  Last checked: {self.last_check_time.strftime('%Y-%m-%d %H:%M:%S') if self.last_check_time else 'Not yet checked'}
  Next check in: {self.config["Watcher"]['check_interval']} seconds (or press 'check_now')
  Network failures: {self.failure_count}
  Total new entries found (this run/overall): {self.total_new_entries_found}
"""
        self.logger.info(status_message)


    def command_listener(self):
        """Listens for user commands in a non-blocking way using msvcrt."""
        current_command_line = ""
        self.logger.info("Command listener ready. Type commands and press 'Enter'.")
        
        while not self.shutdown_event.is_set():
            if msvcrt.kbhit():
                char = msvcrt.getch()
                try:
                    decoded_char = char.decode('utf-8')
                except UnicodeDecodeError:
                    continue 

                if decoded_char == '\r' or decoded_char == '\n':
                    print()
                    cmd = current_command_line.strip().lower()
                    current_command_line = ""
                    
                    if cmd == "help":
                        self.display_help()
                    elif cmd == "test":
                        self.test_notify()
                    elif cmd == "status":
                        self.display_status()
                    elif cmd == "check_now":
                        self.logger.info("Triggering immediate feed check...")
                        self.check_now_event.set()
                    elif cmd in ("exit", "quit"):
                        self.handle_exit()
                    else:
                        self.logger.info(f"Unknown command: '{cmd}'. Type 'help' for commands.")
                elif decoded_char == '\x08':
                    if current_command_line:
                        current_command_line = current_command_line[:-1]
                        sys.stdout.write('\b \b')
                        sys.stdout.flush()
                else:
                    current_command_line += decoded_char
                    sys.stdout.write(decoded_char)
                    sys.stdout.flush()
            else:
                self.shutdown_event.wait(0.1)
        
        self.logger.info("Command listener thread exiting.")

    def run(self):
        """Main loop"""
        self.logger.info("RSS watcher started.")
        self.failure_count = 0

        while not self.shutdown_event.is_set():
            self.last_check_time = datetime.datetime.now()
            try:
                headers = None
                if self.config["Watcher"]["use_custom_user_agent"]:
                    user_agent_string = f"GengoWatcher/1.0 (+{self.config['Network']['user_agent_email']})"
                    headers = {'User-Agent': user_agent_string}
                
                self.logger.info(f"Checking RSS feed: {self.config['Watcher']['feed_url']}...")
                feed = feedparser.parse(self.config["Watcher"]["feed_url"], request_headers=headers)

                if feed.bozo:
                    self.logger.warning(f"Feed parsing error: {feed.bozo_exception}. This indicates a malformed RSS feed or network issue. Gengo only allows 1 request every 30s.")
                    self.logger.warning("Please check your internet connection or try validating the RSS feed URL in your browser.")
                    self.failure_count += 1
                    wait_time = min(self.config["Watcher"]["check_interval"] * (2 ** self.failure_count), self.config["Network"]["max_backoff"])
                    self.logger.info(f"Retrying in {wait_time} seconds due to parsing error...")
                    self.check_now_event.wait(wait_time)
                    self.check_now_event.clear()
                    continue

                if not feed.entries:
                    self.logger.info(f"No entries found in the feed. Last checked: {self.last_check_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    self.failure_count = 0
                    self.check_now_event.wait(self.config["Watcher"]["check_interval"])
                    self.check_now_event.clear()
                    continue

                latest_entry = feed.entries[0]

                if latest_entry.link != self.last_seen_link:
                    self.total_new_entries_found += 1
                    self.logger.info("--- New Entry Discovered ---")
                    self.logger.info(f"Title: {latest_entry.title}")
                    self.logger.info(f"Link: {latest_entry.link}")
                    published_date = getattr(latest_entry, 'published', getattr(latest_entry, 'updated', 'N/A'))
                    self.logger.info(f"Date: {published_date}")
                    self.logger.info("----------------------------")

                    self.last_seen_link = latest_entry.link
                    self.notify(latest_entry.title, latest_entry.link)
                    self._save_runtime_state()
                else:
                    self.logger.info(f"No new entries. Last checked: {self.last_check_time.strftime('%Y-%m-%d %H:%M:%S')}")

                self.failure_count = 0
                self.check_now_event.wait(self.config["Watcher"]["check_interval"])
                self.check_now_event.clear()

            except Exception as e:
                self.logger.error(f"An unexpected error occurred in main loop: {e}", exc_info=True)
                self.logger.warning("Please check your internet connection or the RSS feed URL.")
                self.failure_count += 1
                wait_time = min(self.config["Watcher"]["check_interval"] * (2 ** self.failure_count), self.config["Network"]["max_backoff"])
                self.logger.info(f"Retrying in {wait_time} seconds due to error...")
                self.check_now_event.wait(wait_time)
                self.check_now_event.clear()

        self.logger.info("Main watcher loop finished. Attempting to join command listener thread...")
        self.command_thread.join(timeout=5)
        if self.command_thread.is_alive():
            self.logger.warning("Command listener thread did not terminate gracefully within timeout.")
        else:
            self.logger.info("Command listener thread stopped.")

        self.logger.info("Watcher has completed its shutdown sequence.")


if __name__ == "__main__":
    watcher = GengoWatcher()
    try:
        watcher.run()
    except SystemExit:
        pass
    except KeyboardInterrupt:
        watcher.logger.info("KeyboardInterrupt caught in main, graceful shutdown process completed.")
    except Exception as e:
        watcher.logger.critical(f"Unhandled exception in main execution: {e}", exc_info=True)
    finally:
        sys.exit(0)