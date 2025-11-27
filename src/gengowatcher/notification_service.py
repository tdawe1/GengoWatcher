"""
Notification Service for GengoWatcher.
Handles desktop notifications and sound playback.
"""

import logging
import threading
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional

from plyer import notification

from .config import AppConfig


class NotificationService:
    """Service for handling notifications and sounds."""

    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.logger.info("NotificationService initialized")

    def play_sound(self):
        """Play notification sound using paplay.

        Attempts to play the configured sound file using the paplay command.
        Logs warnings if the sound file is not found or if paplay is not available.
        """
        if not self.config.get("Watcher", "enable_sound"):
            return

        sound_file_path = self.config.get("Paths", "sound_file")
        self.logger.debug(f"Attempting to play sound with paplay: {sound_file_path}")

        if not Path(sound_file_path).is_file():
            self.logger.warning(f"Sound file not found at: {sound_file_path}")
            return

        try:
            subprocess.Popen(
                ["paplay", sound_file_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self.logger.error(
                "`paplay` command not found. Please install `libpulse` (sudo pacman -S libpulse)."
            )
        except Exception as e:
            self.logger.error(f"Error playing sound with paplay: {e}")

    def open_in_browser(self, url: str):
        """Open a URL in the configured browser.

        Uses the configured browser path and arguments if available, otherwise
        falls back to the system default browser.

        Args:
            url: The URL to open in the browser.
        """
        self.logger.debug(f"Opening URL in browser: {url}")
        try:
            browser_path_str = self.config.get("Paths", "browser_path")
            if not browser_path_str or not Path(browser_path_str).is_file():
                webbrowser.open(url)
            else:
                args = [
                    arg.format(url=url)
                    for arg in self.config.get("Paths", "browser_args").split()
                ]
                subprocess.Popen([str(browser_path_str)] + args)
        except Exception as e:
            self.logger.error(f"Browser Error: {e}")

    def show_notification(
        self,
        message: str,
        title: str = "GengoWatcher",
        play_sound: bool = False,
        open_link: bool = False,
        url: Optional[str] = None,
    ):
        """Show a desktop notification with optional sound and browser opening.

        Displays a notification using the plyer library if notifications are enabled.
        Can optionally play a sound and/or open a URL in the browser.

        Args:
            message: The notification message text.
            title: The notification title (default: "GengoWatcher").
            play_sound: Whether to play a notification sound (default: False).
            open_link: Whether to open the provided URL in browser (default: False).
            url: The URL to open if open_link is True (default: None).
        """
        self.logger.debug(f"Showing notification: {title} - {message}")

        if self.config.get("Watcher", "enable_notifications"):
            try:
                icon_path = self.config.get("Paths", "notification_icon_path")
                app_icon = str(icon_path) if Path(icon_path).is_file() else None
                notification.notify(
                    title=title,
                    message=message,
                    app_name="GengoWatcher",
                    app_icon=app_icon,
                    timeout=8,
                )
            except Exception as e:
                self.logger.error(f"Notify Error: {e}")

        if play_sound:
            threading.Thread(target=self.play_sound, daemon=True).start()

        try:
            allow_open = self.config.get("Watcher", "open_links_on_new_job")
        except Exception:
            allow_open = True

        if open_link and url and allow_open:
            self.open_in_browser(url)
