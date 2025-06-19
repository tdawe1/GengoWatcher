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
import colorama
from colorama import Fore, Style

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

    DEFAULT_CONFIG = {
        "Watcher": {
            "feed_url": "https://www.theguardian.com/uk/rss",
            "check_interval": "31",
            "enable_notifications": "True",
            "use_custom_user_agent": "False"
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
                "use_custom_user_agent": self._config_parser.getboolean("Watcher", "use_custom_user_agent", fallback=False)
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

    def handle_exit(self, signum=None, frame=None):
        self.logger.info("Exiting script...")
        self._save_runtime_state()
        self.shutdown_event.set()

    def play_sound(self):
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
        test_title = "Test Notification"
        test_url = "https://gengo.com/t/jobs/status/available"
        self.notify(test_title, test_url)
        self.logger.info("Test notification sent.")

    def display_help(self):
        help_message = f"""
{Style.BRIGHT + Fore.GREEN}Available Commands:{Style.RESET_ALL}
  {Fore.YELLOW}help{Style.RESET_ALL}        - Display this help message.
  {Fore.YELLOW}test{Style.RESET_ALL}        - Send a test desktop notification.
  {Fore.YELLOW}status{Style.RESET_ALL}      - Show current watcher status (last checked, next check, total entries found, etc.).
  {Fore.YELLOW}check_now{Style.RESET_ALL}   - Immediately trigger an RSS feed check.
  {Fore.YELLOW}exit / quit{Style.RESET_ALL} - Stop the watcher and exit the script.
"""
        self.logger.info(help_message)

    def display_status(self):
        status_message = f"""
{Style.BRIGHT + Fore.GREEN}Watcher Status:{Style.RESET_ALL}
  {Fore.CYAN}Last seen link:{Style.RESET_ALL} {self.last_seen_link if self.last_seen_link else 'None (first run or not yet seen)'}
  {Fore.CYAN}Last checked:{Style.RESET_ALL} {self.last_check_time.strftime('%Y-%m-%d %H:%M:%S') if self.last_check_time else 'Not yet checked'}
  {Fore.CYAN}Next check in:{Style.RESET_ALL} {self.config["Watcher"]['check_interval']} seconds (or press 'check_now')
  {Fore.CYAN}Network failures:{Style.RESET_ALL} {self.failure_count}
  {Fore.CYAN}Total new entries found (this run/overall):{Style.RESET_ALL} {self.total_new_entries_found}
"""
        self.logger.info(status_message)


    def command_listener(self):
        current_command_line = ""
        sys.stdout.write(f"{Fore.MAGENTA}Command > {Style.RESET_ALL}")
        sys.stdout.flush()
        
        while not self.shutdown_event.is_set():
            if self.shutdown_event.is_set():
                break 

            if msvcrt.kbhit():
                char = msvcrt.getch()
                if self.shutdown_event.is_set():
                    break
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
                    
                    if not self.shutdown_event.is_set():
                        sys.stdout.write(f"{Fore.MAGENTA}Command > {Style.RESET_ALL}")
                        sys.stdout.flush()
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
                self.shutdown_event.wait(0.05) 
        
        self.logger.info("Command listener thread exiting.")

    def run(self):
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
                    self.logger.info(f"{Fore.GREEN}{Style.BRIGHT}--- New Entry Discovered ---{Style.RESET_ALL}")
                    self.logger.info(f"{Fore.GREEN}Title: {latest_entry.title}{Style.RESET_ALL}")
                    self.logger.info(f"{Fore.GREEN}Link: {latest_entry.link}{Style.RESET_ALL}")
                    published_date = getattr(latest_entry, 'published', getattr(latest_entry, 'updated', 'N/A'))
                    self.logger.info(f"{Fore.GREEN}Date: {published_date}{Style.RESET_ALL}")
                    self.logger.info(f"{Fore.GREEN}{Style.BRIGHT}----------------------------{Style.RESET_ALL}")

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
    colorama.init()
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