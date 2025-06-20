__version__ = "1.1.2"
__release_date__ = "2025-06-21"

import feedparser
import time
import webbrowser
from plyer import notification # pip install plyer
import os
import winsound
from win10toast import ToastNotifier
import signal
import sys
import threading
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import configparser
import datetime
import subprocess
import rich
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import re
import csv

class GengoWatcher:
    CONFIG_FILE = "config.ini"
    PAUSE_FILE = "gengowatcher.pause"

    DEFAULT_CONFIG = {
        "Watcher": {
            "feed_url": "https://www.theguardian.com/uk/rss",
            "check_interval": "31",
            "min_reward": "0.0",  
            "enable_notifications": "True",
            "use_custom_user_agent": "False",
            "enable_sound": "True"  
        },
        "Paths": {
            "sound_file": r"C:\\path\\to\\your\\sound.wav",
            "vivaldi_path": r"C:\\path\\to\\your\\vivaldi.exe",
            "log_file": "rss_check_log.txt",
            "notification_icon_path": "",
            "browser_path": "",  
            "browser_args": "--new-window {url}",
            "all_entries_log": "all_entries_log.txt"  
        },
        "Logging": {
            "log_max_bytes": "1000000",
            "log_backup_count": "3",
            "log_main_enabled": "True",
            "log_all_entries_enabled": "True"
        },
        "Network": {
            "max_backoff": "300",
            "user_agent_email": "your_email@example.com"
        },
        "State": {
            "last_seen_link": "",
            "total_new_entries_found": "0"
        }
    }

    def __init__(self):
        self.console = Console()
        self.config = {}
        self._config_parser = configparser.ConfigParser()
        self.last_seen_link = None
        self.shutdown_event = threading.Event()
        self.check_now_event = threading.Event()
        self.last_check_time = None
        self.notifier = ToastNotifier()
        self.total_new_entries_found = 0
        self.failure_count = 0
        self.current_action = "Initializing"
        self.config_lock = threading.Lock()  # Thread-safety for config

        self._load_config()
        self.last_seen_link = self.config["State"]["last_seen_link"] if self.config["State"]["last_seen_link"] else None
        self.total_new_entries_found = int(self.config["State"]["total_new_entries_found"])

        self._setup_logging()
        self._setup_signal_handlers()
        self.last_error_message = "None"

        self._print_initialization_summary_rich()  
        self.logger.info("Command listener active. Type 'help' for commands.")
        self.start_time = time.time()


    def _create_default_config(self):
        parser = configparser.ConfigParser()
        for section, settings in self.DEFAULT_CONFIG.items():
            parser.add_section(section)
            for key, value in settings.items():
                parser.set(section, key, value)

        with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
            parser.write(f)

        print(f"\nCreated default '{self.CONFIG_FILE}'.")
        print("Please edit this file with your specific paths and preferences, then restart the script.")
        print("Ensure 'feed_url' has your correct RSS key.")
        print("Remember to change 'user_agent_email' if 'use_custom_user_agent' is enabled.")
        sys.exit(0)

    def _load_config(self):
        if not Path(self.CONFIG_FILE).is_file():
            self._create_default_config()

        self._config_parser.read(self.CONFIG_FILE, encoding='utf-8')

        try:
            self.config["Watcher"] = {
                "feed_url": self._config_parser.get("Watcher", "feed_url"),
                "check_interval": self._config_parser.getint("Watcher", "check_interval"),
                "min_reward": self._config_parser.getfloat("Watcher", "min_reward", fallback=0.0),
                "enable_notifications": self._config_parser.getboolean("Watcher", "enable_notifications"),
                "use_custom_user_agent": self._config_parser.getboolean("Watcher", "use_custom_user_agent", fallback=False),
                "enable_sound": self._config_parser.getboolean("Watcher", "enable_sound", fallback=True)
            }

            notification_icon_path_str = self._config_parser.get("Paths", "notification_icon_path").strip()
            self.config["Paths"] = {
                "sound_file": Path(self._config_parser.get("Paths", "sound_file")),
                "vivaldi_path": Path(self._config_parser.get("Paths", "vivaldi_path")),
                "log_file": Path(self._config_parser.get("Paths", "log_file")),
                "notification_icon_path": Path(notification_icon_path_str) if notification_icon_path_str else None,
                "browser_path": self._config_parser.get("Paths", "browser_path", fallback=""),
                "browser_args": self._config_parser.get("Paths", "browser_args", fallback="--new-window {url}"),
                "all_entries_log": Path(self._config_parser.get("Paths", "all_entries_log"))  # Load all_entries_log path
            }

            self.config["Logging"] = {
                "log_max_bytes": self._config_parser.getint("Logging", "log_max_bytes"),
                "log_backup_count": self._config_parser.getint("Logging", "log_backup_count"),
                "log_main_enabled": self._config_parser.getboolean("Logging", "log_main_enabled", fallback=True),
                "log_all_entries_enabled": self._config_parser.getboolean("Logging", "log_all_entries_enabled", fallback=True)
            }

            self.config["Network"] = {
                "max_backoff": self._config_parser.getint("Network", "max_backoff"),
                "user_agent_email": self._config_parser.get("Network", "user_agent_email", fallback=self.DEFAULT_CONFIG["Network"]["user_agent_email"])
            }

            self.config["State"] = {
                "last_seen_link": self._config_parser.get("State", "last_seen_link", fallback=""),
                "total_new_entries_found": self._config_parser.getint("State", "total_new_entries_found", fallback=0)
            }

        except configparser.Error as e:
            print(f"Error reading configuration file '{self.CONFIG_FILE}': {e}")
            print("Please check the file's format and content. If unsure, delete it to regenerate a default.")
            sys.exit(1)

    def _save_runtime_state(self):
        if not self._config_parser.has_section("State"):
            self._config_parser.add_section("State")

        self._config_parser.set("State", "last_seen_link", self.last_seen_link if self.last_seen_link else "")
        self._config_parser.set("State", "total_new_entries_found", str(self.total_new_entries_found))

        if not self._config_parser.has_section("Watcher"):
            self._config_parser.add_section("Watcher")
        self._config_parser.set("Watcher", "enable_sound", str(self.config["Watcher"].get("enable_sound", True)))
        self._config_parser.set("Watcher", "enable_notifications", str(self.config["Watcher"].get("enable_notifications", True)))
        self._config_parser.set("Watcher", "min_reward", str(self.config["Watcher"].get("min_reward", 0.0)))
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                self._config_parser.write(f)
            self.logger.debug("Runtime state saved.")
        except IOError as e:
            self.logger.error(f"Failed to save runtime state to {self.CONFIG_FILE}: {e}")

    def _setup_logging(self):
        """Sets up logging to both a file and the rich console, with toggles."""
        log_file_path = Path(self.config["Paths"]["log_file"])
        log_file_path.parent.mkdir(exist_ok=True)
        self.log_main_enabled = self.config.get("Logging", {}).get("log_main_enabled", True)
        self.log_all_entries_enabled = self.config.get("Logging", {}).get("log_all_entries_enabled", False)
        self.all_entries_log_path = Path(self.config["Paths"].get("all_entries_log", "all_entries_log.txt"))
        self.all_entries_log_path.parent.mkdir(exist_ok=True)
        handlers = [
            RichHandler(
                console=self.console,
                rich_tracebacks=True,
                markup=True
            )
        ]
        if self.log_main_enabled:
            handlers.append(RotatingFileHandler(
                log_file_path,
                maxBytes=self.config["Logging"]["log_max_bytes"],
                backupCount=self.config["Logging"]["log_backup_count"],
                encoding="utf-8"
            ))
        logging.basicConfig(
            level="INFO",
            format="%(message)s",
            datefmt="[%X]",
            handlers=handlers
        )
        self.logger = logging.getLogger("rich")

    def _log_all_entry(self, entry, reward):
        if not getattr(self, 'log_all_entries_enabled', False):
            return
        log_path = self.all_entries_log_path
        file_exists = log_path.is_file()
        try:
            with open(log_path, 'a', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["timestamp", "title", "reward_usd", "link"])
                writer.writerow([
                    datetime.datetime.now().isoformat(),
                    entry.get('title', '(No Title)'),
                    f"{reward:.2f}",
                    entry.get('link', '')
                ])
        except Exception as e:
            self.error(f"Failed to write to all-entries CSV log: {e}")

    def _setup_signal_handlers(self):
        signal.signal(signal.SIGINT, self.handle_exit)

    def _smart_wait(self, total_seconds: float) -> bool:
        """Waits up to total_seconds for shutdown or manual check."""
        self.check_now_event.wait(timeout=total_seconds)
        return self.shutdown_event.is_set()

    def handle_exit(self, signum=None, frame=None):
        if not self.shutdown_event.is_set():
            self.logger.info("Shutdown signal received.")
            self.shutdown_event.set()
            self.logger.debug("Saving runtime state...")
            self._save_runtime_state()
            self.logger.debug("Shutdown complete.")
        sys.exit(0)

    def play_sound(self):
        try:
            if not self.config["Watcher"].get("enable_sound", True):
                self.logger.debug("Sound is disabled in config.")
                return
            if self.config["Paths"]["sound_file"].is_file():
                winsound.PlaySound(str(self.config["Paths"]["sound_file"]), winsound.SND_FILENAME)
            else:
                winsound.MessageBeep()
                self.logger.warning(f"Sound file not found: {self.config['Paths']['sound_file']}. Playing default beep.")
        except Exception as e:
            self.logger.error(f"Sound error: {e}")

    def play_sound_async(self):
        threading.Thread(target=self.play_sound, daemon=True).start()

    def open_in_browser(self, url):
        browser_path_str = self.config["Paths"].get("browser_path", "")
        if not browser_path_str:
            try:
                webbrowser.open(url)
                self.logger.info(f"Opened URL in default browser: {url}")
            except Exception as e:
                self.logger.error(f"Failed to open URL in default browser: {e}")
            return
        browser_path = Path(browser_path_str)
        if not browser_path.is_file():
            self.logger.warning(f"Browser path invalid or not set: {browser_path}")
            return
        try:
            browser_args_template = self.config["Paths"].get("browser_args", "{url}")
            final_args = [arg.format(url=url) for arg in browser_args_template.split()]
            subprocess.Popen([str(browser_path)] + final_args)
            self.logger.debug(f"Opened URL using custom browser: {browser_path}")
        except Exception as e:
            self.logger.error(f"Failed to open URL in custom browser: {e}")

    def notify(self, title, message):
        if not self.config["Watcher"]["enable_notifications"]:
            self.logger.debug("Notifications are disabled in config.")
            return
        icon = None
        if self.config["Paths"]["notification_icon_path"] and self.config["Paths"]["notification_icon_path"].is_file():
            icon = str(self.config["Paths"]["notification_icon_path"])
        try:
            notification.notify(
                title=title,
                message=message,
                app_name='GengoWatcher',
                app_icon=icon,
                timeout=8
            )
            self.logger.debug(f"Notification shown: {title} - {message}")
        except Exception as e:
            self.logger.error(f"Notification error: {e}")

    def show_notification(self, message, title="GengoWatcher", play_sound=False, open_link=False, url=None):
        self.notify(title, message)
        play_sound_enabled = True
        with self.config_lock:
            play_sound_enabled = self.config["Watcher"].get("enable_sound", True)
        if play_sound and play_sound_enabled:
            self.play_sound_async()
        if open_link and url:
            self.open_in_browser(url)

    def print_status(self):
        # Use rich Table and Panel for dashboard
        status = "Running"
        status_color = "green"
        if self.shutdown_event.is_set():
            status, status_color = "Stopped", "red"
        elif os.path.exists(self.PAUSE_FILE):
            status, status_color = "Paused", "yellow"
        last_check = self.last_check_time.strftime("%Y-%m-%d %H:%M:%S") if self.last_check_time else "Never"
        notif_enabled = "[green]Enabled[/]" if self.config["Watcher"]["enable_notifications"] else "[yellow]Disabled[/]"
        sound_enabled = "[green]Enabled[/]" if self.config["Watcher"].get("enable_sound", True) else "[yellow]Disabled[/]"
        vivaldi_configured = "[green]Yes[/]" if bool(self.config["Paths"]["vivaldi_path"] and self.config["Paths"]["vivaldi_path"].is_file()) else "[red]No[/]"
        uptime_seconds = int(time.time() - self.start_time) if hasattr(self, 'start_time') else 0
        uptime_str = str(datetime.timedelta(seconds=uptime_seconds))
        version = globals().get("__version__", "?")
        release_date = globals().get("__release_date__", "?")
        min_reward = self.config["Watcher"].get("min_reward", 0.0)
        if min_reward > 0.0:
            min_reward_status = f"[green]Enabled[/] (US${min_reward:.2f})"
        else:
            min_reward_status = "[yellow]Disabled[/]"
        table = Table(box=None, show_header=False, expand=False)
        table.add_row("[bold white]Version:[/]", f"v{version} ({release_date})")
        table.add_row("[bold white]Status:[/]", f"[{status_color}]{status}[/]")
        table.add_row("[bold white]Uptime:[/]", uptime_str)
        table.add_row("[bold white]Current Action:[/]", f"'{self.current_action}'")
        table.add_row("[bold magenta] ── Configuration ──[/]", "")
        table.add_row("[bold white]Polling Interval:[/]", f"{self.config['Watcher']['check_interval']} seconds")
        table.add_row("[bold white]Notifications:[/]", notif_enabled)
        table.add_row("[bold white]Sound:[/]", sound_enabled)
        table.add_row("[bold white]Vivaldi Path Set:[/]", vivaldi_configured)
        table.add_row("[bold white]Min Reward Filter:[/]", min_reward_status)
        table.add_row("[bold magenta] ── Session Stats ──[/]", "")
        table.add_row("[bold white]New Posts Found:[/]", str(self.total_new_entries_found))
        table.add_row("[bold white]Last Check Time:[/]", last_check)
        table.add_row("[bold white]Last Error:[/]", str(getattr(self, 'last_error_message', 'None')))
        self.console.print(Panel(table, title="GengoWatcher Status", border_style="magenta"))

    def _extract_reward(self, entry) -> float:
        """
        Extracts the monetary reward from an RSS feed entry's title or summary.
        """
        text_to_search = entry.get("title", "") + " | " + entry.get("summary", "")
        match = re.search(r"Reward:\s*(?:US\\$|\\$)?\s*(\d+\.?\d*)", text_to_search, re.IGNORECASE)
        if not match:
            return 0.0
        try:
            reward_value = float(match.group(1))
            return reward_value
        except (ValueError, IndexError):
            self.logger.warning(f"Could not parse reward value from entry: '{entry.get('title', '')}'")
            return 0.0

    def _process_feed_entries(self, entries):
        """
        Processes entries from the RSS feed, filtering by minimum reward, and handling new items.
        """
        if not entries:
            self.logger.info("Feed was fetched, but it contains no entries to process.")
            return
        min_reward_threshold = self.config["Watcher"].get("min_reward", 0.0)
        new_entries_to_process = []
        for entry in entries:
            link = entry.get("link")
            if not link:
                self.logger.warning("Found an entry with no link, skipping.")
                continue
            if link == self.last_seen_link:
                break
            new_entries_to_process.append(entry)
        if not new_entries_to_process:
            self.logger.info("No new entries detected since last check.")
            return
        entry_count = len(new_entries_to_process)
        plural = "entries" if entry_count > 1 else "entry"
        self.logger.info(f"Discovered {entry_count} new {plural}. Filtering by minimum reward...")
        processed_count = 0
        for entry in reversed(new_entries_to_process):
            title = entry.get("title", "(No Title)")
            link = entry.get("link")
            reward = self._extract_reward(entry)
            self._log_all_entry(entry, reward)
            if min_reward_threshold > 0.0 and reward < min_reward_threshold:
                self.logger.info(
                    f"  -> Skipping job: '{title}' (Reward US${reward:.2f} is below minimum of US${min_reward_threshold:.2f})"
                )
                continue
            processed_count += 1
            self.logger.info(f"  -> New Job: '{title}' (Reward: US${reward:.2f})")
            self.total_new_entries_found += 1
            self.show_notification(
                message=title,
                title="New Gengo Job Available!",
                play_sound=True,
                open_link=True,
                url=link
            )
        self.last_seen_link = new_entries_to_process[0].get("link")
        if processed_count > 0:
            self.logger.info(f"Processing complete. {processed_count} jobs met the criteria. Total found this session: {self.total_new_entries_found}")
        else:
            self.logger.info("Processing complete. No new jobs met the minimum reward criteria.")
        self._save_runtime_state()

    def fetch_rss(self):
        headers = {}
        if self.config["Watcher"]["use_custom_user_agent"]:
            user_agent = f"GengoWatcher/1.0 (mailto:{self.config['Network']['user_agent_email']})"
            headers['User-Agent'] = user_agent

        url = self.config["Watcher"]["feed_url"]

        try:
            feed = feedparser.parse(url, request_headers=headers)
            if feed.bozo:
                self.logger.warning(f"Malformed feed or parsing error: {feed.bozo_exception}")
                if not hasattr(feed, 'entries') or not feed.entries:
                    return None  # Treat as failure only if entries are truly missing
            return feed
        except Exception as e:
            self.logger.error(f"RSS fetch error: {e}")
            self.last_error_message = str(e)
            return None

    def run(self):
        self.logger.info("Starting main RSS check loop...")
        self.current_action = "Starting main loop"
        base_interval = self.config["Watcher"]["check_interval"]
        backoff = base_interval
        max_backoff = self.config["Network"]["max_backoff"]
        is_paused = False

        while not self.shutdown_event.is_set():
            try:
                # --- Pause/Resume Logic ---
                if os.path.exists(self.PAUSE_FILE):
                    if not is_paused:
                        msg = f"Pause file '{self.PAUSE_FILE}' detected. Pausing RSS checks."
                        self.logger.info(msg)
                        print(f"[PAUSED] {msg}")
                        is_paused = True
                    self.current_action = "Paused (waiting for resume)"
                    while os.path.exists(self.PAUSE_FILE) and not self.shutdown_event.is_set():
                        time.sleep(1)
                    if self.shutdown_event.is_set():
                        break
                    msg = f"Pause file '{self.PAUSE_FILE}' removed. Resuming RSS checks."
                    self.logger.info(msg)
                    print(f"[RESUMED] {msg}")
                    is_paused = False
                    self.current_action = "Resumed (preparing to fetch RSS)"
                    continue
                # --- End Pause/Resume Logic ---
                self.current_action = "Fetching RSS feed"
                self.logger.info("Fetching RSS feed...")
                feed = self.fetch_rss()
                if feed is None:
                    self.logger.warning(f"RSS fetch failed or no entries. Failure count: {self.failure_count + 1}")
                    self.failure_count += 1
                    wait_time = min(backoff, max_backoff)
                    self.logger.info(f"Backing off for {wait_time} seconds.")
                    self.current_action = f"Waiting {wait_time}s (backoff after failure)"
                    if self._smart_wait(wait_time):
                        break
                    self.check_now_event.clear()
                    backoff *= 2
                    continue
                self.last_check_time = datetime.datetime.now()
                self.failure_count = 0
                backoff = base_interval
                if not feed.entries:
                    self.logger.info("RSS feed fetched successfully but no new entries found.")
                    wait_seconds = self.config["Watcher"]["check_interval"]
                    self.logger.info(f"Waiting {wait_seconds} seconds before next check.")
                    self.current_action = f"Waiting {wait_seconds}s (no new entries)"
                    self.check_now_event.clear()
                    if self._smart_wait(wait_seconds):
                        break
                    continue
                self.current_action = f"Processing {len(feed.entries)} new entries"
                self._process_feed_entries(feed.entries)
                wait_seconds = self.config["Watcher"]["check_interval"]
                self.logger.info(f"Next check in {wait_seconds} seconds.")
                self.current_action = f"Waiting {wait_seconds}s (after processing entries)"
                self.check_now_event.clear()
                if self._smart_wait(wait_seconds):
                    break
            except Exception as e:
                self.logger.error(f"Unexpected error: {e}")
                self.last_error_message = str(e)
                self.current_action = f"Error: {e}"
                time.sleep(10)
        self.logger.info("Exiting main loop.")
        self.current_action = "Stopped"

    def _print_initialization_summary_rich(self):
        """Prints a clean, formatted summary using the rich library."""
        version = globals().get("__version__", "?")
        config_table = Table(box=None, show_header=False, pad_edge=False)
        config_table.add_column("Key", style="cyan")
        config_table.add_column("Value")
        for section_name, section_dict in self.config.items():
            if not isinstance(section_dict, dict):
                continue
            config_table.add_row(f"[bold white]── {section_name} Settings ──", style="magenta")
            for key, value in section_dict.items():
                display_value = str(value)
                style = ""
                if key in ["sound_file", "vivaldi_path", "log_file", "notification_icon_path", "browser_path"]:
                    display_value, style = "[PATH_HIDDEN]", "yellow"
                elif key == "user_agent_email" and "@" in str(value):
                    parts = str(value).split("@")
                    display_value = f"{parts[0][:2]}...@{parts[1]}"
                config_table.add_row(key, Text(display_value, style=style))
            config_table.add_row()
        panel = Panel(
            config_table,
            title="[bold magenta]GengoWatcher Initialized[/]",
            subtitle=f"[cyan]v{version}[/]",
            border_style="magenta"
        )
        self.console.print(panel)

    def print_help_rich(self):
        commands = {
            "Core Controls": {
                "status": "Show the real-time status dashboard.",
                "check": "Trigger an immediate RSS feed check.",
                "exit": "Save state and gracefully quit the application."
            },
            "Watcher Management": {
                "pause": "Pause RSS checks (by creating a pause file).",
                "resume": "Resume RSS checks (by deleting the pause file).",
                "restart": "Restart the entire script.",
            },
            "Settings & Tests": {
                "togglesound": "Toggle sound alerts on/off.",
                "togglenotifications": "Toggle desktop notifications on/off.",
                "reloadconfig": "Reload all settings from config.ini.",
                "notifytest": "Send a test notification to check settings.",
                "togglemainlog": "Toggle the main log file on/off.",
                "toggleallentrieslog": "Toggle the all-entries log on/off.",
                "setminreward": "Set the minimum reward threshold for jobs (e.g. setminreward 2.50).",
            }
        }
        help_table = Table(box=None, show_header=False, pad_edge=False)
        help_table.add_column("Command", style="yellow", width=25)
        help_table.add_column("Description", style="cyan")
        for category, cmds in commands.items():
            help_table.add_row(f"[bold bright_white]-- {category} --", style="white")
            for cmd, desc in cmds.items():
                help_table.add_row(f"  {cmd}", desc)
            help_table.add_row()
        panel = Panel(
            help_table,
            title="[bold]GengoWatcher Commands[/]",
            border_style="magenta",
            padding=(1, 2)
        )
        self.console.print(panel)

    def warn(self, message):
        self.logger.warning(message)
        self.console.print(f"[bold yellow][!][/bold yellow] {message}")

    def error(self, message):
        self.logger.error(message)
        self.console.print(f"[bold red][-][/bold red] {message}")

    def is_min_reward_enabled(self):
        # Treat 0.0 as disabled, any other value as enabled
        return self.config["Watcher"].get("min_reward", 0.0) > 0.0

