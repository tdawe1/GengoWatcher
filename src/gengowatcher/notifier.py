import subprocess
import threading
from pathlib import Path
import logging
from typing import Optional

# Use a specific logger for the notifier
logger = logging.getLogger(__name__)


def play_sound(sound_file_path: str):
    """
    Plays a sound file using system audio players.
    Tries multiple common Linux audio players.
    This runs in a separate thread to avoid blocking.
    """

    def _play():
        if not Path(sound_file_path).is_file():
            logger.warning(f"Sound file not found: {sound_file_path}")
            return

        # List of players to try in order of preference
        # 1. pw-play (PipeWire - modern Linux/Arch default)
        # 2. paplay (PulseAudio)
        # 3. canberra-gtk-play (GTK/GNOME standard)
        # 4. mpv (Very common)
        # 5. aplay (ALSA - absolute fallback)
        players = [
            (["pw-play", sound_file_path], "pw-play"),
            (["paplay", sound_file_path], "paplay"),
            (["canberra-gtk-play", "-f", sound_file_path], "canberra-gtk-play"),
            (["mpv", "--no-video", "--no-terminal", sound_file_path], "mpv"),
            (["aplay", "-q", sound_file_path], "aplay"),
        ]

        for cmd, name in players:
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.debug(
                    f"Successfully played sound with {name}: {sound_file_path}"
                )
                return
            except FileNotFoundError:
                continue
            except subprocess.CalledProcessError as e:
                logger.debug(f"{name} failed: {e}")
                continue

        logger.warning(
            "No suitable audio player found (tried pw-play, paplay, canberra-gtk-play, mpv, aplay)."
        )

    # Run in a separate thread to be non-blocking
    sound_thread = threading.Thread(target=_play)
    sound_thread.daemon = True
    sound_thread.start()


def send_notification(title: str, message: str, icon_path: str = ""):
    """
    Display a desktop notification using the system 'notify-send' utility.

    If `icon_path` is provided and points to an existing file, that icon will be included in the notification; otherwise the icon is ignored.

    Parameters:
        title (str): Notification title.
        message (str): Notification body text.
        icon_path (str): Path to an icon file; ignored if empty or the file does not exist.
    """
    command = ["notify-send", title, message]

    if icon_path and Path(icon_path).is_file():
        command.extend(["--icon", icon_path])

    try:
        subprocess.run(command, check=True)
        logger.debug("Notification sent successfully via notify-send.")
    except FileNotFoundError:
        logger.error(
            "`notify-send` command not found. Please ensure it is installed and in your PATH."
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to send notification: {e}")


def show_notification(
    title: str, message: str, sound_file_path: Optional[str] = None, icon_path: str = ""
):
    """
    Display a desktop notification and optionally play a sound.

    Parameters:
        title (str): Notification title text.
        message (str): Notification body text.
        sound_file_path (str, optional): Path to an audio file to play; if provided and valid, playback is started asynchronously. Defaults to None.
        icon_path (str, optional): Path to an icon file to show with the notification; if empty or invalid, no icon is used. Defaults to "".
    """
    send_notification(title, message, icon_path)

    if sound_file_path:
        play_sound(sound_file_path)
