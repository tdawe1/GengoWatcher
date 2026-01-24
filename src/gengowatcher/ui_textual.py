"""
Textual-based TUI for GengoWatcher.

Replaces the Rich Live-based UI with proper scrolling, mouse support,
and modern widget system.
"""

import datetime
import inspect
import os
import threading
import time
from collections import deque

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Footer,
    Input,
    Label,
    Log,
    Static,
    RichLog,
    TabbedContent,
    TabPane,
    DataTable,
)
from textual.screen import ModalScreen
from textual.command import Provider

from textual import work
from rich.table import Table
from rich.text import Text

from .watcher import GengoWatcher, __version__
from .config import AppConfig
from .state import AppState


class HelpScreen(ModalScreen):
    """Modal screen to show help commands."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("question_mark", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-container"):
            yield Label("Available Commands", id="help-title")
            yield Static(id="help-list")
            yield Label("Press ESC or ? to close", classes="help-footer")

    def on_mount(self) -> None:
        # Use the app's logic to generate the table
        if hasattr(self.app, "_handle_help"):
            table = self.app._handle_help()
            self.query_one("#help-list", Static).update(table)


class StatsSparkline(Static):
    """Sparkline widget showing jobs/hour trend."""

    SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"

    def __init__(self, data=None, **kwargs):
        super().__init__(**kwargs)
        self.data = deque(maxlen=20)
        if data:
            self.data.extend(data)

    def add_data(self, value: float) -> None:
        self.data.append(value)
        self.refresh()

    def render(self):
        if not self.data:
            return ""

        min_val = min(self.data)
        max_val = max(self.data)
        range_val = max_val - min_val

        if range_val == 0:
            # If all values are the same, show middle bar or max
            return self.SPARKLINE_CHARS[4] * len(self.data)

        result = ""
        for val in self.data:
            normalized = (val - min_val) / range_val
            # Clamp to index range 0-7
            index = int(normalized * (len(self.SPARKLINE_CHARS) - 1))
            result += self.SPARKLINE_CHARS[index]

        return result


class HistoryInput(Input):
    """Input with command history support."""

    BINDINGS = [
        Binding("up", "history_up", "History Up", show=False),
        Binding("down", "history_down", "History Down", show=False),
    ]

    def action_history_up(self) -> None:
        app = self.app
        if not app.command_history:
            return

        if app.history_index == -1:
            # Save current input if we haven't started navigating history
            app._temp_input = self.value
            app.history_index = len(app.command_history) - 1
        elif app.history_index > 0:
            app.history_index -= 1

        self.value = app.command_history[app.history_index]
        self.cursor_position = len(self.value)

    def action_history_down(self) -> None:
        app = self.app
        if app.history_index == -1:
            return

        if app.history_index < len(app.command_history) - 1:
            app.history_index += 1
            self.value = app.command_history[app.history_index]
        else:
            # Restore temp input or clear
            app.history_index = -1
            self.value = getattr(app, "_temp_input", "")

        self.cursor_position = len(self.value)


class HeaderPanel(Static):
    """Header panel showing configuration summary."""

    def __init__(self, config: AppConfig, **kwargs):
        super().__init__(**kwargs)
        self.config = config

    def compose(self) -> ComposeResult:
        yield Static(id="header-content")

    def on_mount(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style="bold", justify="right", width=24)
        table.add_column(justify="left")

        table.add_row(
            "Feed URL:", f"[#7dcfff]{self.config.get('Watcher', 'feed_url')}[/]"
        )
        table.add_row(
            "Check Interval:",
            f"{self.config.get('Watcher', 'check_interval')} seconds",
        )
        table.add_row()
        table.add_row(
            "Minimum Reward:",
            f"[#9ece6a]US$ {self.config.get('Watcher', 'min_reward'):.2f}[/]",
        )

        notif_enabled = self.config.get("Watcher", "enable_notifications")
        sound_enabled = self.config.get("Watcher", "enable_sound")
        table.add_row(
            "Desktop Notifications:",
            "[#9ece6a]Enabled[/]" if notif_enabled else "[#f7768e]Disabled[/]",
        )
        table.add_row(
            "Sound Alerts:",
            "[#9ece6a]Enabled[/]" if sound_enabled else "[#f7768e]Disabled[/]",
        )

        self.query_one("#header-content", Static).update(table)

    def refresh_config(self) -> None:
        self._refresh_content()


class RuntimeStatusPanel(Vertical):
    """Runtime status panel showing live statistics."""

    def __init__(
        self, watcher: GengoWatcher, config: AppConfig, state: AppState, **kwargs
    ):
        super().__init__(**kwargs)
        self.watcher = watcher
        self.config = config
        self.state = state

    def compose(self) -> ComposeResult:
        # Row 1
        yield Label("Uptime:", classes="status-label")
        yield Label("--", id="stat-uptime", classes="status-value")
        yield Label("Jobs/Hour:", classes="status-label")
        yield Label("--", id="stat-jph", classes="status-value")

        # Row 2
        yield Label("Jobs (Sess):", classes="status-label")
        yield Label("0", id="stat-jobs-sess", classes="status-value")
        yield Label("Found (Tot):", classes="status-label")
        yield Label("0", id="stat-jobs-tot", classes="status-value")

        # Row 3
        yield Label("Value (Sess):", classes="status-label")
        yield Label("$0.00", id="stat-val-sess", classes="status-value")
        yield Label("Avg Reward:", classes="status-label")
        yield Label("$0.00", id="stat-avg-reward", classes="status-value")

        # Row 4

        # Row 5 - Flags
        yield Label("RSS Fallback:", classes="status-label")
        yield Label("--", id="stat-rss", classes="status-badge status-text-dim")
        yield Label("Auto-Accept:", classes="status-label")
        yield Label("--", id="stat-autoaccept", classes="status-badge status-text-dim")

        # Row 6 - Flags & WS
        yield Label("CAPTCHA:", classes="status-label")
        yield Label("--", id="stat-captcha", classes="status-badge status-text-dim")
        yield Label("WebSocket:", classes="status-label")
        yield Label(
            "Initializing...",
            id="ws-status-indicator",
            classes="status-badge status-offline",
        )

        # Row 7 - Heartbeat
        yield Label("WS Heartbeat:", classes="status-label")
        yield Label("--", id="stat-ws-heartbeat", classes="status-value span-3")

        # Row - Email/Website Monitor Header
        yield Label("── Monitors ──", classes="monitor-section-label")

        # Row - Email Monitor
        yield Label("Email:", classes="status-label")
        yield Label("--", id="stat-email-status", classes="status-value")
        yield Label("Last:", classes="status-label")
        yield Label("--", id="stat-email-last", classes="status-value")

        # Row - Website Monitor
        yield Label("Website:", classes="status-label")
        yield Label("--", id="stat-website-status", classes="status-value")
        yield Label("Last:", classes="status-label")
        yield Label("--", id="stat-website-last", classes="status-value")

        # Row - Monitor Stats
        yield Label("Email Jobs:", classes="status-label")
        yield Label("0", id="stat-email-jobs", classes="status-value")
        yield Label("Web Jobs:", classes="status-label")
        yield Label("0", id="stat-website-jobs", classes="status-value")

        # Sparkline Section
        yield Label("Jobs/Hour Trend:", classes="sparkline-label span-4")
        yield StatsSparkline(
            data=self.state.sparkline_data, id="sparkline", classes="span-4"
        )

    def refresh_status(self) -> None:
        # Calculate stats
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

        # Update Labels
        self.query_one("#stat-uptime", Label).update(
            str(datetime.timedelta(seconds=int(uptime_seconds)))
        )
        self.query_one("#stat-jph", Label).update(f"{jobs_per_hour:.1f}")

        self.query_one("#stat-jobs-sess", Label).update(
            str(self.watcher.session_new_entries)
        )
        self.query_one("#stat-jobs-tot", Label).update(
            str(self.state.total_new_entries_found)
        )

        self.query_one("#stat-val-sess", Label).update(
            f"US$ {self.watcher.session_total_value:.2f}"
        )
        self.query_one("#stat-avg-reward", Label).update(f"US$ {avg_reward:.2f}")

        # Update Sparkline
        try:
            sparkline = self.query_one("#sparkline", StatsSparkline)
            sparkline.add_data(jobs_per_hour)
            # Update state with latest data
            self.state.sparkline_data = list(sparkline.data)
        except Exception:
            pass

        # WebSocket Status
        ws_status = self.watcher.websocket_status
        status_class = "status-offline"
        if ws_status == "Live":
            status_class = "status-live"
        elif ws_status in ("Connecting", "Authenticating"):
            status_class = "status-connecting"

        try:
            lbl = self.query_one("#ws-status-indicator", Label)
            lbl.update(ws_status)
            lbl.classes = f"status-badge {status_class}"
        except Exception:
            pass

        # RSS Status
        seconds_remaining = max(0, self.watcher.next_check_time - time.time())
        rss_status_text = f"{self.watcher.rss_action} ({int(seconds_remaining)}s)"
        rss_class = "status-text-cyan"
        if "Backoff" in self.watcher.rss_action or "Paused" in self.watcher.rss_action:
            rss_class = "status-text-orange"

        if os.path.exists(self.watcher.PAUSE_FILE):
            rss_status_text = "Paused"

        rss_lbl = self.query_one("#stat-rss", Label)
        rss_lbl.update(rss_status_text)
        rss_lbl.classes = f"status-badge {rss_class}"

        # Auto-Accept
        autoaccept_enabled = self.config.getboolean("AutoAccept", "enabled")
        autoaccept_status = "Enabled" if autoaccept_enabled else "Disabled"
        aa_class = "status-text-green" if autoaccept_enabled else "status-text-dim"

        aa_lbl = self.query_one("#stat-autoaccept", Label)
        aa_lbl.update(autoaccept_status)
        aa_lbl.classes = f"status-badge {aa_class}"

        # Captcha
        captcha_enabled = self.config.getboolean("Captcha", "enabled")
        captcha_status = "Enabled" if captcha_enabled else "Disabled"
        cap_class = "status-text-green" if captcha_enabled else "status-text-dim"

        cap_lbl = self.query_one("#stat-captcha", Label)
        cap_lbl.update(captcha_status)
        cap_lbl.classes = f"status-badge {cap_class}"

        # WebSocket Heartbeat
        hb = "—"
        if ws_status == "Live":
            now = time.time()
            parts = []
            try:
                if getattr(self.watcher, "websocket_ping_latency_ms", None) is not None:
                    parts.append(f"{int(self.watcher.websocket_ping_latency_ms)}ms")
                if getattr(self.watcher, "websocket_last_pong_ts", None):
                    last_pong_age = max(
                        0, int(now - self.watcher.websocket_last_pong_ts)
                    )
                    parts.append(f"last {last_pong_age}s")
            except Exception:
                pass
            hb = " | ".join(parts) if parts else "idle"

        self.query_one("#stat-ws-heartbeat", Label).update(hb)

        if hasattr(self.watcher, "_sync_monitor_metrics"):
            self.watcher._sync_monitor_metrics()

        email_status = getattr(self.watcher, "email_monitor_status", "Disabled")
        self.query_one("#stat-email-status", Label).update(email_status)

        email_last = getattr(self.watcher, "email_last_check_time", None)
        if email_last:
            ago = int(time.time() - email_last)
            self.query_one("#stat-email-last", Label).update(f"{ago}s ago")
        else:
            self.query_one("#stat-email-last", Label).update("--")

        email_jobs = getattr(self.watcher, "email_jobs_found_session", 0)
        self.query_one("#stat-email-jobs", Label).update(str(email_jobs))

        web_status = getattr(self.watcher, "website_monitor_status", "Disabled")
        self.query_one("#stat-website-status", Label).update(web_status)

        web_last = getattr(self.watcher, "website_last_check_time", None)
        if web_last:
            ago = int(time.time() - web_last)
            self.query_one("#stat-website-last", Label).update(f"{ago}s ago")
        else:
            self.query_one("#stat-website-last", Label).update("--")

        web_jobs = getattr(self.watcher, "website_jobs_found_session", 0)
        self.query_one("#stat-website-jobs", Label).update(str(web_jobs))


class StatusBar(Static):
    """Bottom status bar showing overall system status."""

    def __init__(self, watcher: GengoWatcher, state: AppState, **kwargs):
        super().__init__(**kwargs)
        self.watcher = watcher
        self.state = state

    def refresh_status(self) -> None:
        status, color = ("Running", "#9ece6a")
        if self.watcher.shutdown_event.is_set():
            status, color = ("Stopped", "#f7768e")
        elif os.path.exists(self.watcher.PAUSE_FILE):
            status, color = ("Paused", "#e0af68")

        monitor_status = self.watcher.get_monitor_status()
        dead_monitors = [
            name for name, state in monitor_status.items() if state == "dead"
        ]
        if dead_monitors and status == "Running":
            status, color = ("Degraded", "#e0af68")

        ws_status_text, ws_status_color = {
            "Live": ("Live", "#9ece6a"),
            "Connecting": ("Connecting", "#e0af68"),
            "Authenticating": ("Authenticating", "#e0af68"),
            "Offline": ("Offline", "#e0af68"),
            "Disabled": ("Disabled", "#565f89"),
            "Stopped": ("Stopped", "#f7768e"),
        }.get(self.watcher.websocket_status, (self.watcher.websocket_status, "#f7768e"))

        if monitor_status.get("websocket") == "dead" and ws_status_text not in (
            "Disabled",
            "Stopped",
        ):
            ws_status_text, ws_status_color = ("Dead", "#f7768e")

        rss_status = self.watcher.rss_action
        rss_color = "#7dcfff"
        if monitor_status.get("rss") == "dead":
            rss_status, rss_color = ("Dead", "#f7768e")

        parts = [
            f"[bold]Status:[/] [{color}]{status}[/]",
            f"[bold]WS:[/] [{ws_status_color}]{ws_status_text}[/]",
            f"[bold]RSS:[/] [{rss_color}]{rss_status}[/]",
        ]

        if monitor_status.get("email") != "disabled":
            email_state = monitor_status.get("email")
            email_color = "#9ece6a" if email_state == "alive" else "#f7768e"
            email_text = "OK" if email_state == "alive" else "Dead"
            parts.append(f"[bold]Email:[/] [{email_color}]{email_text}[/]")

        if monitor_status.get("website") != "disabled":
            website_state = monitor_status.get("website")
            website_color = "#9ece6a" if website_state == "alive" else "#f7768e"
            website_text = "OK" if website_state == "alive" else "Dead"
            parts.append(f"[bold]Web:[/] [{website_color}]{website_text}[/]")

        parts.append(
            f"[bold]Found:[/] [#9ece6a]{self.state.total_new_entries_found}[/]"
        )

        self.update(" │ ".join(parts))


class JobsTable(DataTable):
    """DataTable for displaying found jobs."""

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.add_columns("Time", "Source", "Language Pair", "Reward", "Status")
        self.zebra_stripes = True


class GengoWatcherCommands(Provider):
    """Command palette provider."""

    async def search(self, query: str):
        matcher = self.matcher(query)
        app = self.screen.app
        assert isinstance(app, GengoWatcherApp)

        for name, command in app.commands.items():
            display_name = name
            if command.get("aliases"):
                display_name = f"{name} ({', '.join(command['aliases'])})"

            score = matcher.match(display_name)
            if score > 0:
                yield self.hit(
                    score,
                    matcher.highlight(display_name),
                    lambda n=name: app._execute_command(n),
                    help=command["help"],
                )


class GengoWatcherApp(App):
    """Textual TUI application for GengoWatcher."""

    TITLE = "GengoWatcher"
    SUB_TITLE = f"v{__version__}"
    COMMANDS = {GengoWatcherCommands}

    CSS_PATH = "gengo_watcher.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("escape", "quit", "Quit", show=False),
        Binding("c", "check", "Check Now", show=True),
        Binding("p", "pause", "Pause", show=True),
        Binding("r", "resume", "Resume", show=True),
        Binding("h", "help", "Help", show=True),
        Binding("t", "toggle_runtime", "Dashboard", show=True),
        Binding("question_mark", "show_help", "Help", key_display="?", show=False),
        Binding("ctrl+p", "command_palette", "Commands", show=True),
        Binding("ctrl+l", "clear_log", "Clear", show=False),
        # Tab shortcuts
        Binding("1", "tab_dashboard", "Dashboard", show=False),
        Binding("2", "tab_jobs", "Jobs", show=False),
        Binding("3", "tab_activity", "Activity", show=False),
        Binding("4", "tab_output", "Output", show=False),
        Binding("5", "tab_charts", "Charts", show=False),
    ]

    def __init__(
        self,
        watcher: GengoWatcher,
        config: AppConfig,
        state: AppState,
        log_queue: deque,
    ):
        super().__init__()
        self.watcher = watcher
        self.config = config
        self.state = state
        self.log_queue = log_queue
        self._log_queue_lock = threading.Lock()
        self.jobs_data = []
        self.command_history = []
        self.history_index = -1
        self.runtime_visible = True
        self._init_commands()

    def _init_commands(self) -> None:
        """Initialize command handlers - ported from Rich UI."""
        self.commands = {
            "check": {
                "handler": self._handle_check,
                "help": "Trigger an immediate RSS feed check.",
            },
            "help": {
                "handler": self._handle_help,
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
                "help": "Clear the output panel.",
            },
            "wstest": {
                "handler": self._handle_websocket_test,
                "aliases": ["wt"],
                "help": "Test WebSocket. Use 'wt' for PING, 'wt notify' for test notification.",
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
            "debug": {
                "handler": self._handle_debug,
                "aliases": ["d"],
                "help": "Toggle debug category. Usage: d <category>, d raw [show|clear], d list.",
            },
            "setup-email": {
                "handler": self._handle_setup_email,
                "aliases": ["se"],
                "help": "Configure Gmail OAuth for email monitoring.",
            },
            "toggleemail": {
                "handler": self._handle_toggle_email,
                "aliases": ["te"],
                "help": "Toggle email monitor on/off.",
            },
            "emailstats": {
                "handler": self._cmd_email_stats,
                "aliases": ["es", "emailinfo"],
                "help": "Show email monitor statistics.",
            },
            "togglewebsite": {
                "handler": self._handle_toggle_website,
                "aliases": ["tweb"],
                "help": "Toggle website monitor on/off.",
            },
            "websitestats": {
                "handler": self._cmd_website_stats,
                "aliases": ["ws", "webinfo"],
                "help": "Show website monitor statistics.",
            },
        }
        self.alias_map = {
            alias: cmd
            for cmd, details in self.commands.items()
            for alias in [cmd] + details.get("aliases", [])
        }

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Static(
            f"[bold]GengoWatcher[/] v{__version__}",
            id="app-header",
        )

        # Main tabbed content - primary navigation
        with TabbedContent(initial="dashboard", id="main-tabs"):
            # Dashboard tab - status overview
            with TabPane("Dashboard", id="dashboard"):
                with Vertical(id="dashboard-content"):
                    runtime_panel = RuntimeStatusPanel(
                        self.watcher, self.config, self.state, id="runtime-panel"
                    )
                    runtime_panel.border_title = "Runtime Status"
                    yield runtime_panel

                    header_panel = HeaderPanel(self.config, id="header-panel")
                    header_panel.border_title = "Configuration"
                    yield header_panel

            # Jobs tab - full-width jobs table
            with TabPane("Jobs", id="jobs"):
                yield JobsTable(id="jobs-table")

            # Activity tab - activity log
            with TabPane("Activity", id="activity"):
                activity_log = RichLog(
                    highlight=True,
                    markup=True,
                    auto_scroll=True,
                    max_lines=1000,
                    id="activity-log",
                )
                yield activity_log

            # Output tab - command output
            with TabPane("Output", id="output"):
                output_log = RichLog(
                    highlight=True,
                    markup=True,
                    auto_scroll=True,
                    max_lines=500,
                    id="output-log",
                )
                yield output_log

            # Charts tab - placeholder for Phase 4
            with TabPane("Charts", id="charts"):
                yield Static(
                    "[dim]Charts coming soon - install textual-plotext[/]",
                    id="charts-placeholder",
                )

        # Bottom status and input area
        with Vertical(id="bottom-area"):
            yield StatusBar(self.watcher, self.state, id="status-bar")
            yield HistoryInput(
                placeholder="Type command (h or ? for help)...", id="cmd-input"
            )

        yield Footer()

    def on_mount(self) -> None:
        """Initialize on mount."""
        self.query_one("#activity-log", RichLog).write("[green]GengoWatcher started[/]")

        # Load recent jobs from state or CSV
        try:
            if self.state.get_job_count() < 100:
                csv_path = self.config.get("Paths", "all_entries_log")
                if csv_path:
                    self.state.load_jobs_from_csv(csv_path)

            recent_jobs = self.state.get_recent_jobs(limit=1000)
            if recent_jobs:
                table = self.query_one("#jobs-table", JobsTable)
                for job in recent_jobs:
                    # Convert timestamp to readable string
                    ts = job.get("timestamp", 0)
                    time_str = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")

                    self.add_job(
                        time_str,
                        job.get("source", "Unknown"),
                        job.get("lang_pair", "Unknown"),
                        f"{job.get('reward_currency', 'USD')} {job.get('reward', 0.0):.2f}",
                        "Found",  # Initial status for historical jobs
                    )
                self.watcher.logger.info(
                    f"Loaded {len(recent_jobs)} recent jobs from history."
                )
        except Exception as e:
            self.watcher.logger.error(f"Failed to load recent jobs: {e}")

        self.refresh_worker()

    def add_job(
        self, time: str, source: str, lang_pair: str, reward: str, status: str
    ) -> None:
        """Add a job to the jobs table."""
        self.jobs_data.append(
            {
                "time": time,
                "source": source,
                "lang_pair": lang_pair,
                "reward": reward,
                "status": status,
            }
        )
        try:
            table = self.query_one("#jobs-table", JobsTable)
            table.add_row(time, source, lang_pair, reward, status)
            # Scroll to end if needed, or keep at top? Textual tables usually scroll.
        except Exception:
            pass

    @work(thread=True)
    def refresh_worker(self) -> None:
        """Background worker to refresh UI from watcher state."""
        while not self.watcher.shutdown_event.is_set():
            try:
                # Check if app is still running before calling
                if self._exit:
                    break
                self.call_from_thread(self._refresh_ui)
                self.call_from_thread(self._drain_log_queue)
            except Exception:
                # App may be shutting down, exit gracefully
                if self._exit or self.watcher.shutdown_event.is_set():
                    break
            time.sleep(0.5)

    def _refresh_ui(self) -> None:
        """Refresh all dynamic UI elements."""
        try:
            self.query_one("#runtime-panel", RuntimeStatusPanel).refresh_status()
            self.query_one("#status-bar", StatusBar).refresh_status()
        except Exception:
            pass

    def _drain_log_queue(self) -> None:
        """Drain log queue to activity log widget."""
        activity_log = self.query_one("#activity-log", RichLog)
        with self._log_queue_lock:
            while self.log_queue:
                try:
                    item = self.log_queue.popleft()
                    if hasattr(item, "__rich__") or hasattr(item, "__rich_console__"):
                        activity_log.write(item)
                    else:
                        activity_log.write(str(item))
                except Exception:
                    break

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle command input."""
        command_str = event.value.strip()
        event.input.clear()

        if not command_str:
            return

        # Add to history
        if not self.command_history or self.command_history[-1] != command_str:
            self.command_history.append(command_str)
            if len(self.command_history) > 50:
                self.command_history.pop(0)
        self.history_index = -1

        self._execute_command(command_str)

    def _execute_command(self, command_str: str) -> None:
        """Execute a command."""
        parts = command_str.split()
        if not parts:
            return

        cmd_alias, args = parts[0].lower(), parts[1:]
        command = self.alias_map.get(cmd_alias)

        if not command:
            self.watcher.logger.error(f"Unknown command: '{command_str}'")
            self.notify(f"Unknown command: {cmd_alias}", severity="error")
            return

        handler = self.commands[command]["handler"]
        try:
            sig = inspect.signature(handler)
            if "args" in sig.parameters:
                output = handler(args)
            else:
                output = handler()

            if output:
                output_log = self.query_one("#output-log", RichLog)
                output_log.clear()
                if hasattr(output, "__rich__") or hasattr(output, "__rich_console__"):
                    output_log.write(output)
                else:
                    output_log.write(str(output))
        except Exception as e:
            self.watcher.logger.exception(f"Error executing '{command}': {e}")
            self.notify(f"Error: {e}", severity="error")

    # === Action handlers for keyboard shortcuts ===

    def action_toggle_runtime(self) -> None:
        """Toggle to dashboard tab to view runtime stats."""
        try:
            tabbed = self.query_one("#main-tabs", TabbedContent)
            tabbed.active = "dashboard"
        except Exception:
            pass

    def action_tab_dashboard(self) -> None:
        """Switch to Dashboard tab."""
        self.query_one("#main-tabs", TabbedContent).active = "dashboard"

    def action_tab_jobs(self) -> None:
        """Switch to Jobs tab."""
        self.query_one("#main-tabs", TabbedContent).active = "jobs"

    def action_tab_activity(self) -> None:
        """Switch to Activity tab."""
        self.query_one("#main-tabs", TabbedContent).active = "activity"

    def action_tab_output(self) -> None:
        """Switch to Output tab."""
        self.query_one("#main-tabs", TabbedContent).active = "output"

    def action_tab_charts(self) -> None:
        """Switch to Charts tab."""
        self.query_one("#main-tabs", TabbedContent).active = "charts"

    def action_show_help(self) -> None:
        """Show help modal."""
        self.push_screen(HelpScreen())

    def action_quit(self) -> None:
        """Quit the application."""
        self.watcher.handle_exit()
        self.exit()

    def action_check(self) -> None:
        """Trigger immediate check."""
        self._handle_check()

    def action_pause(self) -> None:
        """Pause monitoring."""
        self._handle_pause()

    def action_resume(self) -> None:
        """Resume monitoring."""
        self._handle_resume()

    def action_help(self) -> None:
        """Show help."""
        self._handle_help()

    def action_clear_log(self) -> None:
        """Clear activity log."""
        self.query_one("#activity-log", RichLog).clear()

    # === Command handlers (ported from Rich UI) ===

    def _handle_check(self, args=None) -> None:
        _ = args
        self.watcher.check_now_event.set()
        self.watcher.logger.info("Manual check triggered.")
        self.notify("Manual check triggered")

    def _handle_help(self, args=None) -> Table:
        _ = args
        table = Table(title="Commands", show_header=True, header_style="bold")
        table.add_column("Command", style="cyan")
        table.add_column("Aliases", style="dim")
        table.add_column("Description")

        for cmd, info in self.commands.items():
            aliases = ", ".join(info.get("aliases", []))
            table.add_row(cmd, aliases, info["help"])

        return table

    def _handle_exit(self, args=None) -> None:
        _ = args
        self.watcher.handle_exit()
        self.exit()

    def _handle_pause(self, args=None) -> None:
        _ = args
        if not os.path.exists(self.watcher.PAUSE_FILE):
            with open(self.watcher.PAUSE_FILE, "w") as f:
                f.write("Paused.")
            self.watcher.logger.warning("Watcher paused.")
            self.notify("Watcher paused", severity="warning")
        else:
            self.watcher.logger.warning("Watcher is already paused.")
            self.notify("Already paused", severity="warning")

    def _handle_resume(self, args=None) -> None:
        _ = args
        if os.path.exists(self.watcher.PAUSE_FILE):
            os.remove(self.watcher.PAUSE_FILE)
            self.watcher.logger.info("Watcher resumed.")
            self.notify("Watcher resumed")
        else:
            self.watcher.logger.warning("Watcher is not paused.")
            self.notify("Not paused", severity="warning")

    def _handle_toggle_sound(self, args=None) -> None:
        _ = args
        current_state = self.config.get("Watcher", "enable_sound")
        self.config.set("Watcher", "enable_sound", not current_state)
        self.config.save_config()
        status = "enabled" if not current_state else "disabled"
        self.watcher.logger.info(f"Sound alerts {status}.")
        self.notify(f"Sound {status}")
        self.query_one("#header-panel", HeaderPanel).refresh_config()

    def _handle_toggle_notifications(self, args=None) -> None:
        _ = args
        current_state = self.config.get("Watcher", "enable_notifications")
        self.config.set("Watcher", "enable_notifications", not current_state)
        self.config.save_config()
        status = "enabled" if not current_state else "disabled"
        self.watcher.logger.info(f"Desktop notifications {status}.")
        self.notify(f"Notifications {status}")
        self.query_one("#header-panel", HeaderPanel).refresh_config()

    def _handle_toggle_websocket(self, args=None) -> None:
        _ = args
        current_state = self.config.get("WebSocket", "enable_websocket")
        self.config.set("WebSocket", "enable_websocket", not current_state)
        self.config.save_config()
        status = "enabled" if not current_state else "disabled"
        self.watcher.logger.info(f"WebSocket monitoring {status}.")
        self.watcher.logger.warning("Restart required for this change.")
        self.notify(f"WebSocket {status} (restart required)", severity="warning")

    def _handle_autoaccept(self, args=None) -> None:
        _ = args
        current_state = self.config.getboolean("AutoAccept", "enabled")
        self.config.set("AutoAccept", "enabled", not current_state)
        self.config.save_config()
        status = "enabled" if not current_state else "disabled"
        self.watcher.logger.info(f"Auto-accept {status}.")
        self.notify(f"Auto-accept {status}")

        if hasattr(self.watcher, "job_acceptance_engine"):
            self.watcher.job_acceptance_engine.enabled = not current_state

    def _handle_captchatoggle(self, args=None) -> None:
        _ = args
        current_state = self.config.getboolean("Captcha", "enabled")
        self.config.set("Captcha", "enabled", not current_state)
        self.config.save_config()
        status = "enabled" if not current_state else "disabled"
        self.watcher.logger.info(f"CAPTCHA solving {status}.")
        self.notify(f"CAPTCHA {status}")

        if hasattr(self.watcher, "captcha_solver"):
            try:
                self.watcher.captcha_solver.reinitialize()
            except Exception as e:
                self.watcher.logger.exception(f"Failed to reinitialize CAPTCHA: {e}")

    def _handle_set_min_reward(self, args) -> None:
        if not args:
            self.watcher.logger.error("Usage: setminreward <amount>")
            self.notify("Usage: smr <amount>", severity="error")
            return
        try:
            amount = float(args[0])
            self.config.set("Watcher", "min_reward", amount)
            self.config.save_config()
            self.watcher.logger.info(f"Minimum reward set to US$ {amount:.2f}")
            self.notify(f"Min reward: ${amount:.2f}")
            self.query_one("#header-panel", HeaderPanel).refresh_config()
        except ValueError:
            self.watcher.logger.error("Invalid amount. Please enter a number.")
            self.notify("Invalid amount", severity="error")

    def _handle_reload_config(self, args=None) -> None:
        _ = args
        self.config.load_config()
        self.watcher.logger.info("Configuration reloaded from config.ini.")
        self.notify("Config reloaded")
        self.query_one("#header-panel", HeaderPanel).refresh_config()

    def _handle_clear(self, args=None) -> None:
        _ = args
        self.query_one("#output-log", RichLog).clear()
        self.watcher.logger.info("Output cleared.")

    def _handle_websocket_test(self, args) -> None:
        command = "ping"
        if args and args[0].lower() == "notify":
            command = "notify"

        with self.watcher._test_command_lock:
            if command == "ping":
                if self.watcher.websocket_status == "Live":
                    self.watcher.logger.info("Triggering WebSocket PING test...")
                    self.watcher._test_command = "ping"
                    self.notify("PING test triggered")
                else:
                    self.watcher.logger.warning(
                        f"WebSocket not live ({self.watcher.websocket_status})"
                    )
                    self.notify("WebSocket not live", severity="warning")
            elif command == "notify":
                self.watcher.logger.info("Triggering test notification...")
                self.watcher._test_command = "notify"
                self.notify("Test notification triggered")

    def _handle_captcha_setup(self, args=None) -> None:
        _ = args
        from .captcha_cli import setup_captcha_solver

        try:
            setup_captcha_solver(self.watcher)
        except Exception as e:
            self.watcher.logger.exception(f"CAPTCHA setup error: {e}")

    def _handle_captcha_test(self, args=None) -> None:
        _ = args
        from .captcha_cli import test_captcha_solver

        try:
            test_captcha_solver(self.watcher)
        except Exception as e:
            self.watcher.logger.exception(f"CAPTCHA test error: {e}")

    def _handle_captcha_stats(self, args=None) -> None:
        _ = args
        from .captcha_cli import show_captcha_stats

        try:
            show_captcha_stats(self.watcher)
        except Exception as e:
            self.watcher.logger.exception(f"CAPTCHA stats error: {e}")

    def _handle_captcha_reset(self, args=None) -> None:
        _ = args
        from .captcha_cli import reset_captcha_config

        try:
            reset_captcha_config(self.watcher)
        except Exception as e:
            self.watcher.logger.exception(f"CAPTCHA reset error: {e}")

    def _handle_accept_stats(self, args=None) -> None:
        _ = args
        try:
            stats = self.watcher.get_job_acceptance_stats()
            table = Table(title="Job Acceptance Statistics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="green")
            table.add_row("Enabled", str(stats["enabled"]))
            table.add_row("Accepted Jobs", str(stats["accepted_jobs"]))
            table.add_row("Failed", str(stats["failed_acceptances"]))
            table.add_row("Rate Limited", str(stats["rate_limited"]))
            table.add_row("Current Rate", f"{stats['current_rate']:.2f} req/s")
            return table
        except Exception as e:
            self.watcher.logger.exception(f"Accept stats error: {e}")

    def _handle_debug(self, args=None) -> Table | None:
        categories = [
            "websocket",
            "rss",
            "job",
            "captcha",
            "browser",
            "config",
            "system",
            "email",
            "website",
            "raw",
        ]

        if not args:
            self._show_debug_status(categories)
            return None

        arg = args[0].lower().strip() if args else ""

        if arg == "list":
            self._show_debug_status(categories)
            return None

        if arg == "all":
            for cat in categories:
                self.config.set("DebugCategories", cat, True)
            self.config.save_config()
            self.watcher.logger.info("All debug categories enabled")
            self.notify("All debug enabled")
            return None

        if arg == "none":
            for cat in categories:
                self.config.set("DebugCategories", cat, False)
            self.config.save_config()
            self.watcher.logger.info("All debug categories disabled")
            self.notify("All debug disabled")
            return None

        # Special handling for 'raw' - show buffered messages
        if arg == "raw":
            # Check for subcommand
            if len(args) > 1:
                subcmd = args[1].lower()
                if subcmd == "show":
                    return self._show_raw_ws_messages()
                elif subcmd == "clear":
                    self.watcher.clear_raw_ws_messages()
                    self.watcher.logger.info("Raw WebSocket message buffer cleared")
                    self.notify("Raw buffer cleared")
                    return None

            # Toggle raw mode
            current = self.config.get("DebugCategories", "raw")
            self.config.set("DebugCategories", "raw", not current)
            self.config.save_config()
            status = "enabled" if not current else "disabled"
            self.watcher.logger.info(f"Raw WebSocket output {status}")
            self.notify(f"Raw output: {status}")

            # If enabling, show current buffer contents
            if not current:
                return self._show_raw_ws_messages()
            return None

        if arg not in categories:
            self.watcher.logger.warning(f"Unknown category: {arg}")
            self.notify(f"Unknown: {arg}", severity="error")
            return None

        current = self.config.get("DebugCategories", arg)
        self.config.set("DebugCategories", arg, not current)
        self.config.save_config()
        status = "enabled" if not current else "disabled"
        self.watcher.logger.info(f"Debug '{arg}' {status}")
        self.notify(f"Debug {arg}: {status}")
        return None

    def _show_raw_ws_messages(self) -> Table:
        """Show raw WebSocket messages in a formatted table."""
        messages = self.watcher.get_raw_ws_messages()

        table = Table(
            title="Raw WebSocket Messages",
            show_header=True,
            header_style="bold cyan",
            expand=True,
        )
        table.add_column("Raw Output", style="white", no_wrap=False)

        if not messages:
            table.add_row("[dim]No messages captured yet.[/dim]")
            table.add_row(
                "[dim]Enable with 'd raw' and wait for WebSocket activity.[/dim]"
            )
        else:
            for msg in messages:
                table.add_row(msg)

        # Add status footer
        raw_enabled = self.config.get("DebugCategories", "raw")
        status_text = "[green]ON[/green]" if raw_enabled else "[red]OFF[/red]"
        table.add_row("")
        table.add_row(
            f"[dim]Raw capture: {status_text} | Buffer: {len(messages)}/50 | 'd raw clear' to clear[/dim]"
        )

        return table

    def _show_debug_status(self, categories) -> None:
        self.watcher.logger.info("Debug Categories:")
        for cat in categories:
            enabled = self.config.get("DebugCategories", cat)
            status = "ON" if enabled else "OFF"
            self.watcher.logger.info(f"  {cat}: {status}")

    def _handle_setup_email(self, args=None) -> None:
        _ = args
        self.watcher.logger.info("To configure Gmail OAuth, exit and run:")
        self.watcher.logger.info("  python -m gengowatcher.main --setup-email")
        self.notify("Exit and run --setup-email", severity="information")

    def _handle_toggle_email(self, args=None) -> None:
        _ = args
        current = self.config.get("EmailMonitor", "enabled")
        self.config.set("EmailMonitor", "enabled", not current)
        self.config.save_config()
        status = "enabled" if not current else "disabled"
        self.watcher.logger.info(f"Email monitor {status}. Restart to apply.")
        self.notify(f"Email {status} (restart)", severity="warning")

    def _handle_toggle_website(self, args=None) -> None:
        _ = args
        current = self.config.get("WebsiteMonitor", "enabled")
        self.config.set("WebsiteMonitor", "enabled", not current)
        self.config.save_config()
        status = "enabled" if not current else "disabled"
        self.watcher.logger.info(f"Website monitor {status}. Restart to apply.")
        self.notify(f"Website {status} (restart)", severity="warning")

    def _cmd_email_stats(self, args: list[str]) -> None:
        """Show email monitor statistics."""
        _ = args
        watcher = self.watcher
        if hasattr(watcher, "_sync_monitor_metrics"):
            watcher._sync_monitor_metrics()

        status = getattr(watcher, "email_monitor_status", "Disabled")
        last_check = getattr(watcher, "email_last_check_time", None)
        jobs = getattr(watcher, "email_jobs_found_session", 0)

        if last_check:
            ago = int(time.time() - last_check)
            last_str = f"{ago}s ago"
        else:
            last_str = "Never"

        self._log_panel("[bold]Email Monitor[/bold]")
        self._log_panel(f"  Status: {status}")
        self._log_panel(f"  Last Check: {last_str}")
        self._log_panel(f"  Jobs Found: {jobs}")

    def _cmd_website_stats(self, args: list[str]) -> None:
        """Show website monitor statistics."""
        _ = args
        watcher = self.watcher
        if hasattr(watcher, "_sync_monitor_metrics"):
            watcher._sync_monitor_metrics()

        status = getattr(watcher, "website_monitor_status", "Disabled")
        last_check = getattr(watcher, "website_last_check_time", None)
        jobs = getattr(watcher, "website_jobs_found_session", 0)

        if last_check:
            ago = int(time.time() - last_check)
            last_str = f"{ago}s ago"
        else:
            last_str = "Never"

        self._log_panel("[bold]Website Monitor[/bold]")
        self._log_panel(f"  Status: {status}")
        self._log_panel(f"  Last Check: {last_str}")
        self._log_panel(f"  Jobs Found: {jobs}")