class CommandLineInterface:
    def __init__(self, watcher: GengoWatcher):
        self.watcher = watcher
        self.console = watcher.console
        self.OK = "[bold green][+][/bold green]"
        self.WARN = "[bold yellow][!][/bold yellow]"
        self.ERR = "[bold red][-][/bold red]"
        self.INFO = "[bold cyan][>][/bold cyan]"

    def run(self):
        self.console.print("[bold cyan][>][/] Type 'help' for commands. Type 'exit' to quit.")
        try:
            while not self.watcher.shutdown_event.is_set():
                cmd = self.console.input("[bold]>>> [/] ").strip()
                self.handle_command(cmd)
        except KeyboardInterrupt:
            self.watcher.logger.info("Keyboard interrupt received in main thread.")
            self.watcher.handle_exit()

    def handle_command(self, cmd: str):
        cmd_lower = cmd.lower()
        if cmd_lower in ("exit", "quit", "stop", "end", "ex", "qu"):
            self.console.print("Exiting...")
            self.watcher.shutdown_event.set()
            return
        elif cmd_lower == "check":
            self.watcher.logger.info("Manual check requested via command.")
            self.watcher.check_now_event.set()
        elif cmd_lower == "status":
            self.watcher.print_status()
        elif cmd_lower == "pause":
            if not os.path.exists(self.watcher.PAUSE_FILE):
                with open(self.watcher.PAUSE_FILE, "w") as f:
                    f.write("Paused by user command.\n")
                self.console.print(f" {self.OK} Watcher paused. Enter 'resume' to continue.")
                self.watcher.logger.info(f"Pause file '{self.watcher.PAUSE_FILE}' created by user command.")
            else:
                self.console.print(f" {self.WARN} Watcher is already paused.")
        elif cmd_lower == "resume":
            if os.path.exists(self.watcher.PAUSE_FILE):
                try:
                    os.remove(self.watcher.PAUSE_FILE)
                    self.console.print(f" {self.OK} Watcher resumed.")
                    self.watcher.logger.info(f"Pause file '{self.watcher.PAUSE_FILE}' removed by user command.")
                except Exception as e:
                    self.console.print(f" {self.ERR} Failed to remove pause file: {e}")
                    self.watcher.logger.error(f"Failed to remove pause file: {e}")
            else:
                self.console.print(f" {self.WARN} Watcher is not paused.")
        elif cmd_lower == "togglesound":
            with self.watcher.config_lock:
                current = self.watcher.config["Watcher"].get("enable_sound", True)
                new_val = not current
                self.watcher.config["Watcher"]["enable_sound"] = new_val
                self.watcher._save_runtime_state()
            status_text = f"{'enabled' if new_val else 'disabled'}"
            self.console.print(f" {self.OK} Sound {status_text}.")
            self.watcher.logger.info(f"Sound {status_text} by user command.")
        elif cmd_lower == "togglenotifications":
            with self.watcher.config_lock:
                current = self.watcher.config["Watcher"].get("enable_notifications", True)
                new_val = not current
                self.watcher.config["Watcher"]["enable_notifications"] = new_val
                self.watcher._save_runtime_state()
            status_text = f"{'enabled' if new_val else 'disabled'}"
            self.console.print(f" {self.OK} Notifications {status_text}.")
            self.watcher.logger.info(f"Notifications {status_text} by user command.")
        elif cmd_lower == "togglemainlog":
            self.watcher.log_main_enabled = not self.watcher.log_main_enabled
            self.watcher.config["Logging"]["log_main_enabled"] = self.watcher.log_main_enabled
            self.watcher._save_runtime_state()
            self.console.print(f" {self.OK} Main log {'enabled' if self.watcher.log_main_enabled else 'disabled'}.")
            self.watcher._setup_logging()
        elif cmd_lower == "toggleallentrieslog":
            self.watcher.log_all_entries_enabled = not self.watcher.log_all_entries_enabled
            self.watcher.config["Logging"]["log_all_entries_enabled"] = self.watcher.log_all_entries_enabled
            self.watcher._save_runtime_state()
            self.console.print(f" {self.OK} All-entries log {'enabled' if self.watcher.log_all_entries_enabled else 'disabled'}.")
        elif cmd_lower.startswith("setminreward"):
            parts = cmd.split()
            if len(parts) == 2:
                try:
                    new_val = float(parts[1])
                    with self.watcher.config_lock:
                        self.watcher.config["Watcher"]["min_reward"] = new_val
                        self.watcher._config_parser.set("Watcher", "min_reward", str(new_val))
                        self.watcher._save_runtime_state()
                    self.console.print(f" {self.OK} Minimum reward set to US${new_val:.2f}.")
                    self.watcher.logger.info(f"Minimum reward set to US${new_val:.2f} by user command.")
                except ValueError:
                    self.console.print(f" {self.ERR} Invalid value for minimum reward. Usage: setminreward 2.50")
            else:
                self.console.print(f" {self.INFO} Usage: setminreward <amount>")
        elif cmd_lower == "help":
            self.watcher.print_help_rich()
        elif cmd == "reloadconfig":
            try:
                self.watcher._load_config()
                self.watcher._setup_logging()
                self.console.print(f" {self.OK} Configuration reloaded.")
                self.watcher.logger.info("Configuration reloaded by user command.")
            except Exception as e:
                self.console.print(f" {self.ERR} Failed to reload configuration: {e}")
                self.watcher.logger.error(f"Failed to reload configuration: {e}")
        elif cmd == "restart":
            self.console.print(f" {self.INFO} Restarting GengoWatcher...")
            self.watcher.logger.info("Restart command received. Restarting script.")
            self.watcher.shutdown_event.set()
            self.watcher._save_runtime_state()
            # Wait for watcher thread to finish
            # Restart the script
            import sys, os
            python = sys.executable
            os.execv(python, [python] + sys.argv)
        elif cmd == "notifytest":
            self.watcher.logger.info("Notification test command triggered.")
            test_url = "https://gengo.com/t/jobs/status/available" # Example URL
            self.watcher.show_notification(
                "This is a notification test!",
                title="GengoWatcher Test",
                play_sound=True,
                open_link=True,
                url=test_url
            )
        else:
            self.console.print(f"Unknown command: {cmd}")

if __name__ == "__main__":
    watcher = GengoWatcher()
    watcher_thread = threading.Thread(target=watcher.run, daemon=True, name="WatcherThread")
    watcher_thread.start()
    cli = CommandLineInterface(watcher)
    cli.run()
    watcher_thread.join(timeout=5)
    watcher.logger.info("Program exited cleanly.")
    sys.exit(0)

