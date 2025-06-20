__version__ = "1.2.0"
__release_date__ = "2025-06-22"

import feedparser
import time
import webbrowser
from plyer import notification
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
from rich.live import Live
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich.layout import Layout
import re
import csv
import inspect
import collections

# Platform-specific imports for non-blocking input
try:
    import msvcrt
    PLATFORM = "windows"
except ImportError:
    import select
    PLATFORM = "linux"

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
        self.log_queue = collections.deque(maxlen=10)

    def emit(self, record):
        level_style_map = {
            logging.INFO: "info",
            logging.WARNING: "warning",
            logging.ERROR: "error",
            logging.CRITICAL: "bold red",
        }
        style = level_style_map.get(record.levelno, "default")
        # Prepend timestamp to the message
        message = f"{datetime.datetime.fromtimestamp(record.created).strftime('%H:%M:%S')} - {record.getMessage()}"
        self.log_queue.append(Text(message, style=style))

class GengoWatcher:
    CONFIG_FILE = "config.ini"
    PAUSE_FILE = "gengowatcher.pause"

    DEFAULT_CONFIG = {
        "Watcher": { "feed_url": "https://www.theguardian.com/uk/rss", "check_interval": 31, "min_reward": 0.0, "enable_notifications": True, "use_custom_user_agent": False, "enable_sound": True },
        "Paths": { "sound_file": "C:\\path\\to\\your\\sound.wav", "log_file": "logs/gengowatcher.log", "notification_icon_path": "", "browser_path": "", "browser_args": "--new-window {url}", "all_entries_log": "logs/all_entries.csv" },
        "Logging": { "log_max_bytes": 1000000, "log_backup_count": 3, "log_main_enabled": True, "log_all_entries_enabled": True },
        "Network": { "max_backoff": 300, "user_agent_email": "your_email@example.com" },
        "State": { "last_seen_link": "", "total_new_entries_found": 0 }
    }

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.config = {}
        self._config_parser = configparser.ConfigParser()
        self.shutdown_event = threading.Event()
        self.check_now_event = threading.Event()
        self.config_lock = threading.Lock()
        
        self.last_seen_link = None
        self.last_check_time = None
        self.next_check_time = time.time()
        self.total_new_entries_found = 0
        self.failure_count = 0
        self.current_action = "Initializing"
        
        self.start_time = time.time()
        self.session_new_entries = 0
        self.session_total_value = 0.0

        self._load_config()
        self.total_new_entries_found = int(self.config["State"].get("total_new_entries_found", 0))
        self.logger.info(f"GengoWatcher v{__version__} initialized.")

    def _create_default_config(self):
        parser = configparser.ConfigParser()
        for section, settings in self.DEFAULT_CONFIG.items():
            parser.add_section(section)
            for key, value in settings.items():
                parser.set(section, key, str(value))
        log_dir = Path(self.DEFAULT_CONFIG["Paths"]["log_file"]).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f: parser.write(f)
        print(f"\nCreated default 'config.ini'. Please edit it and restart.")
        sys.exit(0)

    def _load_config(self):
        if not Path(self.CONFIG_FILE).is_file(): self._create_default_config()
        self._config_parser.read(self.CONFIG_FILE, encoding='utf-8')
        with self.config_lock:
            try:
                for section, defaults in self.DEFAULT_CONFIG.items():
                    if not self._config_parser.has_section(section): self._config_parser.add_section(section)
                    self.config[section] = {}
                    for key, default_val in defaults.items():
                        if isinstance(default_val, bool): method = self._config_parser.getboolean
                        elif isinstance(default_val, int): method = self._config_parser.getint
                        elif isinstance(default_val, float): method = self._config_parser.getfloat
                        else: method = self._config_parser.get
                        self.config[section][key] = method(section, key, fallback=default_val)
                self.last_seen_link = self.config["State"].get("last_seen_link") or None
            except (configparser.Error, ValueError) as e:
                # Use standard print for startup errors before logging is fully configured
                print(f"CRITICAL: Error reading 'config.ini': {e}")
                sys.exit(1)

    def _save_config_and_state(self):
        with self.config_lock:
            self.config["State"]["total_new_entries_found"] = self.total_new_entries_found
            self.config["State"]["last_seen_link"] = self.last_seen_link if self.last_seen_link is not None else ""
            for section, settings in self.config.items():
                if not self._config_parser.has_section(section): self._config_parser.add_section(section)
                for key, value in settings.items():
                    self._config_parser.set(section, key, str(value))
            try:
                with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f: self._config_parser.write(f)
            except IOError as e: self.logger.error(f"Error saving config: {e}")

    def handle_exit(self, signum=None, frame=None):
        if not self.shutdown_event.is_set():
            self.logger.info("Shutdown initiated. Saving state...")
            self.shutdown_event.set()
            self._save_config_and_state()

    def play_sound(self):
        sound_file = Path(self.config["Paths"]["sound_file"])
        if sound_file.is_file(): winsound.PlaySound(str(sound_file), winsound.SND_FILENAME)
        else: winsound.MessageBeep()

    def open_in_browser(self, url):
        try:
            browser_path_str = self.config["Paths"].get("browser_path", "")
            if not browser_path_str or not Path(browser_path_str).is_file():
                webbrowser.open(url)
            else:
                args = [arg.format(url=url) for arg in self.config["Paths"]["browser_args"].split()]
                subprocess.Popen([str(browser_path_str)] + args)
        except Exception as e:
            self.logger.error(f"Browser Error: {e}")

    def show_notification(self, message, title="GengoWatcher", play_sound=False, open_link=False, url=None):
        if self.config["Watcher"]["enable_notifications"]:
            try:
                icon = Path(self.config["Paths"]["notification_icon_path"])
                icon_path = str(icon) if icon.is_file() else None
                notification.notify(title=title, message=message, app_name='GengoWatcher', app_icon=icon_path, timeout=8)
            except Exception as e:
                self.logger.error(f"Notify Error: {e}")
        if play_sound and self.config["Watcher"]["enable_sound"]:
            threading.Thread(target=self.play_sound, daemon=True).start()
        if open_link and url:
            self.open_in_browser(url)

    def _extract_reward(self, entry) -> float:
        text = entry.get("title", "") + " | " + entry.get("summary", "")
        match = re.search(r"Reward:\s*(?:US\$|\$)?\s*(\d+\.?\d*)", text, re.IGNORECASE)
        try:
            return float(match.group(1)) if match else 0.0
        except (ValueError, IndexError):
            return 0.0

    def _process_feed_entries(self, entries):
        if not entries: return
        new_entries = []
        for entry in entries:
            if entry.get("link") == self.last_seen_link: break
            new_entries.append(entry)
        if not new_entries: return

        min_reward = self.config["Watcher"]["min_reward"]
        processed_count = 0
        for entry in reversed(new_entries):
            reward = self._extract_reward(entry)
            if min_reward > 0.0 and reward < min_reward: continue
            
            processed_count += 1
            self.total_new_entries_found += 1
            self.session_new_entries += 1
            self.session_total_value += reward
            
            title = entry.get("title", "No Title")
            self.logger.info(f"New job: {title.split('|')[0].strip()} (US$ {reward:.2f})")
            self.show_notification(message=title, title="New Gengo Job Available!", play_sound=True, open_link=True, url=entry.get("link"))

        if processed_count > 0:
            self.last_seen_link = new_entries[0].get("link")
            self._save_config_and_state()

    def fetch_rss(self):
        headers = {}
        if self.config["Watcher"]["use_custom_user_agent"]:
            headers['User-Agent'] = f"GengoWatcher/{__version__} ({self.config['Network']['user_agent_email']})"
        try:
            feed = feedparser.parse(self.config["Watcher"]["feed_url"], request_headers=headers)
            if feed.bozo:
                self.logger.error(f"Feed Error: {feed.bozo_exception}")
                return None
            return feed
        except Exception as e:
            self.logger.error(f"RSS Error: {e}")
            return None

    def run(self):
        self.logger.info("Watcher thread started.")
        if not self.last_seen_link:
            self.current_action = "Priming feed"
            initial_feed = self.fetch_rss()
            if initial_feed and initial_feed.entries:
                self.last_seen_link = initial_feed.entries[0].get("link")
                self.logger.info("Initial feed primed successfully.")
                self._save_config_and_state()
        
        while not self.shutdown_event.is_set():
            if self.check_now_event.is_set() or time.time() >= self.next_check_time:
                self.check_now_event.clear()
                is_paused = os.path.exists(self.PAUSE_FILE)
                
                if is_paused:
                    self.current_action = "Paused"
                    wait_time = 5
                else:
                    self.current_action = "Fetching"
                    feed = self.fetch_rss()
                    if feed is None:
                        self.failure_count += 1
                        wait_time = min(self.config["Watcher"]["check_interval"] * self.failure_count, self.config["Network"]["max_backoff"])
                        self.current_action = f"Backoff ({int(wait_time)}s)"
                    else:
                        if self.failure_count > 0: self.logger.info("Connection re-established.")
                        self.failure_count = 0
                        self.last_check_time = datetime.datetime.now()
                        self.current_action = "Processing"
                        self._process_feed_entries(feed.entries)
                        wait_time = self.config["Watcher"]["check_interval"]
                        self.current_action = "Waiting"
                self.next_check_time = time.time() + wait_time
            time.sleep(0.1)

    def toggle_sound_enabled(self):
        with self.config_lock:
            self.config["Watcher"]["enable_sound"] = not self.config["Watcher"]["enable_sound"]
            self._save_config_and_state()
            return self.config["Watcher"]["enable_sound"]

    def toggle_notifications_enabled(self):
        with self.config_lock:
            self.config["Watcher"]["enable_notifications"] = not self.config["Watcher"]["enable_notifications"]
            self._save_config_and_state()
            return self.config["Watcher"]["enable_notifications"]

    def set_min_reward(self, amount: float):
        with self.config_lock:
            self.config["Watcher"]["min_reward"] = amount
            self._save_config_and_state()

    def run_notify_test(self):
        self.logger.info("Sending a test notification...")
        self.show_notification(message="This is a test notification!", title="GengoWatcher Test", play_sound=True, open_link=True, url="https://gengo.com/t/jobs/status/available")

    def restart(self):
        self.handle_exit()
        python = sys.executable
        os.execv(python, [python] + sys.argv)


