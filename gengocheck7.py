import feedparser
import time
import webbrowser
import os
import platform
import winsound
from win10toast import ToastNotifier
import signal
import sys
import threading
import io
import logging
from logging.handlers import RotatingFileHandler

class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()

    def flush(self):
        for s in self.streams:
            s.flush()


class GengoWatcher:

    FEED_URL = "https://gengo.com/rss/available_jobs/6d9668ab271c486e52eb4d37b876cabd5a1cf2da958b7004205163"
    CHECK_INTERVAL = 31  # seconds
    SOUND_FILE = r"C:\Users\Thomas\py dist\mixkit-arcade-bonus-alert-767.wav"
    VIVALDI_PATH = r"C:\Users\Thomas\AppData\Local\Vivaldi\Application\vivaldi.exe"
    LOG_FILE = "gengo_rss_log.txt"

    def __init__(self):
        self.last_seen_link = None
        self.shutdown_event = threading.Event()

        self.logger = logging.getLogger("GengoWatcher")
        self.logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(self.LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        self.stdout_buffer = io.StringIO()
        sys.stdout = sys.stderr = Tee(sys.__stdout__, self.stdout_buffer)

        self.notifier = ToastNotifier()

        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)

        self.command_thread = threading.Thread(target=self.command_listener, daemon=True)
        self.command_thread.start()

    def log(self, message):
        print(message)
        self.logger.info(message)

    def save_log(self):
        with open(self.LOG_FILE, "a", encoding="utf-8") as f:
            f.write("\n--- Terminal Output ---\n")
            f.write(self.stdout_buffer.getvalue())
        self.log("Log saved.")

    def play_sound(self):
        try:
            if os.path.isfile(self.SOUND_FILE):
                winsound.PlaySound(self.SOUND_FILE, winsound.SND_FILENAME)
            else:
                winsound.MessageBeep()
        except Exception as e:
            self.log(f"Sound error: {e}")

    def play_sound_async(self):
        threading.Thread(target=self.play_sound, daemon=True).start()

    def open_in_vivaldi(self, url):
        if not self.VIVALDI_PATH or not os.path.isfile(self.VIVALDI_PATH):
            self.log("Vivaldi path not set or invalid.")
            return
        try:
            webbrowser.register('vivaldi', None, webbrowser.BackgroundBrowser(self.VIVALDI_PATH))
            webbrowser.get('vivaldi').open_new_tab(url)
        except Exception as e:
            self.log(f"Browser open error: {e}")

    def bring_vivaldi_to_foreground(self):
        try:
            os.system('powershell -command "$wshell = New-Object -ComObject WScript.Shell; $wshell.AppActivate(\'Vivaldi\')"')
        except Exception as e:
            self.log(f"Foreground error: {e}")

    def bring_vivaldi_to_foreground_async(self):
        threading.Thread(target=self.bring_vivaldi_to_foreground, daemon=True).start()

    def notify(self, title, url):
        self.log(f"New entry: {title}")

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
            self.log(f"Notification error: {e}")

        threading.Thread(target=self.open_in_vivaldi, args=(url,), daemon=True).start()
        self.bring_vivaldi_to_foreground_async()

    def handle_exit(self, signum=None, frame=None):
        self.log("Exiting script...")
        self.shutdown_event.set()
        self.save_log()
        sys.exit(0)

    def test_notify(self):
        test_title = "Test Notification"
        test_url = "https://gengo.com/t/jobs/status/available"
        self.notify(test_title, test_url)
        self.log("Test notification sent.")

    def command_listener(self):
        while not self.shutdown_event.is_set():
            try:
                cmd = input()
                if cmd.strip().lower() == "test":
                    self.test_notify()
                elif cmd.strip().lower() in ("exit", "quit"):
                    self.handle_exit()
            except EOFError:
                break
            except Exception as e:
                self.log(f"Command listener error: {e}")
                break

    def run(self):
        self.log("RSS watcher started. Watching for new entries...")
        failure_count = 0
        max_backoff = 300

        while not self.shutdown_event.is_set():
            try:
                feed = feedparser.parse(self.FEED_URL)

                if feed.bozo:
                    self.log(f"Feed parsing error: {feed.bozo_exception}")
                    failure_count += 1
                    wait_time = min(self.CHECK_INTERVAL * (2 ** failure_count), max_backoff)
                    self.log(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue

                if not feed.entries:
                    self.log("No entries found.")
                    failure_count = 0
                    time.sleep(self.CHECK_INTERVAL)
                    continue

                latest_entry = feed.entries[0]

                if latest_entry.link != self.last_seen_link:
                    self.last_seen_link = latest_entry.link
                    self.notify(latest_entry.title, latest_entry.link)
                else:
                    self.log("No new entries.")

                failure_count = 0
                time.sleep(self.CHECK_INTERVAL)

            except Exception as e:
                self.log(f"Error: {e}")
                failure_count += 1
                wait_time = min(self.CHECK_INTERVAL * (2 ** failure_count), max_backoff)
                self.log(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)


if __name__ == "__main__":
    watcher = GengoWatcher()
    watcher.run()
