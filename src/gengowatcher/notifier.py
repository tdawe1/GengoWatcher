import subprocess
import threading
from pathlib import Path
import logging

# Use a specific logger for the notifier
logger = logging.getLogger(__name__)

def play_sound(sound_file_path: str):
    """
    Play a sound file in the background without blocking the caller.
    
    Attempts to play the file at `sound_file_path` using the `playsound` library; if the file is missing or the playback dependency is not available the function logs a warning and returns silently. Playback errors are logged as errors.
    
    Parameters:
        sound_file_path (str): Filesystem path to the sound file to play. The path should point to an existing file; if it does not, a warning will be logged and no playback will be attempted.
    """
    def _play():
        """
        Attempt to play the configured sound file and log success or failure.
        
        Checks whether the file at the closed-over `sound_file_path` exists and, if so, attempts playback using `playsound`. Logs a warning if the file is missing, a warning if the `playsound` package is not installed, and an error if playback fails for any other reason. Logs a debug message on successful playback.
        """
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
