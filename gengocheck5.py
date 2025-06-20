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

# --- CONFIG ---
FEED_URL = "https://gengo.com/rss/available_jobs/6d9668ab271c486e52eb4d37b876cabd5a1cf2da958b7004205163"
CHECK_INTERVAL = 31  # seconds

VIVALDI_PATH = {
    "Windows": r"C:\Users\Thomas\AppData\Local\Vivaldi\Application\vivaldi.exe",
}

SOUND_FILE = r"C:\Users\Thomas\py dist\mixkit-arcade-bonus-alert-767.wav"

LOG_FILE = "gengo_rss_log.txt"
log_lines = []

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


# Capture all stdout/stderr
stdout_buffer = io.StringIO()
sys.stdout = sys.stderr = Tee(sys.__stdout__, stdout_buffer)


# Setup
notifier = ToastNotifier()
last_seen_link = None

def log(message):
    timestamped = f"{time.ctime()} - {message}"
    print(timestamped)
    log_lines.append(timestamped)

def save_log():
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n")
        f.write("\n--- Terminal Output ---\n")
        f.write(stdout_buffer.getvalue())
    log("Log saved.")

def play_sound():
    try:
        if os.path.isfile(SOUND_FILE):
            winsound.PlaySound(SOUND_FILE, winsound.SND_FILENAME)
        else:
            winsound.MessageBeep()
    except Exception as e:
        log(f"Sound error: {e}")

def open_in_vivaldi(url):
    path = VIVALDI_PATH.get(platform.system())
    if not path:
        log("Vivaldi path not set.")
        return
    webbrowser.register('vivaldi', None, webbrowser.BackgroundBrowser(path))
    webbrowser.get('vivaldi').open_new_tab(url)

def bring_vivaldi_to_foreground():
    os.system('powershell -command "$wshell = New-Object -ComObject WScript.Shell; $wshell.AppActivate(\'Vivaldi\')"')

def notify(title, url):
    log(f"New entry: {title}")
    play_sound()
    try:
        notifier.show_toast(
            "New Gengo Job",
            title,
            icon_path=None,
            duration=5,
            threaded=True
        )
    except Exception as e:
        log(f"Notification error: {e}")
    open_in_vivaldi(url)
    bring_vivaldi_to_foreground()

def handle_exit(signum=None, frame=None):
    log("Exiting script...")
    save_log()
    sys.exit(0)

def test_notify():
    test_title = "Test Notification"
    test_url = "https://gengo.com/t/jobs/status/available"
    notify(test_title, test_url)
    log("Test notification sent.")

def command_listener():
    while True:
        try:
            cmd = input()
            if cmd.strip().lower() == "test":
                test_notify()
            elif cmd.strip().lower() in ("exit", "quit"):
                handle_exit()
        except EOFError:
            break

# Signal handlers
signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

# Start command listener
threading.Thread(target=command_listener, daemon=True).start()

# Main loop
log("RSS watcher started. Watching for new entries...")

try:
    while True:
        feed = feedparser.parse(FEED_URL)
        if not feed.entries:
            log("No entries found.")
            time.sleep(CHECK_INTERVAL)
            continue

        latest_entry = feed.entries[0]
        if latest_entry.link != last_seen_link:
            last_seen_link = latest_entry.link
            notify(latest_entry.title, latest_entry.link)

        time.sleep(CHECK_INTERVAL)

except Exception as e:
    log(f"Error: {e}")
    handle_exit()
