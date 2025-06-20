import feedparser
import time
import webbrowser
import os
import platform

# --- CONFIG ---
FEED_URL = "https://gengo.com/rss/available_jobs/6d9668ab271c486e52eb4d37b876cabd5a1cf2da958b7004205163"  
CHECK_INTERVAL = 31  # seconds

# Set to Vivaldi browser path if not in PATH
VIVALDI_PATH = {
    "Windows": r"C:\Users\Thomas\AppData\Local\Vivaldi\Application\vivaldi.exe",
}

# Track last seen link
last_seen_link = None

def open_in_vivaldi(url):
    webbrowser.register('vivaldi', None, webbrowser.BackgroundBrowser(VIVALDI_PATH))
    webbrowser.get('vivaldi').open_new_tab(url)

def bring_vivaldi_to_foreground():
    # This works best if Vivaldi is already running
    os.system('powershell -command "(New-Object -ComObject Shell.Application).AppActivate(\'Vivaldi\')"')

while True:
    feed = feedparser.parse(FEED_URL)

    if not feed.entries:
        print("No entries found.")
        time.sleep(CHECK_INTERVAL)
        continue

    latest_entry = feed.entries[0]

    if latest_entry.link != last_seen_link:
        print(f"New post found: {latest_entry.title}")
        last_seen_link = latest_entry.link
        open_in_vivaldi(latest_entry.link)
        time.sleep(2)  # Allow time for the browser to open the tab
        bring_vivaldi_to_foreground()

    time.sleep(CHECK_INTERVAL)
