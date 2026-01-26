"""
Textual-based TUI for GengoWatcher.

Strict implementation of the v2.0 Design Doc.
"""

import datetime
import logging
import time
from collections import deque

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Grid, Container
from textual.widgets import (
    Footer,
    Input,
    Label,
    Static,
    RichLog,
    TabbedContent,
    TabPane,
    DataTable,
)
from textual import work
from rich.text import Text

from .watcher import GengoWatcher, __version__
from .config import AppConfig
from .state import AppState
from .stats import StatsManager

# =============================================================================
# Constants
# =============================================================================


class Icons:
    FOUND = "▲"
    ACCEPTED = "✓"
    VALUE = "$"
    RATE = "~"
    MIN_WORDS = "≥"

    WEBSOCKET = "●"
    EMAIL = "◉"
    WEB = "◎"
    RSS = "⊛"  # Added
    CAPTCHA = "⧗"
    WORKFLOW = "⇄"
    AUTO = "▶"  # Added

    IDLE = "○"
    LIVE = "∿∿∿"
    POLLING = "↻"


# =============================================================================
# Widgets
# =============================================================================


class TitleBar(Static):
    """3-line title bar: Brand, Separator, Info."""

    def on_mount(self) -> None:
        self.set_interval(1.0, self.update_clock)

    def compose(self) -> ComposeResult:
        # Line 1
        yield Static("◆ GENGOWATCHER v2.0", classes="brand")
        # Line 2
        yield Static("─" * 200, classes="separator")
        # Line 3
        with Horizontal(classes="info-row"):
            yield Static("Session: 0h 00m", id="session-timer")
            yield Static("  |  ", classes="dim")
            yield Static("12:00:00 JST", id="clock")

    def update_clock(self) -> None:
        now = datetime.datetime.now()
        try:
            self.query_one("#clock", Static).update(now.strftime("%H:%M:%S %Z"))
        except Exception:
            pass

        # Session timer
        app = self.app
        # Access watcher safely
        watcher = getattr(app, "watcher", None)
        if watcher:
            elapsed = int(time.time() - watcher.start_time)
            h, m = divmod(elapsed // 60, 60)
            try:
                self.query_one("#session-timer", Static).update(f"Session: {h}h {m}m")
            except Exception:
                pass


class MetricCard(Static):
    """Vertical metric card: Icon+Value on top, Label on bottom."""

    def __init__(self, label: str, icon: str, value: str = "0", **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self.icon = icon
        self.value = value

    def compose(self) -> ComposeResult:
        with Horizontal(classes="metric-value-row"):
            yield Static(self.icon, classes="metric-icon")
            yield Static(
                self.value, classes="metric-value", id=f"val-{self.label.lower()}"
            )
        yield Static(self.label, classes="metric-label")

    def update_value(self, value: str):
        try:
            self.query_one(f"#val-{self.label.lower()}", Static).update(value)
        except Exception:
            pass


class MetricsRow(Horizontal):
    """Container for 5 metric cards."""

    def compose(self) -> ComposeResult:
        yield MetricCard("Found", Icons.FOUND, "0", id="card-found")
        yield MetricCard("Accepted", Icons.ACCEPTED, "0", id="card-accepted")
        yield MetricCard("Value", Icons.VALUE, "$0.00", id="card-value")
        yield MetricCard("Rate", Icons.RATE, "0.0/hr", id="card-rate")
        yield MetricCard("Min", Icons.MIN_WORDS, "≥$0.00", id="card-min")

    def refresh_metrics(self, state: AppState):
        jobs = state.get_recent_jobs(limit=1000)
        found = len(jobs)
        accepted = sum(1 for j in jobs if j.get("accepted", False))
        value = sum(j.get("reward", 0) for j in jobs)

        try:
            self.query_one("#card-found", MetricCard).update_value(str(found))
            self.query_one("#card-accepted", MetricCard).update_value(str(accepted))
            self.query_one("#card-value", MetricCard).update_value(f"${value:.2f}")
        except Exception:
            pass


class StatusIndicator(Static):
    """Icon + Label + State."""

    def __init__(
        self,
        icon: str,
        label: str,
        state_text: str = "Idle",
        state_class: str = "status-idle",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.icon = icon
        self.label = label
        self.state_text = state_text
        self.state_class = state_class

    def compose(self) -> ComposeResult:
        yield Static(self.icon, classes="status-icon")
        yield Static(
            f"{self.label} {self.state_text}",
            classes=f"status-text {self.state_class}",
            id=f"stat-{self.label.lower()}",
        )

    def set_state(self, text: str, css_class: str):
        try:
            w = self.query_one(f"#stat-{self.label.lower()}", Static)
            w.update(f"{self.label} {text}")
            w.set_classes(f"status-text {css_class}")
        except Exception:
            pass


class StatusRow(Horizontal):
    """7 status indicators."""

    def compose(self) -> ComposeResult:
        yield StatusIndicator(Icons.WEBSOCKET, "WS", "Live", "status-live")
        yield StatusIndicator(Icons.EMAIL, "Email", "45s", "status-working")
        yield StatusIndicator(Icons.WEB, "Web", "Idle", "status-idle")
        yield StatusIndicator(Icons.RSS, "RSS", "Idle", "status-idle")  # Added
        yield StatusIndicator(Icons.CAPTCHA, "Captcha", "", "status-idle")
        yield StatusIndicator(Icons.WORKFLOW, "Workflow", "", "status-idle")
        yield StatusIndicator(Icons.AUTO, "Auto", "On", "status-live")  # Added


class DashboardQuadrant(Static):
    """Base class for quadrants."""

    def __init__(self, title: str, **kwargs):
        super().__init__(**kwargs)
        self.title_text = title

    def compose(self) -> ComposeResult:
        yield Static(f"┌─ {self.title_text} ────────────┐", classes="quadrant-title")
        yield Container(id="quadrant-content")


class ActivityPreview(DashboardQuadrant):
    def __init__(self, **kwargs):
        super().__init__("Recent Activity", **kwargs)

    def compose(self) -> ComposeResult:
        yield Static(f"┌─ {self.title_text} ────────────┐", classes="quadrant-title")
        yield RichLog(id="activity-log", markup=True)


class JobsPreview(DashboardQuadrant):
    def __init__(self, **kwargs):
        super().__init__("Jobs Preview", **kwargs)

    def compose(self) -> ComposeResult:
        yield Static(f"┌─ {self.title_text} ────────────┐", classes="quadrant-title")
        yield DataTable(id="jobs-table")

    def on_mount(self):
        try:
            dt = self.query_one(DataTable)
            dt.add_columns("ID", "Pair", "Words", "$$$")
        except Exception:
            pass


class ChartPlaceholder(DashboardQuadrant):
    def __init__(self, **kwargs):
        super().__init__("Jobs/Hour", **kwargs)

    def compose(self) -> ComposeResult:
        yield Static(f"┌─ {self.title_text} ────────────┐", classes="quadrant-title")
        yield Static(
            "\n    (Chart Placeholder)\n    ╭─╮\n  ╭─╯ ╰╮\n╭─╯    ╰────",
            classes="chart-ascii",
        )


class ConfigPreview(DashboardQuadrant):
    def __init__(self, **kwargs):
        super().__init__("Configuration", **kwargs)

    def compose(self) -> ComposeResult:
        yield Static(f"┌─ {self.title_text} ────────────┐", classes="quadrant-title")
        yield Static("Languages: JA↔EN\nCheck Interval: 60s")


class DashboardGrid(Grid):
    """2x2 Grid container."""

    def compose(self) -> ComposeResult:
        yield ActivityPreview()
        yield ChartPlaceholder()
        yield JobsPreview()
        yield ConfigPreview()


# =============================================================================
# Main App
# =============================================================================


class GengoWatcherApp(App):
    CSS_PATH = "gengo_watcher.tcss"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("c", "check", "Check"),
        ("p", "pause", "Pause"),
        ("?", "help", "Help"),
    ]

    def __init__(
        self,
        config: AppConfig,
        state: AppState,
        watcher: GengoWatcher,
        stats: StatsManager,
    ):
        super().__init__()
        self.config = config
        self.state = state
        self.watcher = watcher
        self.stats = stats

        # Setup logging redirection
        self._setup_logging()

    def _setup_logging(self):
        handler = TextualLogHandler(self)
        logging.getLogger().addHandler(handler)

    def compose(self) -> ComposeResult:
        # 1. Title Bar
        yield TitleBar()

        # 2. Tabs
        with TabbedContent(initial="dashboard"):
            with TabPane("Dashboard", id="dashboard"):
                yield MetricsRow()
                yield StatusRow()
                yield DashboardGrid()

            with TabPane("Jobs", id="jobs"):
                yield Static("Jobs Content")
            with TabPane("Activity", id="activity"):
                yield Static("Activity Content")
            with TabPane("Output", id="output"):
                yield Static("Output Content")
            with TabPane("Charts", id="charts"):
                yield Static("Charts Content")
            with TabPane("Stats", id="stats"):
                yield Static("Stats Content")

        # 3. Input & Footer
        yield Input(placeholder="> help_")
        yield Footer()

    def call_from_thread(self, func, *args, **kwargs):
        # The base App.call_from_thread will be used, but we need to ensure we don't block
        super().call_from_thread(func, *args, **kwargs)


class TextualLogHandler(logging.Handler):
    """Redirects logs to the ActivityPreview widget."""

    def __init__(self, app):
        super().__init__()
        self.app = app

    def emit(self, record):
        try:
            msg = self.format(record)
            self.app.call_from_thread(self.write_log, msg)
        except:
            pass

    def write_log(self, msg):
        try:
            log = self.app.query_one("#activity-log", RichLog)
            log.write(msg)
        except:
            pass
