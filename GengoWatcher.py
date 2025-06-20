__version__ = "1.2.0"
__release_date__ = "2025-06-22"

import feedparser
import time
import webbrowser
from plyer import notification # pip install plyer
import os
import winsound
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
from rich.console import Console, Group
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
import re
import csv
import inspect

# Define a central theme for consistent styling across the application
APP_THEME = Theme({
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
    "table_header": "bold magenta"
})

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
            "log_file": "logs/gengowatcher.log",
            "notification_icon_path": "",
            "browser_path": "",  
            "browser_args": "--new-window {url}",
            "all_entries_log": "logs/all_entries.csv"  
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
        self.console = Console(theme=APP_THEME)
        self.config = {}
        self._config_parser = configparser.ConfigParser()
        self.last_seen_link = None
        self.shutdown_event = threading.Event()
        self.check_now_event = threading.Event()
        self.last_check_time = None
        self.total_new_entries_found = 0
        self.failure_count = 0
        self.current_action = "Initializing"
        self.config_lock = threading.Lock()

        self._load_config()
        self.last_seen_link = self.config["State"]["last_seen_link"] or None
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
        
        # Ensure log directory exists before writing config
        log_dir = Path(self.DEFAULT_CONFIG["Paths"]["log_file"]).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        
        with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
            parser.write(f)

        self.console.print(f"\nCreated default '[success]{self.CONFIG_FILE}[/]'.")
        self.console.print("Please edit this file with your preferences, then restart the script.")
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
            notification_icon_path_str = self._config_parser.get("Paths", "notification_icon_path", fallback="").strip()
            self.config["Paths"] = {
                "sound_file": Path(self._config_parser.get("Paths", "sound_file")),
                "log_file": Path(self._config_parser.get("Paths", "log_file")),
                "notification_icon_path": Path(notification_icon_path_str) if notification_icon_path_str else None,
                "browser_path": self._config_parser.get("Paths", "browser_path", fallback=""),
                "browser_args": self._config_parser.get("Paths", "browser_args", fallback="--new-window {url}"),
                "all_entries_log": Path(self._config_parser.get("Paths", "all_entries_log"))
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
        except (configparser.Error, ValueError) as e:
            self.console.print(f"[[error]Error[/]] reading configuration file '{self.CONFIG_FILE}': {e}")
            self.console.print("Please check the file's format. If unsure, delete it to regenerate.")
            sys.exit(1)

    def _save_runtime_state(self):
        with self.config_lock:
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
        log_file_path = self.config["Paths"]["log_file"]
        log_file_path.parent.mkdir(exist_ok=True, parents=True)
        self.log_all_entries_path = self.config["Paths"]["all_entries_log"]
        self.log_all_entries_path.parent.mkdir(exist_ok=True, parents=True)
        
        handlers = [RichHandler(console=self.console, rich_tracebacks=True, markup=True)]
        if self.config["Logging"]["log_main_enabled"]:
            handlers.append(RotatingFileHandler(
                log_file_path,
                maxBytes=self.config["Logging"]["log_max_bytes"],
                backupCount=self.config["Logging"]["log_backup_count"],
                encoding="utf-8"
            ))
        logging.basicConfig(level="INFO", format="%(message)s", datefmt="[%X]", handlers=handlers)
        self.logger = logging.getLogger("rich")

    def _log_all_entry(self, entry, reward):
        if not self.config["Logging"]["log_all_entries_enabled"]:
            return
        log_path = self.log_all_entries_path
        file_exists = log_path.is_file()
        try:
            with open(log_path, 'a', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["timestamp", "title", "reward_usd", "link"])
                writer.writerow([datetime.datetime.now().isoformat(), entry.get('title', '(No Title)'), f"{reward:.2f}", entry.get('link', '')])
        except Exception as e:
            self.logger.error(f"Failed to write to all-entries CSV log: {e}")

    def _setup_signal_handlers(self):
        signal.signal(signal.SIGINT, self.handle_exit)

    def _smart_wait(self, total_seconds: float) -> bool:
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
        if self.config["Paths"]["sound_file"].is_file():
            winsound.PlaySound(str(self.config["Paths"]["sound_file"]), winsound.SND_FILENAME)
        else:
            winsound.MessageBeep()
            self.logger.warning(f"Sound file not found: {self.config['Paths']['sound_file']}. Playing default beep.")

    def play_sound_async(self):
        threading.Thread(target=self.play_sound, daemon=True).start()

    def open_in_browser(self, url):
        browser_path_str = self.config["Paths"].get("browser_path", "")
        if not browser_path_str:
            webbrowser.open(url)
            self.logger.info(f"Opened URL in default browser: {url}")
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
        icon = self.config["Paths"]["notification_icon_path"]
        icon_path = str(icon) if icon and icon.is_file() else None
        try:
            notification.notify(title=title, message=message, app_name='GengoWatcher', app_icon=icon_path, timeout=8)
            self.logger.debug(f"Notification shown: {title} - {message}")
        except Exception as e:
            self.logger.error(f"Notification error: {e}")

    def show_notification(self, message, title="GengoWatcher", play_sound=False, open_link=False, url=None):
        if self.config["Watcher"]["enable_notifications"]:
            self.notify(title, message)
        if play_sound and self.config["Watcher"]["enable_sound"]:
            self.play_sound_async()
        if open_link and url:
            self.open_in_browser(url)

    def get_status_panel(self) -> Panel:
        status, status_color = ("Running", "success")
        if self.shutdown_event.is_set(): status, status_color = ("Stopped", "error")
        elif os.path.exists(self.PAUSE_FILE): status, status_color = ("Paused", "warning")
        
        last_check = self.last_check_time.strftime("%Y-%m-%d %H:%M:%S") if self.last_check_time else "Never"
        notif_enabled = "[success]Enabled[/]" if self.config["Watcher"]["enable_notifications"] else "[warning]Disabled[/]"
        sound_enabled = "[success]Enabled[/]" if self.config["Watcher"].get("enable_sound", True) else "[warning]Disabled[/]"
        
        min_reward = self.config["Watcher"].get("min_reward", 0.0)
        min_reward_status = f"[success]Enabled (US${min_reward:.2f})[/]" if min_reward > 0.0 else "[warning]Disabled[/]"

        table = Table(box=None, show_header=False, pad_edge=False)
        table.add_column("Label", style="label", justify="right", width=20)
        table.add_column("Value", style="value")
        
        table.add_row("Version:", f"v{__version__} ({__release_date__})")
        table.add_row("Status:", f"[{status_color}]{status}[/]")
        table.add_row("Current Action:", f"'{self.current_action}'")
        table.add_row()
        table.add_row("[table_header]Configuration[/]", "")
        table.add_row("Min Reward Filter:", min_reward_status)
        table.add_row("Notifications:", notif_enabled)
        table.add_row("Sound:", sound_enabled)
        table.add_row()
        table.add_row("[table_header]Session Stats[/]", "")
        table.add_row("New Jobs Found:", str(self.total_new_entries_found))
        table.add_row("Last Check:", last_check)
        table.add_row("Last Error:", str(self.last_error_message))
        
        return Panel(table, title="[title]GengoWatcher Status[/]", border_style="panel_border")

    def print_status(self):
        self.console.print(self.get_status_panel())

    def _extract_reward(self, entry) -> float:
        text_to_search = entry.get("title", "") + " | " + entry.get("summary", "")
        match = re.search(r"Reward:\s*(?:US\$|\$)?\s*(\d+\.?\d*)", text_to_search, re.IGNORECASE)
        if not match: return 0.0
        try:
            return float(match.group(1))
        except (ValueError, IndexError):
            self.logger.warning(f"Could not parse reward value from entry: '{entry.get('title', '')}'")
            return 0.0

    def _create_new_job_panel(self, entry, reward: float) -> Panel:
        title = entry.get("title", "No Title")
        link = entry.get("link", "#")
        lang_match = re.search(r"\|\s*([a-zA-Z\s]+/[a-zA-Z\s]+)", title)
        chars_match = re.search(r"\|\s*([\d,]+)\s*chars", title)
        language_pair = lang_match.group(1).strip() if lang_match else "N/A"
        char_count = chars_match.group(1).strip() if chars_match else "N/A"
        job_table = Table(box=None, show_header=False, pad_edge=False)
        job_table.add_column("Label", style="label", justify="right", width=15)
        job_table.add_column("Value", style="value")
        job_table.add_row("Reward:", f"[success]US$ {reward:.2f}[/]")
        job_table.add_row("Language Pair:", language_pair)
        job_table.add_row("Character Count:", char_count)
        job_table.add_row("Direct Link:", f"[link={link}]{link}[/link]")
        clean_title = title.split('|')[0].strip()
        return Panel(job_table, title="[title]✨ New Job Alert[/]", subtitle=f"[info]{clean_title}[/]", border_style="success")

    def _process_feed_entries(self, entries):
        if not entries:
            self.logger.info("Feed fetched, but it contains no entries to process.")
            return
        min_reward_threshold = self.config["Watcher"]["min_reward"]
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

        self.logger.info(f"Discovered {len(new_entries_to_process)} new entries. Filtering by minimum reward...")
        processed_count = 0
        for entry in reversed(new_entries_to_process):
            reward = self._extract_reward(entry)
            self._log_all_entry(entry, reward)
            
            if min_reward_threshold > 0.0 and reward < min_reward_threshold:
                self.logger.info(f"  -> Skipping job (Reward US${reward:.2f} is below minimum of US${min_reward_threshold:.2f})")
                continue
            
            processed_count += 1
            self.total_new_entries_found += 1
            self.console.print(self._create_new_job_panel(entry, reward))
            self.show_notification(message=entry.get("title", "(No Title)"), title="New Gengo Job Available!", play_sound=True, open_link=True, url=entry.get("link"))
        
        original_last_seen = self.last_seen_link
        self.last_seen_link = new_entries_to_process[0].get("link")
        
        if processed_count > 0 or self.last_seen_link != original_last_seen:
            self.logger.info(f"Processing complete. {processed_count} jobs met criteria. Updating state.")
            self._save_runtime_state()

    def fetch_rss(self):
        headers = {}
        if self.config["Watcher"]["use_custom_user_agent"]:
            headers['User-Agent'] = f"GengoWatcher/{__version__} (mailto:{self.config['Network']['user_agent_email']})"
        try:
            feed = feedparser.parse(self.config["Watcher"]["feed_url"], request_headers=headers)
            if feed.bozo:
                self.logger.warning(f"Malformed feed or parsing error: {feed.bozo_exception}")
                if not getattr(feed, 'entries', None): return None
            return feed
        except Exception as e:
            self.logger.error(f"RSS fetch error: {e}")
            self.last_error_message = str(e)
            return None

    def run(self):
        self.current_action = "Starting main loop"
        
        # --- NEW PRIMING LOGIC ---
        if not self.last_seen_link:
            self.console.print("[info]First run detected (no last seen link). Priming the feed...[/]")
            self.current_action = "Priming feed"
            initial_feed = self.fetch_rss()
            if initial_feed and initial_feed.entries:
                self.last_seen_link = initial_feed.entries[0].get("link")
                self._save_runtime_state()
                self.console.print("[success]Feed primed.[/])
                self.console.print("Will now watch for new entries.")
            else:
                self.logger.warning("Could not prime feed. Will check again on the next cycle.")
        # --- END OF PRIMING LOGIC ---

        base_interval = self.config["Watcher"]["check_interval"]
        backoff = base_interval
        max_backoff = self.config["Network"]["max_backoff"]
        is_paused = False

        while not self.shutdown_event.is_set():
            try:
                if os.path.exists(self.PAUSE_FILE):
                    if not is_paused:
                        self.logger.info(f"Pause file '{self.PAUSE_FILE}' detected. Pausing RSS checks.")
                        is_paused = True
                    self.current_action = "Paused"
                    time.sleep(1)
                    continue
                if is_paused:
                    self.logger.info(f"Pause file removed. Resuming RSS checks.")
                    is_paused = False
                
                self.current_action = "Fetching RSS feed..."
                feed = self.fetch_rss()
                if feed is None:
                    self.failure_count += 1
                    wait_time = min(backoff * self.failure_count, max_backoff)
                    self.logger.warning(f"RSS fetch failed. Backing off for {wait_time} seconds.")
                    self.current_action = f"Waiting {wait_time}s (backoff)"
                    if self._smart_wait(wait_time): break
                    self.check_now_event.clear()
                    continue
                
                self.last_check_time = datetime.datetime.now()
                self.failure_count = 0
                
                self.current_action = f"Processing {len(feed.entries)} entries..."
                self._process_feed_entries(feed.entries)
                
                self.current_action = f"Waiting {base_interval}s"
                self.check_now_event.clear()
                if self._smart_wait(base_interval): break
            
            except Exception as e:
                self.logger.error(f"An unexpected error occurred in the main loop: {e}", exc_info=True)
                self.last_error_message = str(e)
                self.current_action = "Error state"
                time.sleep(10)
        
        self.logger.info("Exiting main loop.")
        self.current_action = "Stopped"

    def _print_initialization_summary_rich(self):
        config_table = Table(box=None, show_header=False, pad_edge=False)
        config_table.add_column("Key", style="label", width=25)
        config_table.add_column("Value", style="value")
        for section_name, section_dict in self.config.items():
            if not isinstance(section_dict, dict): continue
            config_table.add_row(f"[{'table_header'}]{section_name} Settings[/{'table_header'}]")
            for key, value in section_dict.items():
                display_value, style_name = str(value), "value"
                if key in ["sound_file", "log_file", "notification_icon_path", "browser_path"]:
                    display_value, style_name = "[PATH_HIDDEN]", "path"
                elif key == "user_agent_email" and "@" in str(value):
                    display_value = f"{str(value).split('@')[0][:2]}...@{str(value).split('@')[1]}"
                config_table.add_row(key, Text(display_value, style=style_name))
            config_table.add_row()
        panel = Panel(config_table, title=f"[title]GengoWatcher Initialized[/]", subtitle=f"[info]v{__version__}[/]", border_style="panel_border")
        self.console.print(panel)

class CommandLineInterface:
    def __init__(self, watcher: GengoWatcher):
        self.watcher = watcher
        self.console = watcher.console
        self.commands = {
            "status": {"handler": self.watcher.print_status, "aliases": ["s", "st"], "help": "Show a static status dashboard."},
            "peek": {"handler": self._handle_peek, "aliases": ["live"], "help": "Show a live dashboard for 10s (e.g., `peek 20`)."},
            "check": {"handler": self._handle_check, "aliases": ["c", "now"], "help": "Trigger an immediate RSS feed check."},
            "help": {"handler": self.print_help, "aliases": ["h"], "help": "Display this list of commands."},
            "exit": {"handler": self._handle_exit, "aliases": ["q", "quit"], "help": "Save state and quit the application."},
            "pause": {"handler": self._handle_pause, "aliases": ["p"], "help": "Pause RSS checks."},
            "resume": {"handler": self._handle_resume, "aliases": ["r"], "help": "Resume RSS checks."},
            "togglesound": {"handler": self._handle_toggle_sound, "aliases": ["ts"], "help": "Toggle sound alerts on/off."},
            "togglenotifications": {"handler": self._handle_toggle_notifications, "aliases": ["tn"], "help": "Toggle desktop notifications on/off."},
            "setminreward": {"handler": self._handle_set_min_reward, "aliases": ["smr"], "help": "Set min reward (e.g., `smr 5.50`)."},
            "reloadconfig": {"handler": self._handle_reload_config, "aliases": ["rl"], "help": "Reload all settings from config.ini."},
            "restart": {"handler": self._handle_restart, "aliases": [], "help": "Restart the entire script."},
            "notifytest": {"handler": self._handle_notify_test, "aliases": ["nt"], "help": "Send a test notification."}
        }
        self.alias_map = {alias: cmd for cmd, details in self.commands.items() for alias in [cmd] + details["aliases"]}
        self.OK = "[success][+][/success]"
        self.WARN = "[warning][!][/warning]"
        self.ERR = "[error][-][/error]"
        self.INFO = "[info][>][/info]"

    def run(self):
        self.console.print(f"{self.INFO} Type 'help' for commands.")
        try:
            while not self.watcher.shutdown_event.is_set():
                cmd_full = self.console.input("[bold]>>> [/]").strip()
                if cmd_full: self.handle_command(cmd_full)
        except KeyboardInterrupt:
            self.console.print("\nKeyboard interrupt received.")
            self._handle_exit()

    def handle_command(self, cmd_full: str):
        parts = cmd_full.split()
        command_alias, args = parts[0].lower(), parts[1:]
        primary_command = self.alias_map.get(command_alias)
        if not primary_command:
            self.console.print(f"{self.ERR} Unknown command: '{command_alias}'")
            return
        handler = self.commands[primary_command]["handler"]
        try:
            sig = inspect.signature(handler)
            if 'args' in sig.parameters: handler(args)
            else: handler()
        except Exception as e:
            self.watcher.logger.error(f"Error executing command '{primary_command}': {e}", exc_info=True)
            self.console.print(f"{self.ERR} An error occurred: {e}")

    def print_help(self):
        help_table = Table(box=None, show_header=False, pad_edge=False)
        help_table.add_column("Command", style="label")
        help_table.add_column("Aliases", style="info")
        help_table.add_column("Description", style="value")
        for command, details in self.commands.items():
            aliases = ", ".join(details["aliases"])
            help_table.add_row(f"[header]{command}[/]", aliases, details["help"])
        panel = Panel(help_table, title="[title]GengoWatcher Commands[/]", border_style="panel_border")
        self.console.print(panel)

    def _handle_exit(self):
        self.console.print("Exiting...")
        self.watcher.handle_exit()

    def _handle_check(self):
        self.watcher.logger.info("Manual check requested via command.")
        self.watcher.check_now_event.set()

    def _handle_pause(self):
        if not os.path.exists(self.watcher.PAUSE_FILE):
            with open(self.watcher.PAUSE_FILE, "w") as f: f.write("Paused.")
            self.console.print(f" {self.OK} Watcher paused.")
        else: self.console.print(f" {self.WARN} Watcher is already paused.")

    def _handle_resume(self):
        if os.path.exists(self.watcher.PAUSE_FILE):
            os.remove(self.watcher.PAUSE_FILE)
            self.console.print(f" {self.OK} Watcher resumed.")
        else: self.console.print(f" {self.WARN} Watcher is not paused.")

    def _handle_toggle_sound(self):
        with self.watcher.config_lock:
            new_val = not self.watcher.config["Watcher"].get("enable_sound", True)
            self.watcher.config["Watcher"]["enable_sound"] = new_val
            self.watcher._save_runtime_state()
        self.console.print(f" {self.OK} Sound {'enabled' if new_val else 'disabled'}.")

    def _handle_toggle_notifications(self):
        with self.watcher.config_lock:
            new_val = not self.watcher.config["Watcher"].get("enable_notifications", True)
            self.watcher.config["Watcher"]["enable_notifications"] = new_val
            self.watcher._save_runtime_state()
        self.console.print(f" {self.OK} Notifications {'enabled' if new_val else 'disabled'}.")

    def _handle_set_min_reward(self, args):
        if len(args) != 1:
            self.console.print(f" {self.ERR} Usage: setminreward <amount>")
            return
        try:
            new_val = float(args[0])
            with self.watcher.config_lock:
                self.watcher.config["Watcher"]["min_reward"] = new_val
                self.watcher._save_runtime_state()
            self.console.print(f" {self.OK} Minimum reward set to US${new_val:.2f}.")
        except ValueError:
            self.console.print(f" {self.ERR} Invalid amount.")

    def _handle_reload_config(self):
        try:
            self.watcher._load_config()
            self.watcher._setup_logging()
            self.console.print(f" {self.OK} Configuration reloaded.")
        except Exception as e:
            self.console.print(f" {self.ERR} Failed to reload configuration: {e}")

    def _handle_restart(self):
        self.console.print(f" {self.INFO} Restarting GengoWatcher...")
        self.watcher.handle_exit()
        python = sys.executable
        os.execv(python, [python] + sys.argv)

    def _handle_notify_test(self):
        self.watcher.logger.info("Notification test command triggered.")
        self.watcher.show_notification(
            message="This is a notification test!",
            title="GengoWatcher Test",
            play_sound=True,
            open_link=True,
            url="https://gengo.com/t/jobs/status/available"
        )
        
    def _handle_peek(self, args):
        try: duration = int(args[0]) if args else 10
        except (ValueError, IndexError): duration = 10
        self.console.print(f"{self.INFO} Showing live status for {duration} seconds...")
        from rich.live import Live
        with Live(self.watcher.get_status_panel(), console=self.console, refresh_per_second=2, transient=True) as live:
            time.sleep(duration)
        self.console.print(f"{self.INFO} Live view finished.")

if __name__ == "__main__":
    watcher = GengoWatcher()
    watcher_thread = threading.Thread(target=watcher.run, daemon=True, name="WatcherThread")
    watcher_thread.start()
    cli = CommandLineInterface(watcher)
    cli.run()
    watcher_thread.join(timeout=5)
    watcher.logger.info("Program exited cleanly.")
    sys.exit(0)