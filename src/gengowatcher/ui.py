import time
import collections
import datetime
import os
import signal
import inspect
import sys
import threading

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout

from .watcher import GengoWatcher, __version__
from .config import AppConfig
from .state import AppState

if sys.platform == "win32":
    import msvcrt
else:
    import select
    import tty
    import termios


class CommandLineInterface:
    def __init__(
        self,
        watcher: GengoWatcher,
        config: AppConfig,
        state: AppState,
        console: Console,
        log_queue: collections.deque,
    ):
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
        self.exit_event = threading.Event()

    def _init_commands(self):
        self.commands = {
            "check": {
                "handler": self._handle_check,
                "help": "Trigger an immediate RSS feed check.",
            },
            "help": {
                "handler": self.print_help,
                "help": "Display this list of commands.",
            },
            "exit": {
                "handler": self._handle_exit,
                "aliases": ["q", "quit"],
                "help": "Save state and quit the application.",
            },
            "pause": {
                "handler": self._handle_pause,
                "aliases": ["p"],
                "help": "Pause RSS feed checks.",
            },
            "resume": {
                "handler": self._handle_resume,
                "aliases": ["r"],
                "help": "Resume RSS feed checks.",
            },
            "togglesound": {
                "handler": self._handle_toggle_sound,
                "aliases": ["ts"],
                "help": "Toggle sound alerts on/off.",
            },
            "togglenotifications": {
                "handler": self._handle_toggle_notifications,
                "aliases": ["tn"],
                "help": "Toggle desktop notifications on/off.",
            },
            "togglewebsocket": {
                "handler": self._handle_toggle_websocket,
                "aliases": ["tw"],
                "help": "Toggle WebSocket monitoring (requires restart).",
            },
            "autoaccept": {
                "handler": self._handle_autoaccept,
                "aliases": ["aa"],
                "help": "Toggle auto-accept on/off.",
            },
            "captchatoggle": {
                "handler": self._handle_captchatoggle,
                "aliases": ["ct"],
                "help": "Toggle CAPTCHA solving on/off.",
            },
            "setminreward": {
                "handler": self._handle_set_min_reward,
                "aliases": ["smr"],
                "help": "Set min reward (e.g., `smr 5.50`).",
            },
            "reloadconfig": {
                "handler": self._handle_reload_config,
                "aliases": ["rl"],
                "help": "Reload all settings from config.ini.",
            },
            "restart": {
                "handler": self.watcher.restart,
                "aliases": [],
                "help": "Restart the entire script.",
            },
            "notifytest": {
                "handler": self.watcher.run_notify_test,
                "aliases": ["nt"],
                "help": "Send a test notification.",
            },
            "clear": {
                "handler": self._handle_clear,
                "help": "Clear the command output panel.",
            },
            "wstest": {
                "handler": self._handle_websocket_test,
                "aliases": ["wt"],
                "help": "Test WebSocket. Use 'wt' for PING, 'wt notify' for a test notification.",
            },
            "captchasetup": {
                "handler": self._handle_captcha_setup,
                "help": "Configure CAPTCHA solver service.",
            },
            "captchatest": {
                "handler": self._handle_captcha_test,
                "help": "Test CAPTCHA solver configuration.",
            },
            "captchastats": {
                "handler": self._handle_captcha_stats,
                "help": "Show CAPTCHA solver statistics.",
            },
            "captchareset": {
                "handler": self._handle_captcha_reset,
                "help": "Reset CAPTCHA configuration.",
            },
            "acceptstats": {
                "handler": self._handle_accept_stats,
                "help": "Display job acceptance statistics.",
            },
        }
        self.alias_map = {
            alias: cmd
            for cmd, details in self.commands.items()
            for alias in [cmd] + details.get("aliases", [])
        }

    def _build_layout(self) -> Layout:
        layout = Layout(name="root")
        layout.split(
            Layout(name="header", size=8),
            Layout(ratio=1, name="main"),
            Layout(size=3, name="footer"),
            Layout(size=1, name="input"),
        )
        layout["main"].split_row(
            Layout(name="left", ratio=3), Layout(name="right", ratio=2)
        )
        layout["left"].split(
            Layout(name="runtime_status"), Layout(name="recent_activity")
        )
        layout["right"].update(Layout(name="output"))
        return layout

    def _get_header_panel(self) -> Panel:
        config_table = Table.grid(expand=True, padding=(0, 1))
        config_table.add_column(style="label", justify="right", width=24)
        config_table.add_column(style="value", justify="left")
        config_table.add_row(
            "Feed URL:", f"[path]{self.config.get('Watcher', 'feed_url')}[/]"
        )
        config_table.add_row(
            "Check Interval:",
            f" {self.config.get('Watcher', 'check_interval')} seconds",
        )
        config_table.add_row()
        config_table.add_row(
            "Minimum Reward:",
            f"[success]US$ {self.config.get('Watcher', 'min_reward'):.2f}[/]",
        )
        notif_enabled = self.config.get("Watcher", "enable_notifications")
        sound_enabled = self.config.get("Watcher", "enable_sound")
        config_table.add_row(
            "Desktop Notifications:",
            (
                Text("Enabled", style="success")
                if notif_enabled
                else Text("Disabled", style="error")
            ),
        )
        config_table.add_row(
            "Sound Alerts:",
            (
                Text("Enabled", style="success")
                if sound_enabled
                else Text("Disabled", style="error")
            ),
        )
        return Panel(
            config_table,
            title=f"[title]Welcome to GengoWatcher[/]",
            subtitle=f"v{__version__}",
            subtitle_align="center",
            border_style="panel_border",
        )

    def run(self):
        """The main loop for the command-line interface."""
        if sys.platform != "win32":
            old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())

        with Live(
            self.layout,
            console=self.console,
            screen=True,
            auto_refresh=False,
            vertical_overflow="visible",
        ) as live:
            while not (self.exit_event.is_set() or self.watcher.shutdown_event.is_set()):
                self.layout["header"].update(self._get_header_panel())
                self.layout["runtime_status"].update(self._get_runtime_status_panel())
                self.layout["recent_activity"].update(self._get_recent_activity_panel())
                self.layout["right"].update(self._get_output_panel())
                self.layout["footer"].update(self._get_status_bar())
                self.layout["input"].update(
                    Text(f"> {self.input_buffer}", no_wrap=True)
                )
                live.refresh()

                try:
                    if sys.platform == "win32":
                        if msvcrt.kbhit():
                            self._process_char(msvcrt.getch())
                        time.sleep(0.1)
                    else:
                        rlist, _, _ = select.select([sys.stdin], [], [], 0.5)
                        if rlist:
                            self._process_char(sys.stdin.read(1))
                except (OSError, IOError):
                    time.sleep(0.5)

        if sys.platform != "win32":
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    def _process_char(self, char):
        if isinstance(char, bytes):
            if char == b"\r":
                char = "\n"
            elif char == b"\x08":
                char = "backspace"
            elif char == b"\x04":
                char = "\x04"
            else:
                try:
                    char = char.decode()
                except UnicodeDecodeError:
                    char = ""
        if char in ("", "\x04"):
            self._handle_exit()
            return
        if char == "\n":
            self.handle_command(self.input_buffer)
            self.input_buffer = ""
        elif char in ("\x7f", "backspace", "\b"):
            self.input_buffer = self.input_buffer[:-1]
        elif char.isprintable():
            self.input_buffer += char

    def _get_runtime_status_panel(self) -> Panel:
        """
        Builds a Rich Panel showing runtime metrics and service statuses.
        
        The panel contains a grid of runtime information including uptime, jobs per hour,
        session and total job counts, session value and average reward, WebSocket status
        (with inline heartbeat details when live: latency, last pong age, next ping),
        RSS fallback/status with remaining seconds or paused state, Auto-Accept status,
        and CAPTCHA solver status.
        
        Returns:
            Panel: A Rich Panel containing the assembled runtime status table.
        """
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style="label", justify="right", width=16)
        table.add_column(style="value", justify="left", width=14)
        table.add_column(style="label", justify="right", width=14)
        table.add_column(style="value", justify="left")

        uptime_seconds = time.time() - self.watcher.start_time
        uptime_hours = uptime_seconds / 3600.0
        jobs_per_hour = (
            (self.watcher.session_new_entries / uptime_hours)
            if uptime_hours > 0
            else 0.0
        )
        avg_reward = (
            (self.watcher.session_total_value / self.watcher.session_new_entries)
            if self.watcher.session_new_entries > 0
            else 0.0
        )

        ws_status, ws_color = {
            "Live": ("Live", "success"),
            "Connecting": ("Connecting", "yellow"),
            "Authenticating": ("Authenticating", "yellow"),
            "Offline": ("Offline", "warning"),
            "Disabled": ("Disabled", "dim"),
            "Stopped": ("Stopped", "error"),
        }.get(self.watcher.websocket_status, (self.watcher.websocket_status, "error"))

        seconds_remaining = max(0, self.watcher.next_check_time - time.time())
        rss_status_text = f"{self.watcher.rss_action} ({int(seconds_remaining)}s)"
        if "Backoff" in self.watcher.rss_action:
            rss_color = "warning"
        elif "Paused" in self.watcher.rss_action:
            rss_color = "warning"
        else:
            rss_color = "cyan"
        if os.path.exists(self.watcher.PAUSE_FILE):
            rss_status_text = "Paused"

        table.add_row(
            "Uptime:",
            f"{str(datetime.timedelta(seconds=int(uptime_seconds)))}",
            "Jobs/Hour:",
            f"{jobs_per_hour:.1f}",
        )
        table.add_row(
            "Jobs (Session):",
            f"{self.watcher.session_new_entries}",
            "Found (Total):",
            f"{self.state.total_new_entries_found}",
        )
        table.add_row(
            "Value (Session):",
            f"US$ {self.watcher.session_total_value:.2f}",
            "Avg. Reward:",
            f"US$ {avg_reward:.2f}",
        )
        table.add_row()

        # Auto-accept status
        autoaccept_enabled = self.config.getboolean("AutoAccept", "enabled")
        autoaccept_status = "Enabled" if autoaccept_enabled else "Disabled"
        autoaccept_color = "success" if autoaccept_enabled else "dim"

        # WebSocket status + heartbeat in a single row
        value_text = Text()
        value_text.append(ws_status, style=ws_color)
        if ws_status == "Live":
            now = time.time()
            last_pong_age = None
            next_ping_in = None
            latency = None
            try:
                if getattr(self.watcher, "websocket_last_pong_ts", None):
                    last_pong_age = max(0, int(now - self.watcher.websocket_last_pong_ts))
                if getattr(self.watcher, "websocket_next_ping_ts", None):
                    next_ping_in = max(0, int(self.watcher.websocket_next_ping_ts - now))
                if getattr(self.watcher, "websocket_ping_latency_ms", None) is not None:
                    latency = int(self.watcher.websocket_ping_latency_ms)
            except Exception:
                pass
            parts = []
            if latency is not None:
                parts.append(f"{latency}ms")
            if last_pong_age is not None:
                parts.append(f"last {last_pong_age}s")
            if next_ping_in is not None:
                parts.append(f"next {next_ping_in}s")
            if parts:
                value_text.append("  ")
                value_text.append(" | ".join(parts), style="cyan")

        table.add_row("WebSocket:", value_text)
        table.add_row("RSS Fallback:", Text(rss_status_text, style=rss_color))
        table.add_row("Auto-Accept:", Text(autoaccept_status, style=autoaccept_color))

        # CAPTCHA solving status
        captcha_enabled = self.config.getboolean("Captcha", "enabled")
        captcha_status = "Enabled" if captcha_enabled else "Disabled"
        captcha_color = "success" if captcha_enabled else "dim"

        table.add_row("CAPTCHA Solver:", Text(captcha_status, style=captcha_color))

        return Panel(table, title="[title]Runtime Status[/]", title_align="center")

    def _get_recent_activity_panel(self) -> Panel:
        return Panel(
            Group(*self.log_queue),
            title="[title]Recent Activity[/]",
            title_align="center",
        )

    def _get_output_panel(self) -> Panel:
        return Panel(
            Group(*self.command_output), title="[title]Output[/]", title_align="center"
        )

    def _get_status_bar(self) -> Panel:
        status, color = ("Running", "success")
        if self.watcher.shutdown_event.is_set():
            status, color = ("Stopped", "error")
        elif os.path.exists(self.watcher.PAUSE_FILE):
            status, color = ("Paused", "warning")

        ws_status_text, ws_status_color = {
            "Live": ("Live", "success"),
            "Connecting": ("Connecting", "yellow"),
            "Authenticating": ("Authenticating", "yellow"),
            "Offline": ("Offline", "warning"),
            "Disabled": ("Disabled", "dim"),
            "Stopped": ("Stopped", "error"),
        }.get(self.watcher.websocket_status, (self.watcher.websocket_status, "error"))

        return Panel(
            Text.assemble(
                ("Status: ", "default"),
                (status, color),
                (" | ", "dim"),
                ("WebSocket: ", "default"),
                (ws_status_text, ws_status_color),
                (" | ", "dim"),
                ("RSS: ", "default"),
                (self.watcher.rss_action, "cyan"),
                (" | ", "dim"),
                ("Found (Total): ", "default"),
                (str(self.state.total_new_entries_found), "green"),
            ),
            border_style="dim",
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
            if "args" in sig.parameters:
                output = handler(args)
            else:
                output = handler()
            if output:
                self.command_output.clear()
                self.command_output.append(output)
        except Exception as e:
            self.watcher.logger.exception(f"Error executing '{command}': {e}")

    def print_help(self):
        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column(style="label", width=22)
        table.add_column(style="value")
        for cmd, info in self.commands.items():
            aliases = ", ".join(info.get("aliases", []))
            table.add_row(f"[header]{cmd}[/] ({aliases})" if aliases else f"[header]{cmd}[/]", info["help"])
        return Panel(table, title="[title]Commands[/]", border_style="panel_border")

    def _handle_exit(self, *args):
        self.watcher.handle_exit()
        self.exit_event.set()

    def _handle_check(self, args=None):
        _ = args
        self.watcher.check_now_event.set()
        self.watcher.logger.info("Manual check triggered.")

    def _handle_clear(self, args=None):
        _ = args
        self.command_output.clear()
        self.watcher.logger.info("Command output cleared.")

    def _handle_pause(self, args=None):
        _ = args
        if not os.path.exists(self.watcher.PAUSE_FILE):
            with open(self.watcher.PAUSE_FILE, "w") as f:
                f.write("Paused.")
            self.watcher.logger.warning("Watcher paused.")
        else:
            self.watcher.logger.warning("Watcher is already paused.")

    def _handle_resume(self, args=None):
        _ = args
        if os.path.exists(self.watcher.PAUSE_FILE):
            os.remove(self.watcher.PAUSE_FILE)
            self.watcher.logger.info("Watcher resumed.")
        else:
            self.watcher.logger.warning("Watcher is not paused.")

    def _handle_toggle_sound(self, args=None):
        _ = args
        current_state = self.config.get("Watcher", "enable_sound")
        self.config.set("Watcher", "enable_sound", not current_state)
        self.config.save_config()
        self.watcher.logger.info(
            f"Sound alerts {'enabled' if not current_state else 'disabled'}."
        )

    def _handle_toggle_notifications(self, args=None):
        _ = args
        current_state = self.config.get("Watcher", "enable_notifications")
        self.config.set("Watcher", "enable_notifications", not current_state)
        self.config.save_config()
        self.watcher.logger.info(
            f"Desktop notifications {'enabled' if not current_state else 'disabled'}."
        )

    def _handle_toggle_websocket(self, args=None):
        _ = args
        current_state = self.config.get("WebSocket", "enable_websocket")
        self.config.set("WebSocket", "enable_websocket", not current_state)
        self.config.save_config()
        new_state_text = "enabled" if not current_state else "disabled"
        self.watcher.logger.info(f"WebSocket monitoring has been {new_state_text}.")
        self.watcher.logger.warning(
            "A restart is required for this change to take effect."
        )

    def _handle_autoaccept(self, args=None):
        _ = args
        current_state = self.config.getboolean("AutoAccept", "enabled")
        self.config.set("AutoAccept", "enabled", not current_state)
        self.config.save_config()
        new_state_text = "enabled" if not current_state else "disabled"
        self.watcher.logger.info(f"Auto-accept has been {new_state_text}.")

        # Update the job acceptance engine if it exists
        if hasattr(self.watcher, 'job_acceptance_engine'):
            self.watcher.job_acceptance_engine.enabled = not current_state
            self.watcher.logger.info(f"Job acceptance engine updated.")

    def _handle_captchatoggle(self, args=None):
        _ = args
        current_state = self.config.getboolean("Captcha", "enabled")
        self.config.set("Captcha", "enabled", not current_state)
        self.config.save_config()
        new_state_text = "enabled" if not current_state else "disabled"
        self.watcher.logger.info(f"CAPTCHA solving has been {new_state_text}.")

        # Update the CAPTCHA solver if it exists
        if hasattr(self.watcher, 'captcha_solver'):
            try:
                self.watcher.captcha_solver.reinitialize()
                status_text = (
                    "enabled"
                    if self.watcher.captcha_solver.is_configured()
                    else "disabled"
                )
                self.watcher.logger.info(
                    "CAPTCHA solver reinitialised and is currently %s.", status_text
                )
            except Exception as error:
                self.watcher.logger.exception(
                    "Failed to reinitialise CAPTCHA solver: %s", error
                )

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
        _ = args
        self.config.load_config()
        self.watcher.logger.info("Configuration reloaded from config.ini.")

    def _handle_websocket_test(self, args):
        """
        Triggers a test.
        - No args: PING test (if WebSocket is live).
        - 'notify': Simulates a new job notification.
        """
        command = "ping"
        if args and args[0].lower() == "notify":
            command = "notify"
        with self.watcher._test_command_lock:
            if command == "ping":
                if self.watcher.websocket_status == "Live":
                    self.watcher.logger.info("Triggering WebSocket PING test...")
                    self.watcher._test_command = "ping"
                else:
                    self.watcher.logger.warning(
                        f"WebSocket is not live (status: {self.watcher.websocket_status}). PING test aborted."
                    )
            elif command == "notify":
                self.watcher.logger.info("Triggering test job notification...")
                self.watcher._test_command = "notify"
    
    def _handle_captcha_setup(self, args=None):
        """Handle CAPTCHA setup command"""
        _ = args
        from .captcha_cli import setup_captcha_solver
        try:
            setup_captcha_solver(self.watcher)
        except Exception as e:
            self.watcher.logger.exception(f"Error setting up CAPTCHA solver: {e}")
    
    def _handle_captcha_test(self, args=None):
        """Handle CAPTCHA test command"""
        _ = args
        from .captcha_cli import test_captcha_solver
        try:
            test_captcha_solver(self.watcher)
        except Exception as e:
            self.watcher.logger.exception(f"Error testing CAPTCHA solver: {e}")
    
    def _handle_captcha_stats(self, args=None):
        """Handle CAPTCHA stats command"""
        _ = args
        from .captcha_cli import show_captcha_stats
        try:
            show_captcha_stats(self.watcher)
        except Exception as e:
            self.watcher.logger.exception(f"Error showing CAPTCHA stats: {e}")
    
    def _handle_captcha_reset(self, args=None):
        """Handle CAPTCHA reset command"""
        _ = args
        from .captcha_cli import reset_captcha_config
        try:
            reset_captcha_config(self.watcher)
        except Exception as e:
            self.watcher.logger.exception(f"Error resetting CAPTCHA config: {e}")

    def _handle_accept_stats(self, args=None):
        """Handle job acceptance stats command"""
        _ = args
        try:
            stats = self.watcher.get_job_acceptance_stats()
            self.watcher.logger.info("Job Acceptance Statistics:")
            self.watcher.logger.info(f"  Enabled: {stats['enabled']}")
            self.watcher.logger.info(f"  Accepted Jobs: {stats['accepted_jobs']}")
            self.watcher.logger.info(f"  Failed Acceptances: {stats['failed_acceptances']}")
            self.watcher.logger.info(f"  Rate Limited: {stats['rate_limited']}")
            self.watcher.logger.info(f"  Current Rate: {stats['current_rate']:.2f} requests/sec")
        except Exception as e:
            self.watcher.logger.exception(f"Error showing job acceptance stats: {e}")