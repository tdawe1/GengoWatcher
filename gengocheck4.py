import feedparser
import time
import webbrowser
import os
import platform
import winsound
from win10toast import ToastNotifier
import signal
import sys

# --- CONFIG ---
FEED_URL = "https://gengo.com/rss/available_jobs/6d9668ab271c486e52eb4d37b876cabd5a1cf2da958b7004205163"
CHECK_INTERVAL = 31  # seconds

VIVALDI_PATH = {
    "Windows": r"C:\Users\Thomas\AppData\Local\Vivaldi\Application\vivaldi.exe",
}

LOG_FILE = "gengo_rss_log.txt"
log_lines = []

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
    log("Log saved.")

def open_in_vivaldi(url):
    path = VIVALDI_PATH.get(platform.system())
    if not path:
        log("Unsupported OS or Vivaldi path not set.")
        return
    webbrowser.register('vivaldi', None, webbrowser.BackgroundBrowser(path))
    webbrowser.get('vivaldi').open_new_tab(url)

def bring_vivaldi_to_foreground():
    os.system('powershell -command "(New-Object -ComObject Shell.Application).AppActivate(\'Vivaldi\')"')

def notify(title, url):
    log(f"New job: {title}")
    winsound.MessageBeep()  # Play default Windows sound
    notifier.show_toast(
        "New Gengo Job",
        title,
        icon_path=None,
        duration=5,
        threaded=True
    )
    open_in_vivaldi(url)
    bring_vivaldi_to_foreground()

def handle_exit(signum=None, frame=None):
    log("Exiting script...")
    save_log()
    sys.exit(0)

# Attach signal handlers for graceful shutdown
signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

# Main loop
log("Gengo RSS watcher started. Watching for new jobs...")

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