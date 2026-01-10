import subprocess
import threading
from pathlib import Path
import logging

# Use a specific logger for the notifier
logger = logging.getLogger(__name__)

def play_sound(sound_file_path: str):
    """
    Plays a sound file using system audio players.
    Tries paplay (PulseAudio/PipeWire), then aplay (ALSA) as fallback.
    This runs in a separate thread to avoid blocking.
    """
    def _play():
        if not Path(sound_file_path).is_file():
            logger.warning(f"Sound file not found: {sound_file_path}")
            return

        # Try paplay first (PulseAudio/PipeWire - common on modern Linux including Arch)
        try:
            subprocess.run(
                ['paplay', sound_file_path],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.debug(f"Successfully played sound with paplay: {sound_file_path}")
            return
        except FileNotFoundError:
            logger.debug("paplay not found, trying aplay...")
        except subprocess.CalledProcessError as e:
            logger.debug(f"paplay failed: {e}, trying aplay...")

        # Fallback to aplay (ALSA - works on most Linux distros)
        try:
            subprocess.run(
                ['aplay', '-q', sound_file_path],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.debug(f"Successfully played sound with aplay: {sound_file_path}")
            return
        except FileNotFoundError:
            logger.warning("Neither paplay nor aplay found. Cannot play sound.")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error playing sound {sound_file_path}: {e}")

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
    command = ['notify-send', title, message]
    
    if icon_path and Path(icon_path).is_file():
        command.extend(['--icon', icon_path])
    
    try:
        subprocess.run(command, check=True)
        logger.debug("Notification sent successfully via notify-send.")
    except FileNotFoundError:
        logger.error("`notify-send` command not found. Please ensure it is installed and in your PATH.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to send notification: {e}")

def show_notification(title: str, message: str, sound_file_path: str = None, icon_path: str = ""):
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
