
import subprocess
import threading
from pathlib import Path
import logging

# Use a specific logger for the notifier
logger = logging.getLogger(__name__)

def play_sound(sound_file_path: str):
    """
    Plays a sound file using the `playsound` library.
    This runs in a separate thread to avoid blocking.
    """
    def _play():
        try:
            from playsound import playsound
            
            if not Path(sound_file_path).is_file():
                logger.warning(f"Sound file not found: {sound_file_path}")
                return

            playsound(sound_file_path)
            logger.debug(f"Successfully played sound: {sound_file_path}")

        except ImportError:
            logger.warning("playsound is not installed. Please install it with 'pip install playsound'")
        except Exception as e:
            # Catching a generic exception from playsound as it can vary
            logger.error(f"Error playing sound {sound_file_path}: {e}")

    # Run in a separate thread to be non-blocking
    sound_thread = threading.Thread(target=_play)
    sound_thread.daemon = True
    sound_thread.start()

def send_notification(title: str, message: str, icon_path: str = ""):
    """
    Sends a desktop notification using `notify-send`.
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
    Displays a desktop notification and optionally plays a sound.
    """
    send_notification(title, message, icon_path)
    
    if sound_file_path:
        play_sound(sound_file_path)

