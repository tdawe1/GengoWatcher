"""User-feedback helpers extracted from GengoWatcher.

Owns three side-channel helpers:

* _setup_csv_logging(watcher)  -- opens the on-disk CSV recorder
  for RSS feed entries.
* show_notification(watcher, message, title="GengoWatcher",
  play_sound=False, open_link=False, url=None, sound_file=None)
  -- sends a desktop notification + optionally plays a sound and
  opens a URL in the configured browser.
* open_in_browser(watcher, url)  -- opens the URL through the
  managed Firefox debug session when available, otherwise via a
  configurable Path-anchored browser executable, finally falling
  back to webbrowser.open().

The watcher keeps thin delegator methods on the class so call
sites throughout the codebase continue to resolve through the
instance.
"""

from __future__ import annotations

import csv
import subprocess
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

from . import notifier

if TYPE_CHECKING:
    pass



def _setup_csv_logging(watcher):
    """
    Initialise CSV logging for recording RSS feed entries.

    Creates the configured log directory if missing, opens the log file for appending and initialises a CSV writer. If the file is empty a header row ("timestamp", "title", "reward", "link", "summary") is written. If the file cannot be opened, CSV logging is disabled and an error is logged.
    """
    watcher.logger.debug("Setting up CSV logging.")
    try:
        log_path_str = watcher.config.get("Paths", "all_entries_log")
        if not log_path_str or not isinstance(log_path_str, (str, Path)):
            watcher.logger.error("all_entries_log path not configured or invalid")
            return
        log_path = Path(str(log_path_str))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        watcher._all_entries_log_file = open(
            log_path, "a", newline="", encoding="utf-8"
        )
        watcher._csv_writer = csv.writer(watcher._all_entries_log_file)
        if log_path.stat().st_size == 0:
            watcher._csv_writer.writerow(
                ["timestamp", "title", "reward", "link", "summary"]
            )
        watcher.logger.debug(f"CSV logging enabled at {log_path}")
    except IOError as e:
        watcher.logger.error(f"Could not open all_entries_log file: {e}")
        watcher._all_entries_log_file = None
        watcher._csv_writer = None



def show_notification(
    watcher,
    message,
    title="GengoWatcher",
    play_sound=False,
    open_link=False,
    url=None,
    sound_file=None,
):
    """
    Send a desktop notification and optionally play a sound or open a URL.

    Parameters:
        message (str): Notification message body.
        title (str): Notification title; defaults to "GengoWatcher".
        play_sound (bool): If True and sound is enabled in configuration, play the configured sound.
        open_link (bool): If True and `url` is provided, open the URL in the configured browser.
        url (str | None): URL to open when `open_link` is True; ignored if not provided.
        sound_file (str | None): Optional override sound path; defaults to Paths.sound_file.
    """
    if watcher.config.get("Watcher", "enable_notifications"):
        icon_path = watcher.config.get("Paths", "notification_icon_path")
        notifier.send_notification(title, message, icon_path)

    if play_sound and watcher.config.get("Watcher", "enable_sound"):
        chosen_sound = sound_file or watcher.config.get("Paths", "sound_file")
        notifier.play_sound(chosen_sound)

    if open_link and url:
        watcher.open_in_browser(url)



def open_in_browser(watcher, url):
    """
    Open the given URL using the configured browser if available, otherwise use the system default browser.

    Parameters:
        url (str): The URL to open. If the configured `browser_args` include formatting placeholders (for example `{url}`), they will be formatted with this URL.
    """
    watcher.logger.debug(f"Opening URL in browser: {url}")
    try:
        if watcher._open_in_managed_firefox_debug_session(str(url)):
            return

        browser_path_str = watcher.config.get("Paths", "browser_path")
        if not browser_path_str or not Path(browser_path_str).is_file():
            webbrowser.open(url)
        else:
            args = [
                arg.format(url=url)
                for arg in watcher.config.get("Paths", "browser_args").split()
            ]
            subprocess.Popen([str(browser_path_str)] + args)
    except Exception as e:
        watcher.logger.error(f"Browser Error: {e}")


__all__ = [
    "_setup_csv_logging",
    "show_notification",
    "open_in_browser",
]
