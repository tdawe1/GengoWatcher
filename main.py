import logging
import threading
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
import collections
import datetime

from rich.console import Console
from rich.text import Text
from rich.theme import Theme

# Import application modules
from config import AppConfig
from state import AppState
from watcher import GengoWatcher
from ui import CommandLineInterface

# Define the application's look and feel
APP_THEME = Theme({
    "info": "cyan", "success": "bold green", "warning": "yellow", "error": "bold red",
    "title": "bold magenta", "header": "bold bright_white", "label": "cyan", "value": "white",
    "path": "italic yellow", "panel_border": "bright_blue", "table_header": "bold magenta",
    "prompt": "bold white", "input": "white"
})


class UILoggingHandler(logging.Handler):
    """A custom logging handler that captures styled logs for display in the UI."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # This queue will be shared with the UI
        self.log_queue = collections.deque(maxlen=10)

    def emit(self, record):
        level_style_map = {
            logging.INFO: "info",
            logging.WARNING: "warning",
            logging.ERROR: "error",
            logging.CRITICAL: "bold red",
        }
        style = level_style_map.get(record.levelno, "default")
        # Prepend timestamp to the message, Rich will handle styling
        message = f"{datetime.datetime.fromtimestamp(record.created).strftime('%H:%M:%S')} - {record.getMessage()}"
        self.log_queue.append(Text(message, style=style))


def main():
    """Main function to set up and run the application."""
    console = Console(theme=APP_THEME)

    # Set up the root logger
    log = logging.getLogger("gengowatcher")
    log.setLevel(logging.INFO)
    
    # Create the handler that will send logs to the UI
    ui_handler = UILoggingHandler()
    log.addHandler(ui_handler)
    
    # --- Initialization ---
    try:
        config = AppConfig()
        state = AppState(logger=log)
        watcher = GengoWatcher(config=config, state=state, logger=log)
    except Exception as e:
        console.print(f"[error]A critical error occurred during initialization: {e}[/]")
        sys.exit(1)

    # --- File Logging Setup ---
    if config.get("Logging", "log_main_enabled"):
        try:
            log_file = Path(config.get("Paths", "log_file"))
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_file, 
                maxBytes=config.get("Logging", "log_max_bytes"), 
                backupCount=config.get("Logging", "log_backup_count")
            )
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            log.addHandler(file_handler)
        except IOError as e:
            console.print(f"[error]Could not set up file logging: {e}[/]")

    # --- UI and Threading Setup ---
    cli = CommandLineInterface(watcher, config, state, console, log_queue=ui_handler.log_queue)
    
    watcher_thread = threading.Thread(target=watcher.run, daemon=True, name="WatcherThread")
    watcher_thread.start()
    
    try:
        cli.run()
    except Exception as e:
        log.error(f"UI loop crashed: {e}")
    finally:
        # Ensure clean shutdown
        if not watcher.shutdown_event.is_set():
            watcher.handle_exit()
        watcher_thread.join(timeout=2)
        console.print("[info]GengoWatcher has shut down.[/]")


if __name__ == "__main__":
    main()