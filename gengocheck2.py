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
        print("Unsupported OS or Vivaldi path not set.")
        return
    webbrowser.register('vivaldi', None, webbrowser.BackgroundBrowser(path))
    webbrowser.get('vivaldi').open_new_tab(url)

def bring_vivaldi_to_foreground():
    os.system('powershell -command "(New-Object -ComObject Shell.Application).AppActivate(\'Vivaldi\')"')

def notify(title, url):
    notifier.show_toast(
        "New Gengo Job",
        title,
        icon_path=None,
        duration=5,
        threaded=True
    )
    open_in_vivaldi(url)
    bring_vivaldi_to_foreground()


print("Gengo RSS watcher started. Watching for new jobs...")

while True:
    try:
        feed = feedparser.parse(FEED_URL)
        if not feed.entries:
            print("No entries found.")
            time.sleep(CHECK_INTERVAL)
            continue

        latest_entry = feed.entries[0]

        if latest_entry.link != last_seen_link:
            print(f"New job: {latest_entry.title}")
            last_seen_link = latest_entry.link
            notify(latest_entry.title, latest_entry.link)

        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(CHECK_INTERVAL)
