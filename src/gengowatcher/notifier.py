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
        path = _resolve_path(sound_file_path)

        if not path.is_file():
            logger.warning(f"Sound file not found: {sound_file_path}")
            return

        # List of players to try in order of preference
        # 1. pw-play (PipeWire - modern Linux/Arch default)
        # 2. paplay (PulseAudio)
        # 3. canberra-gtk-play (GTK/GNOME standard)
        # 4. mpv (Very common)
        # 5. aplay (ALSA - absolute fallback)
        players = [
            (["pw-play", str(path)], "pw-play"),
            (["paplay", str(path)], "paplay"),
            (["canberra-gtk-play", "-f", str(path)], "canberra-gtk-play"),
            (["mpv", "--no-video", "--no-terminal", str(path)], "mpv"),
            (["aplay", "-q", str(path)], "aplay"),
        ]

        for cmd, name in players:
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            except FileNotFoundError:
                continue
            except subprocess.CalledProcessError as e:
                logger.debug(f"{name} failed: {e}")
                continue
            except subprocess.TimeoutExpired:
                logger.debug(f"{name} timed out")
                continue
            else:
                logger.debug(
                    f"Successfully played sound with {name}: {sound_file_path}"
                )
                return

        logger.warning(
            "No suitable audio player found (tried pw-play, paplay, canberra-gtk-play, mpv, aplay)."
        )

    # Run in a separate thread to be non-blocking
    sound_thread = threading.Thread(target=_play)
    sound_thread.daemon = True
    sound_thread.start()


def _resolve_path(file_path: str) -> Path:
    """Resolve a path relative to project root if not absolute."""
    path = Path(file_path)
    if not path.is_absolute():
        project_root = Path(__file__).parent.parent.parent
        path = project_root / file_path
    return path


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

    if icon_path:
        resolved_icon = _resolve_path(icon_path)
        if resolved_icon.is_file():
            command.extend(["--icon", str(resolved_icon)])

    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        logger.debug("Notification sent successfully via notify-send.")
    except FileNotFoundError:
        logger.exception(
            "`notify-send` command not found. Please ensure it is installed and in your PATH."
        )
    except subprocess.TimeoutExpired:
        logger.warning("notify-send timed out after 10 seconds")
    except subprocess.CalledProcessError:
        logger.exception("Failed to send notification")


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
