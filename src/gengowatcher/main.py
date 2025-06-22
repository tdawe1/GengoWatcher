import logging
import threading
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
import collections
import datetime
import argparse

from rich.console import Console
from rich.text import Text
from rich.theme import Theme

from .config import AppConfig
from .state import AppState
from .watcher import GengoWatcher
from .ui import CommandLineInterface

APP_THEME = Theme(
    {
        "info": "cyan",
        "success": "bold green",
        "warning": "yellow",
        "error": "bold red",
        "title": "bold magenta",
        "header": "bold bright_white",
        "label": "cyan",
        "value": "white",
        "path": "italic yellow",
        "panel_border": "bright_blue",
        "table_header": "bold magenta",
        "prompt": "bold white",
        "input": "white",
    }
)


class UILoggingHandler(logging.Handler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_queue = collections.deque(maxlen=10)

    def emit(self, record):
        level_style_map = {
            logging.INFO: "info",
            logging.WARNING: "warning",
            logging.ERROR: "error",
            logging.CRITICAL: "bold red",
        }
        style = level_style_map.get(record.levelno, "default")
        message = (
            f"{datetime.datetime.fromtimestamp(record.created).strftime('%H:%M:%S')} - "
            f"{record.getMessage()}"
        )
        self.log_queue.append(Text.from_markup(message, style=style))


def main():
    parser = argparse.ArgumentParser(description="GengoWatcher CLI")
    parser.add_argument(
        "--set",
        nargs=3,
        metavar=("SECTION", "OPTION", "VALUE"),
        help="Set a config value",
    )
    parser.add_argument(
        "--get", nargs=2, metavar=("SECTION", "OPTION"), help="Get a config value"
    )
    parser.add_argument("--list", action="store_true", help="List all config values")
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Interactively configure missing/required values",
    )
    args, unknown = parser.parse_known_args()

    console = Console(theme=APP_THEME)
    log = logging.getLogger("gengowatcher")
    log.setLevel(logging.INFO)
    ui_handler = UILoggingHandler()
    log.addHandler(ui_handler)

    try:
        config = AppConfig()
        if config.get("Logging", "log_main_enabled"):
            try:
                log_file = Path(config.get("Paths", "log_file"))
                log_file.parent.mkdir(parents=True, exist_ok=True)
                file_handler = RotatingFileHandler(
                    log_file,
                    maxBytes=config.get("Logging", "log_max_bytes"),
                    backupCount=config.get("Logging", "log_backup_count"),
                )
                file_handler.setFormatter(
                    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
                )
                log.addHandler(file_handler)
            except IOError as e:
                console.print(f"[error]Could not set up file logging: {e}[/]")
        state = AppState(logger=log)
        watcher = GengoWatcher(config=config, state=state, logger=log)
    except Exception as e:
        if log.handlers:
            log.critical(f"A critical error occurred during initialization: {e}")
        else:
            console.print(
                f"[error]A critical error occurred during initialization: {e}[/]"
            )
        sys.exit(1)

    if args.set:
        section, option, value = args.set
        watcher.set_config_value(section, option, value)
        print(f"Set [{section}] {option} = {value}")
        sys.exit(0)
    if args.get:
        section, option = args.get
        value = watcher.get_config_value(section, option)
        print(f"[{section}] {option} = {value}")
        sys.exit(0)
    if args.list:
        all_values = watcher.list_config_values()
        for section, options in all_values.items():
            print(f"[{section}]")
            for option, value in options.items():
                print(f"  {option} = {value}")
        sys.exit(0)
    if args.configure:
        watcher.prompt_for_config_values()
        sys.exit(0)

    if not watcher.is_config_complete():
        print("Config is incomplete. Please provide missing values:")
        watcher.prompt_for_config_values()

    cli = CommandLineInterface(
        watcher, config, state, console, log_queue=ui_handler.log_queue
    )

    watcher_thread = threading.Thread(
        target=watcher.run, daemon=True, name="WatcherThread"
    )
    watcher_thread.start()

    try:
        cli.run()
    except Exception as e:
        log.error(f"UI loop crashed: {e}")
    finally:
        if not watcher.shutdown_event.is_set():
            watcher.handle_exit()
        watcher_thread.join(timeout=2)
        console.print("[info]GengoWatcher has shut down.[/]")


if __name__ == "__main__":
    main()
