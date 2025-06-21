import time
import collections
import datetime
import os
import signal
import inspect

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout

from watcher import GengoWatcher, __version__
from config import AppConfig
from state import AppState

try:
    import msvcrt
    PLATFORM = "windows"
except ImportError:
    import sys
    import select
    import tty
    import termios
    PLATFORM = "linux"


class CommandLineInterface:
    def __init__(self, watcher: GengoWatcher, config: AppConfig, state: AppState, console: Console, log_queue: collections.deque):
        self.watcher = watcher
        self.config = config
        self.state = state
        self.console = console
        self.log_queue = log_queue
        self.input_buffer = ""
        self.command_output = collections.deque(maxlen=20)
        self._init_commands()
        signal.signal(signal.SIGINT, self._handle_exit)
        self.layout = self._build_layout()

    def _init_commands(self):
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

    def _build_layout(self) -> Layout:
        layout = Layout(name="root")
        layout.split(
            Layout(name="header", size=8),
            Layout(ratio=1, name="main"),
            Layout(size=3, name="footer"),
            Layout(size=1, name="input"),
        )
        layout["main"].split_row(
            Layout(name="left", ratio=3),
            Layout(name="right", ratio=2)
        )
        layout["left"].split(
            Layout(name="runtime_status"),
            Layout(name="recent_activity")
        )
        layout["right"].update(Layout(name="output"))
        return layout

    def _get_header_panel(self) -> Panel:
        config_table = Table.grid(expand=True, padding=(0, 1))
        config_table.add_column(style="label", justify="right", width=24)
        config_table.add_column(style="value", justify="left")
        config_table.add_row("Feed URL:", f"[path]{self.config.get('Watcher', 'feed_url')}[/]")
        config_table.add_row("Check Interval:", f" {self.config.get('Watcher', 'check_interval')} seconds")
        config_table.add_row()
        config_table.add_row("Minimum Reward:", f"[success]US$ {self.config.get('Watcher', 'min_reward'):.2f}[/]")
        notif_enabled = self.config.get('Watcher', 'enable_notifications')
        sound_enabled = self.config.get('Watcher', 'enable_sound')
        config_table.add_row("Desktop Notifications:", Text("Enabled", style="success") if notif_enabled else Text("Disabled", style="error"))
        config_table.add_row("Sound Alerts:", Text("Enabled", style="success") if sound_enabled else Text("Disabled", style="error"))
        return Panel(config_table, title=f"[title]Welcome to GengoWatcher[/]", subtitle=f"v{__version__}", subtitle_align="center", border_style="panel_border")

    def run(self):
        if PLATFORM == "linux":
            old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        with Live(self.layout, console=self.console, screen=True, auto_refresh=False, vertical_overflow="visible") as live:
            while not self.watcher.shutdown_event.is_set():
                self.layout["header"].update(self._get_header_panel())
                self.layout["runtime_status"].update(self._get_runtime_status_panel())
                self.layout["recent_activity"].update(self._get_recent_activity_panel())
                self.layout["right"].update(self._get_output_panel())
                self.layout["footer"].update(self._get_status_bar())
                self.layout["input"].update(Text(f"> {self.input_buffer}", no_wrap=True))
                live.refresh()
                if PLATFORM == "windows":
                    if msvcrt.kbhit():
                        char = msvcrt.getch()
                        self._process_char(char)
                    else:
                        time.sleep(0.5)
                else:
                    if select.select([sys.stdin], [], [], 0.5)[0]:
                        char = sys.stdin.read(1)
                        self._process_char(char)
        if PLATFORM == "linux":
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    def _process_char(self, char):
        if isinstance(char, bytes):
            if char == b'\r':
                char = '\n'
            elif char == b'\x08':
                char = 'backspace'
            else:
                try:
                    char = char.decode()
                except UnicodeDecodeError:
                    char = ''
        if char == '\n':
            self.handle_command(self.input_buffer)
            self.input_buffer = ""
        elif char in ('\x7f', 'backspace', '\b'):
            self.input_buffer = self.input_buffer[:-1]
        elif char.isprintable():
            self.input_buffer += char

    def _get_runtime_status_panel(self) -> Panel:
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style="label", justify="right", width=15)
        table.add_column(style="value", justify="left", width=11)
        table.add_column(style="label", justify="right", width=15)
        table.add_column(style="value", justify="left", width=11)
        uptime_seconds = time.time() - self.watcher.start_time
        uptime_hours = uptime_seconds / 3600.0
        jobs_per_hour = (self.watcher.session_new_entries / uptime_hours) if uptime_hours > 0 else 0.0
        avg_reward = (
            self.watcher.session_total_value / self.watcher.session_new_entries
        ) if self.watcher.session_new_entries > 0 else 0.0
        if os.path.exists(self.watcher.PAUSE_FILE):
            next_check_text = Text("Paused", "warning")
        elif self.watcher.shutdown_event.is_set():
            next_check_text = Text("N/A", "dim")
        else:
            seconds_remaining = max(0, self.watcher.next_check_time - time.time())
            next_check_text = Text(f"{int(seconds_remaining)}s", "cyan")
        table.add_row(
            "Uptime:", f" {str(datetime.timedelta(seconds=int(uptime_seconds)))}",
            "Jobs/Hour:", f" {jobs_per_hour:.1f}"
        )
        table.add_row(
            "Jobs (Session):", f" {self.watcher.session_new_entries}",
            "Found (Total):", f" {self.state.total_new_entries_found}"
        )
        table.add_row(
            "Value (Session):", f" US$ {self.watcher.session_total_value:.2f}",
            "Avg. Reward:", f"US$ {avg_reward:.2f}"
        )
        failures = self.watcher.failure_count
        failures_text = Text(f" {failures}", style="warning" if failures > 0 else "success")
        table.add_row(
            "Next Check In:", next_check_text,
            "Feed Failures:", failures_text
        )
        return Panel(table, title="[title]Runtime Status[/]", title_align="center")

    def _get_recent_activity_panel(self) -> Panel:
        return Panel(Group(*self.log_queue), title="[title]Recent Activity[/]", title_align="center")

    def _get_output_panel(self) -> Panel:
        return Panel(Group(*self.command_output), title="[title]Output[/]", title_align="center")

    def _get_status_bar(self) -> Panel:
        status, color = ("Running", "success")
        if self.watcher.shutdown_event.is_set():
            status, color = ("Stopped", "error")
        elif os.path.exists(self.watcher.PAUSE_FILE):
            status, color = ("Paused", "warning")
        action = self.watcher.current_action
        return Panel(
            Text.assemble(
                ("Status: ", "default"), (status, color), (" | ", "dim"),
                ("Action: ", "default"), (action, "cyan"), (" | ", "dim"),
                ("Found (Total): ", "default"), (str(self.state.total_new_entries_found), "green")
            ),
            border_style="dim"
        )

    def handle_command(self, command_str):
        parts = command_str.strip().lower().split()
        if not parts:
            return
        cmd_alias, args = parts[0], parts[1:]
        command = self.alias_map.get(cmd_alias)
        if not command:
            self.watcher.logger.error(f"Unknown command: '{command_str}'")
            return
        handler = self.commands[command]["handler"]
        try:
            sig = inspect.signature(handler)
            if 'args' in sig.parameters:
                output = handler(args)
            else:
                output = handler()
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

    def _handle_exit(self, *args):
        self.watcher.handle_exit()

    def _handle_check(self, args=None):
        self.watcher.check_now_event.set()
        self.watcher.logger.info("Manual check triggered.")

    def _handle_clear(self, args=None):
        self.command_output.clear()
        self.watcher.logger.info("Command output cleared.")

    def _handle_pause(self, args=None):
        if not os.path.exists(self.watcher.PAUSE_FILE):
            with open(self.watcher.PAUSE_FILE, "w") as f:
                f.write("Paused.")
            self.watcher.logger.warning("Watcher paused.")
        else:
            self.watcher.logger.warning("Watcher is already paused.")

    def _handle_resume(self, args=None):
        if os.path.exists(self.watcher.PAUSE_FILE):
            os.remove(self.watcher.PAUSE_FILE)
            self.watcher.logger.info("Watcher resumed.")
        else:
            self.watcher.logger.warning("Watcher is not paused.")

    def _handle_toggle_sound(self, args=None):
        current_state = self.config.get("Watcher", "enable_sound")
        self.config.set("Watcher", "enable_sound", not current_state)
        self.config.save_config()
        self.watcher.logger.info(f"Sound alerts {'enabled' if not current_state else 'disabled'}.")

    def _handle_toggle_notifications(self, args=None):
        current_state = self.config.get("Watcher", "enable_notifications")
        self.config.set("Watcher", "enable_notifications", not current_state)
        self.config.save_config()
        self.watcher.logger.info(f"Desktop notifications {'enabled' if not current_state else 'disabled'}.")

    def _handle_set_min_reward(self, args):
        if not args:
            self.watcher.logger.error("Usage: setminreward <amount>")
            return
        try:
            amount = float(args[0])
            self.config.set("Watcher", "min_reward", amount)
            self.config.save_config()
            self.watcher.logger.info(f"Minimum reward set to US$ {amount:.2f}")
        except ValueError:
            self.watcher.logger.error("Invalid amount. Please enter a number.")

    def _handle_reload_config(self, args=None):
        self.config.load_config()
        self.watcher.logger.info("Configuration reloaded from config.ini.")