class CommandLineInterface:
    def __init__(self, watcher: GengoWatcher, console: Console, log_queue: collections.deque):
        self.watcher = watcher
        self.console = console
        self.log_queue = log_queue
        self.input_buffer = ""
        self.command_output = collections.deque(maxlen=20)
        
        self.commands = {
            "check": {"handler": self._handle_check, "help": "Trigger an immediate RSS feed check."},
            "help": {"handler": self.print_help, "help": "Display this list of commands."},
            "exit": {"handler": self._handle_exit, "aliases": ["q", "quit"], "help": "Save state and quit the application."},
            "pause": {"handler": self._handle_pause, "aliases": ["p"], "help": "Pause RSS feed checks."},
            "resume": {"handler": self._handle_resume, "aliases": ["r"], "help": "Resume RSS feed checks."},
            "togglesound": {"handler": self._handle_toggle_sound, "aliases": ["ts"], "help": "Toggle sound alerts on/off."},
            "togglenotifications": {"handler": self._handle_toggle_notifications, "aliases": ["tn"], "help": "Toggle desktop notifications on/off."},
            "setminreward": {"handler": self._handle_set_min_reward, "aliases": ["smr"], "help": "Set min reward (e.g., `smr 5.50`)."},
            "reloadconfig": {"handler": self._handle_reload_config, "aliases": ["rl"], "help": "Reload all settings from config.ini."},
            "restart": {"handler": self.watcher.restart, "aliases": [], "help": "Restart the entire script."},
            "notifytest": {"handler": self.watcher.run_notify_test, "aliases": ["nt"], "help": "Send a test notification."},
            "clear": {"handler": self._handle_clear, "help": "Clear the command output panel."},
        }
        self.alias_map = {alias: cmd for cmd, details in self.commands.items() for alias in [cmd] + details.get("aliases", [])}
        signal.signal(signal.SIGINT, self._handle_exit)

        # Build the static layout structure ONCE.
        self.layout = self._build_layout()

    def _build_layout(self) -> Layout:
        """Builds the main layout structure. This is done only once."""
        layout = Layout(name="root")
        layout.split(
            Layout(self._get_header_panel(), name="header", size=8),
            Layout(ratio=1, name="main"),
            Layout(size=3, name="footer"),
            Layout(size=1, name="input"),
        )
        layout["main"].split_row(
            Layout(name="left", minimum_size=50),
            Layout(name="right")
        )
        # Create named, empty layouts that will be updated in the run loop
        layout["left"].split(
            Layout(name="runtime_status"),
            Layout(name="recent_activity")
        )
        layout["right"].update(Layout(name="output"))
        return layout

    def _get_header_panel(self) -> Panel:
        """Creates the static header panel."""
        config_table = Table.grid(expand=True, padding=(0, 1))
        config_table.add_column(style="label", justify="right", width=24)
        config_table.add_column(style="value", justify="left")
        
        config_table.add_row("Feed URL:", f"[path]{self.watcher.config['Watcher']['feed_url']}[/]")
        config_table.add_row("Check Interval:", f" {self.watcher.config['Watcher']['check_interval']} seconds")
        config_table.add_row() # Spacer
        config_table.add_row("Minimum Reward:", f"[success]US$ {self.watcher.config['Watcher']['min_reward']:.2f}[/]")
        config_table.add_row("Desktop Notifications:", Text("Enabled", style="success") if self.watcher.config['Watcher']['enable_notifications'] else Text("Disabled", style="error"))
        config_table.add_row("Sound Alerts:", Text("Enabled", style="success") if self.watcher.config['Watcher']['enable_sound'] else Text("Disabled", style="error"))
        
        return Panel(config_table, title=f"[title]Welcome to GengoWatcher[/]", subtitle=f"v{__version__}", subtitle_align="center", border_style="panel_border")

    def run(self):
        """Runs the main, flicker-free live display loop."""
        with Live(self.layout, console=self.console, screen=True, auto_refresh=False, vertical_overflow="visible") as live:
            while not self.watcher.shutdown_event.is_set():
                # Update the dynamic parts of the layout
                self.layout["runtime_status"].update(self._get_runtime_status_panel())
                self.layout["recent_activity"].update(self._get_recent_activity_panel())
                self.layout["right"].update(self._get_output_panel())
                self.layout["footer"].update(self._get_status_bar())
                self.layout["input"].update(Text(f"> {self.input_buffer}", no_wrap=True))
                
                live.refresh()
                
                if PLATFORM == "windows":
                    start_time = time.time()
                    while time.time() - start_time < 0.2:
                        if msvcrt.kbhit():
                            char = msvcrt.getch()
                            if char == b'\r':
                                self.handle_command(self.input_buffer)
                                self.input_buffer = ""
                            elif char == b'\x08': # Backspace
                                self.input_buffer = self.input_buffer[:-1]
                            else:
                                try: self.input_buffer += char.decode()
                                except UnicodeDecodeError: pass
                        time.sleep(0.01)

    def _get_runtime_status_panel(self) -> Panel:
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style="label", justify="right", width=18)
        table.add_column(style="value", justify="left")
        uptime_seconds = time.time() - self.watcher.start_time
        table.add_row("Uptime:", f" {str(datetime.timedelta(seconds=int(uptime_seconds)))}")
        last_check_str = self.watcher.last_check_time.strftime('%Y-%m-%d %H:%M:%S') if self.watcher.last_check_time else "Never"
        table.add_row("Last Check:", f" {last_check_str}")
        failures = self.watcher.failure_count
        table.add_row("Feed Failures:", Text(f" {failures}", style="warning" if failures > 0 else "default"))
        table.add_row()
        table.add_row("Jobs (Session):", f" {self.watcher.session_new_entries}")
        table.add_row("Value (Session):", f" US$ {self.watcher.session_total_value:.2f}")
        return Panel(table, title="[title]Runtime Status[/]", title_align="center")

    def _get_recent_activity_panel(self) -> Panel:
        return Panel(Group(*self.log_queue), title="[title]Recent Activity[/]", title_align="center")

    def _get_output_panel(self) -> Panel:
        return Panel(Group(*self.command_output), title="[title]Output[/]", title_align="center")

    def _get_status_bar(self) -> Panel:
        status, color = ("Running", "success")
        if self.watcher.shutdown_event.is_set(): status, color = ("Stopped", "error")
        elif os.path.exists(self.watcher.PAUSE_FILE): status, color = ("Paused", "error")
        
        remaining = self.watcher.next_check_time - time.time()
        rem_str = f"{int(max(0,remaining))}s"
        action = self.watcher.current_action
        if status == "Running" and action == "Waiting": action = f"Next check in {rem_str}"
        elif status == "Paused": action = f"Paused"
        
        return Panel(Text.assemble(
            ("Status: ", "default"), (status, color), (" | ", "dim"),
            ("Action: ", "default"), (action, "cyan"), (" | ", "dim"),
            ("Found (Total): ", "default"), (str(self.watcher.total_new_entries_found), "green")
        ), border_style="dim")

    def handle_command(self, command_str):
        parts = command_str.strip().lower().split()
        if not parts: return
        cmd_alias, args = parts[0], parts[1:]
        command = self.alias_map.get(cmd_alias)
        if not command:
            self.watcher.logger.error(f"Unknown command: '{command_str}'")
            return
        
        handler = self.commands[command]["handler"]
        try:
            sig = inspect.signature(handler)
            if 'args' in sig.parameters: output = handler(args)
            else: output = handler()
            if output:
                self.command_output.clear()
                self.command_output.append(output)
        except Exception as e:
            self.watcher.logger.error(f"Error executing '{command}': {e}")

    def print_help(self):
        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column(style="label", width=22)
        table.add_column(style="value")
        for cmd, info in self.commands.items():
            aliases = ", ".join(info.get("aliases", []))
            table.add_row(f"[header]{cmd}[/] ({aliases})", info["help"])
        return Panel(table, title="[title]Commands[/]", border_style="panel_border")

    def _handle_exit(self, *args): self.watcher.handle_exit()
    def _handle_check(self, args=None): self.watcher.check_now_event.set(); self.watcher.logger.info("Manual check triggered.")
    def _handle_clear(self, args=None): self.command_output.clear(); self.watcher.logger.info("Command output cleared.")
        
    def _handle_pause(self, args=None):
        if not os.path.exists(self.watcher.PAUSE_FILE):
            with open(self.watcher.PAUSE_FILE, "w") as f: f.write("Paused.")
            self.watcher.logger.warning("Watcher paused.")
        else: self.watcher.logger.warning("Watcher is already paused.")
    
    def _handle_resume(self, args=None):
        if os.path.exists(self.watcher.PAUSE_FILE):
            os.remove(self.watcher.PAUSE_FILE)
            self.watcher.logger.info("Watcher resumed.")
        else: self.watcher.logger.warning("Watcher is not paused.")
    
    def _handle_toggle_sound(self, args=None):
        new_state = self.watcher.toggle_sound_enabled()
        self.watcher.logger.info(f"Sound alerts {'enabled' if new_state else 'disabled'}.")
    
    def _handle_toggle_notifications(self, args=None):
        new_state = self.watcher.toggle_notifications_enabled()
        self.watcher.logger.info(f"Desktop notifications {'enabled' if new_state else 'disabled'}.")

    def _handle_set_min_reward(self, args):
        if not args:
            self.watcher.logger.error("Usage: setminreward <amount>")
            return
        try:
            amount = float(args[0])
            self.watcher.set_min_reward(amount)
            self.watcher.logger.info(f"Minimum reward set to US$ {amount:.2f}")
        except ValueError:
            self.watcher.logger.error("Invalid amount. Please enter a number.")

    def _handle_reload_config(self, args=None):
        self.watcher._load_config()
        self.watcher.logger.info("Configuration reloaded from config.ini.")


if __name__ == "__main__":
    console = Console(theme=APP_THEME)

    log = logging.getLogger("gengowatcher")
    log.setLevel(logging.INFO)
    
    ui_handler = UILoggingHandler()
    log.addHandler(ui_handler)
    
    watcher = GengoWatcher(logger=log)

    if watcher.config["Logging"]["log_main_enabled"]:
        log_file = Path(watcher.config["Paths"]["log_file"])
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=watcher.config["Logging"]["log_max_bytes"], 
            backupCount=watcher.config["Logging"]["log_backup_count"]
        )
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        log.addHandler(file_handler)

    cli = CommandLineInterface(watcher, console, log_queue=ui_handler.log_queue)
    
    watcher_thread = threading.Thread(target=watcher.run, daemon=True, name="WatcherThread")
    watcher_thread.start()
    
    try:
        cli.run()
    finally:
        # Ensure shutdown is clean even if UI loop crashes
        if not watcher.shutdown_event.is_set():
            watcher.shutdown_event.set()
        watcher_thread.join(timeout=2)
        # The 'screen' mode will automatically restore the console
        console.print("GengoWatcher has shut down.")