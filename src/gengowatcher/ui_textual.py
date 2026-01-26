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
    """3-line title bar: Brand, Separator, Info (Config + Session + Clock)."""

    def __init__(self, config: AppConfig = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config

    def on_mount(self) -> None:
        self.set_interval(1.0, self.update_clock)

    def compose(self) -> ComposeResult:
        # Line 1: Brand
        yield Static("◆ GENGOWATCHER v2.0", classes="brand")

        # Line 2: Separator (handled by CSS border-bottom usually, but explicit line requested)
        yield Static("─" * 200, classes="separator")

        # Line 3: Info Row (Config | Session | Clock)
        with Horizontal(classes="info-row"):
            # Config section
            config_text = "Config: N/A"
            if self.config:
                sl = self.config.get("Watcher", "source_lang") or "JA"
                tl = self.config.get("Watcher", "target_lang") or "EN"
                interval = self.config.get("Watcher", "check_interval") or 60
                min_reward = self.config.get("Watcher", "min_reward") or 0.0

                lang = f"{sl}↔{tl}"
                config_text = f" {lang} | {interval}s | Min: ${float(min_reward):.2f} "
            yield Static(config_text, classes="config-info")

            yield Static(" | ", classes="dim")
            yield Static("Session: 0h 00m", id="session-timer")
            yield Static(" | ", classes="dim")
            yield Static("12:00:00 JST", id="clock")

    def update_clock(self) -> None:
        now = datetime.datetime.now()
        try:
            self.query_one("#clock", Static).update(now.strftime("%H:%M:%S"))
        except Exception:
            pass

        # Session timer
        app = self.app
        watcher = getattr(app, "watcher", None)
        if watcher:
            elapsed = int(time.time() - watcher.start_time)
            h, m = divmod(elapsed // 60, 60)
            try:
                self.query_one("#session-timer", Static).update(
                    f"Session: {h}h {m:02d}m"
                )
            except Exception:
                pass


class MetricCard(Static):
    """Metric card with precise Grid layout."""

    def __init__(self, label: str, icon: str, value: str = "0", **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self.icon = icon
        self.value = value
        self.border_title = label  # Native Textual border title

    def compose(self) -> ComposeResult:
        # Use a grid: Column 1 (Icon), Column 2 (Value)
        with Grid(classes="metric-grid"):
            yield Static(self.icon, classes="metric-icon")
            yield Static(
                self.value, classes="metric-value", id=f"val-{self.label.lower()}"
            )
        # Label is handled by border_title now, or we can keep it inside if desired.
        # Design doc shows "Found" at bottom. Let's keep it simple: Icon+Value centered.
        # The Label is strictly the card title/footer.
        # Let's put label at bottom as a Static if border_title isn't enough.
        yield Static(self.label, classes="metric-label")

    def update_value(self, value: str):
        try:
            self.query_one(f"#val-{self.label.lower()}", Static).update(value)
        except Exception:
            pass


class MetricsRow(Horizontal):
    """Row of 5 metric cards with sparklines."""

    def __init__(self, state: "AppState", **kwargs):
        super().__init__(**kwargs)
        self.state = state

    def compose(self) -> ComposeResult:
        yield MetricCard("Found", "▲", id="card-found", classes="found")
        yield MetricCard("Accepted", "✓", id="card-accepted", classes="accepted")
        yield MetricCard("Value", "$", id="card-value", classes="value")
        yield MetricCard("Rate", "~", id="card-rate", classes="rate")
        yield MetricCard("Today", "☀", id="card-today", classes="today")

    def refresh_metrics(self) -> None:
        if not self.state:
            return
        jobs = self.state.get_recent_jobs(limit=1000)
        found = len(jobs)
        accepted = sum(1 for j in jobs if j.get("accepted", False))
        total_value = sum(j.get("reward", 0) for j in jobs)

        # Rate calculation (simplified)
        rate = found / 1.0  # Placeholder

        self.query_one("#card-found", MetricCard).update_value(str(found))
        self.query_one("#card-accepted", MetricCard).update_value(str(accepted))
        self.query_one("#card-value", MetricCard).update_value(f"${total_value:.2f}")
        self.query_one("#card-rate", MetricCard).update_value(f"{rate:.1f}/hr")
        self.query_one("#card-today", MetricCard).update_value(f"${total_value:.2f}")


class StatusIndicator(Static):
    """Status indicator with icon and color."""

    def __init__(self, icon: str, name: str, **kwargs):
        super().__init__(**kwargs)
        self.icon = icon
        self.label_text = name
        self.add_class("status-indicator")

    def compose(self) -> ComposeResult:
        yield Static(f"{self.icon} {self.label_text}", classes="status-label")

    def set_state(self, state: str):
        self.remove_class("live", "working", "idle", "error")
        self.add_class(state)


class StatusRow(Horizontal):
    """Dedicated row of status indicators."""

    def __init__(self, watcher: "GengoWatcher", **kwargs):
        super().__init__(**kwargs)
        self.watcher = watcher

    def compose(self) -> ComposeResult:
        # 7 Indicators
        yield StatusIndicator("●", "WS", id="ind-ws")
        yield StatusIndicator("◉", "Email", id="ind-email")
        yield StatusIndicator("◎", "Web", id="ind-web")
        yield StatusIndicator("⊛", "RSS", id="ind-rss")
        yield StatusIndicator("⧗", "Cap", id="ind-cap")
        yield StatusIndicator("⇄", "Work", id="ind-work")
        yield StatusIndicator("▶", "Auto", id="ind-auto")

    def refresh_status(self):
        if not self.watcher:
            return
        # Basic wiring - elaborate later if needed
        self.query_one("#ind-ws", StatusIndicator).set_state(
            "live"
            if getattr(self.watcher, "websocket_status", "") == "Live"
            else "idle"
        )
        self.query_one("#ind-email", StatusIndicator).set_state(
            "working"
            if getattr(self.watcher, "email_monitor_status", "") == "Polling"
            else "idle"
        )
        self.query_one("#ind-web", StatusIndicator).set_state("idle")  # Placeholder
        self.query_one("#ind-rss", StatusIndicator).set_state(
            "working"
            if "Fetching" in getattr(self.watcher, "rss_action", "")
            else "idle"
        )
        self.query_one("#ind-cap", StatusIndicator).set_state("live")
        self.query_one("#ind-work", StatusIndicator).set_state("live")
        self.query_one("#ind-auto", StatusIndicator).set_state("idle")


class DashboardQuadrant(Static):
    """Base class for panels using native border titles."""

    def __init__(self, title: str, **kwargs):
        super().__init__(**kwargs)
        self.border_title = title  # Use native border title!
        self.add_class("dashboard-panel")

    def compose(self) -> ComposeResult:
        # No manual ASCII border here!
        yield Container(id="quadrant-content")


class ActivityPreview(DashboardQuadrant):
    def __init__(self, **kwargs):
        super().__init__("Recent Activity", **kwargs)

    def compose(self) -> ComposeResult:
        # Just yield content, border_title handles the header
        yield RichLog(id="activity-log", markup=True)


class JobsPreview(DashboardQuadrant):
    def __init__(self, state: "AppState", **kwargs):
        super().__init__("Jobs Preview", **kwargs)
        self.state = state

    def compose(self) -> ComposeResult:
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
        yield Static(
            "\n    (Chart Placeholder)\n    ╭─╮\n  ╭─╯ ╰╮\n╭─╯    ╰────",
            classes="chart-ascii",
        )


class ConfigPreview(DashboardQuadrant):
    def __init__(self, **kwargs):
        super().__init__("Configuration", **kwargs)

    def compose(self) -> ComposeResult:
        # This panel is now redundant if config is in TitleBar,
        # but user might want detailed config here.
        yield Static("Languages: JA↔EN\nCheck Interval: 60s")


class SessionStats(DashboardQuadrant):
    """Session statistics summary."""

    def __init__(self, watcher: "GengoWatcher", state: "AppState", **kwargs):
        super().__init__("Session", **kwargs)
        self.watcher = watcher
        self.state = state

    def compose(self) -> ComposeResult:
        with Vertical(id="session-stats-content"):
            yield Static("Duration: 0h 00m", id="stat-duration")
            yield Static("Found: 0", id="stat-found")
            yield Static("Accepted: 0", id="stat-accepted")
            yield Static("Value: $0.00", id="stat-value")

    def refresh_stats(self):
        if not self.watcher or not self.state:
            return
        elapsed = int(time.time() - self.watcher.start_time)
        h, m = divmod(elapsed // 60, 60)
        jobs = self.state.get_recent_jobs(limit=1000)
        found = len(jobs)
        accepted = sum(1 for j in jobs if j.get("accepted", False))
        total = sum(j.get("reward", 0) for j in jobs)

        self.query_one("#stat-duration", Static).update(f"Duration: {h}h {m:02d}m")
        self.query_one("#stat-found", Static).update(f"Found: {found}")
        self.query_one("#stat-accepted", Static).update(f"Accepted: {accepted}")
        self.query_one("#stat-value", Static).update(f"Value: ${total:.2f}")


class SourcesBreakdown(DashboardQuadrant):
    """Job source breakdown."""

    def __init__(self, state: "AppState", **kwargs):
        super().__init__("Sources", **kwargs)
        self.state = state

    def compose(self) -> ComposeResult:
        yield Static("WS: 0%\nEmail: 0%\nWeb: 0%\nRSS: 0%", id="sources-content")

    def refresh_sources(self):
        # ... logic ...
        pass


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
        yield TitleBar(config=self.config)

        # 2. Tabs
        with TabbedContent(initial="dashboard"):
            with TabPane("Dashboard", id="dashboard"):
                yield MetricsRow(state=self.state)
                yield StatusRow(watcher=self.watcher)

                # 2x2 Grid + Activity
                with Vertical(id="dashboard-content"):
                    with Container(classes="dashboard-grid"):
                        yield JobsPreview(state=self.state)
                        yield ChartPlaceholder()
                        yield ConfigPreview()  # Keep as bottom-right per doc
                        yield SessionStats(watcher=self.watcher, state=self.state)

                    yield ActivityPreview()

            with TabPane("Jobs", id="jobs"):
                yield DataTable(id="jobs-table-full")
            with TabPane("Activity", id="activity"):
                yield RichLog(id="activity-log-full", markup=True)
            with TabPane("Output", id="output"):
                yield RichLog(id="output-log", markup=True)
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
