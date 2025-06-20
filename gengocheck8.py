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

class GengoWatcher:
    CONFIG_FILE = "config.ini"

    def __init__(self):
        self.config = {} 
        self.last_seen_link = None
        self.shutdown_event = threading.Event()
        self.notifier = ToastNotifier()

        self._load_config()
        self._setup_logging()
        self._setup_signal_handlers()
        
        self.command_thread = threading.Thread(target=self.command_listener, daemon=True)
        self.command_thread.start()

    def _load_config(self):
        parser = configparser.ConfigParser()
        if not Path(self.CONFIG_FILE).is_file():
            print(f"Error: Configuration file '{self.CONFIG_FILE}' not found. Please create it.")
            sys.exit(1)

        parser.read(self.CONFIG_FILE, encoding='utf-8')

        self.config["FEED_URL"] = parser.get("Watcher", "feed_url")
        self.config["CHECK_INTERVAL"] = parser.getint("Watcher", "check_interval")

        self.config["SOUND_FILE"] = Path(parser.get("Paths", "sound_file"))
        self.config["VIVALDI_PATH"] = Path(parser.get("Paths", "vivaldi_path"))
        self.config["LOG_FILE"] = parser.get("Paths", "log_file")

        self.config["LOG_MAX_BYTES"] = parser.getint("Logging", "log_max_bytes")
        self.config["LOG_BACKUP_COUNT"] = parser.getint("Logging", "log_backup_count")

        self.config["MAX_BACKOFF"] = parser.getint("Network", "max_backoff")

    def _setup_logging(self):
        self.logger = logging.getLogger("GengoWatcher")
        self.logger.setLevel(logging.INFO)
        
        if not self.logger.handlers:
            file_handler = RotatingFileHandler(
                self.config["LOG_FILE"],
                maxBytes=self.config["LOG_MAX_BYTES"],
                backupCount=self.config["LOG_BACKUP_COUNT"],
                encoding="utf-8"
            )
            file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)

            console_handler = logging.StreamHandler(sys.stdout) # or sys.stderr if preferred
            console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)

        self.logger.info("Logging initialized.")

    def _setup_signal_handlers(self):
        signal.signal(signal.SIGINT, self.handle_exit)

    def handle_exit(self, signum=None, frame=None):
        self.logger.info("Exiting script...")
        self.shutdown_event.set()
        sys.exit(0)

    def play_sound(self):
        try:
            if self.config["SOUND_FILE"].is_file():
                winsound.PlaySound(str(self.config["SOUND_FILE"]), winsound.SND_FILENAME)
            else:
                winsound.MessageBeep()
                self.logger.warning(f"Sound file not found: {self.config['SOUND_FILE']}. Playing default beep.")
        except Exception as e:
            self.logger.error(f"Sound error: {e}")

    def play_sound_async(self):
        threading.Thread(target=self.play_sound, daemon=True).start()

    def open_in_vivaldi(self, url):
        if not self.config["VIVALDI_PATH"] or not self.config["VIVALDI_PATH"].is_file():
            self.logger.warning("Vivaldi path not set or invalid. Opening with default browser.")
            try:
                webbrowser.open_new_tab(url)
            except Exception as e:
                self.logger.error(f"Default browser open error: {e}")
            return
        
        try:
            webbrowser.register('vivaldi', None, webbrowser.BackgroundBrowser(str(self.config["VIVALDI_PATH"])))
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
        self.logger.info(f"New entry: {title}")

        self.play_sound_async()

        try:
            self.notifier.show_toast(
                "New Gengo Job",
                title,
                icon_path=None,
                duration=5,
                threaded=True
            )
        except Exception as e:
            self.logger.error(f"Notification error: {e}")

        threading.Thread(target=self.open_in_vivaldi, args=(url,), daemon=True).start()
        self.bring_vivaldi_to_foreground_async()

    def test_notify(self):
        test_title = "RSS Checker Test Notification"
        test_url = "https://gengo.com/t/jobs/status/available"
        self.notify(test_title, test_url)
        self.logger.info("Test notification sent.")

    def command_listener(self):
        self.logger.info("Command listener started. Type 'test' for a notification or 'exit' to quit.")
        while not self.shutdown_event.is_set():
            try:
                cmd = input() # threaded blocking call
                if cmd.strip().lower() == "test":
                    self.test_notify()
                elif cmd.strip().lower() in ("exit", "quit"):
                    self.handle_exit()
                else:
                    self.logger.info(f"Unknown command: '{cmd}'.")
            except EOFError:
                self.logger.info("EOF received in command listener.")
                break
            except Exception as e:
                self.logger.error(f"Command listener error: {e}")
                time.sleep(1)

    def run(self):
        self.logger.info("RSS watcher started. Checking for new entries...")
        failure_count = 0

        while not self.shutdown_event.is_set():
            try:
                feed = feedparser.parse(self.config["FEED_URL"])

                if feed.bozo:
                    self.logger.warning(f"Feed parsing error: {feed.bozo_exception}. This indicates a malformed RSS feed.")
                    failure_count += 1
                    wait_time = min(self.config["CHECK_INTERVAL"] * (2 ** failure_count), self.config["MAX_BACKOFF"])
                    self.logger.info(f"Retrying in {wait_time} seconds due to parsing error...")
                    time.sleep(wait_time)
                    continue

                if not feed.entries:
                    self.logger.info("No entries found in the feed.")
                    failure_count = 0
                    time.sleep(self.config["CHECK_INTERVAL"])
                    continue

                latest_entry = feed.entries[0]

                if latest_entry.link != self.last_seen_link:
                    self.last_seen_link = latest_entry.link
                    self.notify(latest_entry.title, latest_entry.link)
                else:
                    self.logger.info("No new entries.")

                failure_count = 0
                time.sleep(self.config["CHECK_INTERVAL"])

            except Exception as e:
                self.logger.error(f"An unexpected error occurred in main loop: {e}", exc_info=True)
                failure_count += 1
                wait_time = min(self.config["CHECK_INTERVAL"] * (2 ** failure_count), self.config["MAX_BACKOFF"])
                self.logger.info(f"Retrying in {wait_time} seconds due to error...")
                time.sleep(wait_time)


if __name__ == "__main__":
    watcher = GengoWatcher()
    try:
        watcher.run()
    except KeyboardInterrupt:
        watcher.handle_exit()
    except Exception as e:
        watcher.logger.critical(f"Unhandled exception in main execution: {e}", exc_info=True)