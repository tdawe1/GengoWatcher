import feedparser
import time
import webbrowser
import os
import platform
from win10toast import ToastNotifier

# --- CONFIG ---
FEED_URL = "https://gengo.com/rss/available_jobs/6d9668ab271c486e52eb4d37b876cabd5a1cf2da958b7004205163"
CHECK_INTERVAL = 31  # seconds

VIVALDI_PATH = {
    "Windows": r"C:\Users\Thomas\AppData\Local\Vivaldi\Application\vivaldi.exe",
}

# Setup
notifier = ToastNotifier()
last_seen_link = None

def open_in_vivaldi(url):
    path = VIVALDI_PATH.get(platform.system())
    if not path:
        print("Vivaldi path not set.")
        return
    webbrowser.register('vivaldi', None, webbrowser.BackgroundBrowser(path))
    webbrowser.get('vivaldi').open_new_tab(url)

def bring_vivaldi_to_foreground():
    os.system('powershell -command "(New-Object -ComObject Shell.Application).AppActivate(\'Vivaldi\')"')

def notify(title, url):
    notifier.show_toast(
        "New Entry",
        title,
        icon_path=None,
        duration=5,
        threaded=True
    )
    open_in_vivaldi(url)
    bring_vivaldi_to_foreground()


print("RSS watcher started. Watching for new entries...")

try:
    while True:
        print("Checking feed...")
        feed = feedparser.parse(FEED_URL)
        if not feed.entries:
            print("No entries found.")
            time.sleep(CHECK_INTERVAL)
            continue

        latest_entry = feed.entries[0]
        print(f"Latest entry: {latest_entry.title} - {latest_entry.link}")

        # Test: force notification
        notify("TEST: " + latest_entry.title, latest_entry.link)

        time.sleep(CHECK_INTERVAL)

except Exception as e:
    print(f"Error occurred: {e}")
    input("Press Enter to exit...")
