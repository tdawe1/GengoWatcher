"""
Textual-based TUI for GengoWatcher.

Strict implementation of the v2.0 Design Doc.
"""

import datetime
import logging
import re
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
from textual.css.query import NoMatches
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

    def __init__(self, config: AppConfig | None = None, **kwargs):
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
        except NoMatches:
            pass  # Widget not mounted yet

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
            except NoMatches:
                pass  # Widget not mounted yet


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
        except NoMatches:
            pass  # Widget not mounted yet


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

        # Rate calculation using session duration
        session_start = getattr(self.state, "session_start", None)
        if session_start:
            elapsed_hours = max((time.time() - session_start) / 3600, 0.01)
        else:
            elapsed_hours = 1.0  # Default to 1 hour if no session start
        rate = found / elapsed_hours

        self.query_one("#card-found", MetricCard).update_value(str(found))
        self.query_one("#card-accepted", MetricCard).update_value(str(accepted))
        self.query_one("#card-value", MetricCard).update_value(f"${total_value:.2f}")
        self.query_one("#card-rate", MetricCard).update_value(f"{rate:.1f}/hr")
        self.query_one("#card-today", MetricCard).update_value(f"${total_value:.2f}")


class StatusIndicator(Static):
    """Status indicator with dynamic icon and color based on state."""

    # Icons for different states
    ICONS = {
        "idle": "○",  # Empty circle
        "live": "●",  # Filled circle (will pulse)
        "working": "◐",  # Half circle (activity)
        "error": "✗",  # X mark
    }

    # Pulse animation frames for live state
    PULSE_FRAMES = ["●", "◉", "○", "◉"]

    def __init__(self, base_icon: str, name: str, **kwargs):
        super().__init__(**kwargs)
        self.base_icon = base_icon
        self.label_text = name
        self.current_state = "idle"
        self._pulse_index = 0
        self.add_class("status-indicator")
        self.add_class("status-idle")

    def compose(self) -> ComposeResult:
        yield Static(
            f"{self.ICONS['idle']} {self.label_text}",
            classes="status-label",
            id=f"{self.id}-label",
        )

    def on_mount(self) -> None:
        """Start the pulse animation timer."""
        self.set_interval(0.5, self._pulse_tick)

    def _pulse_tick(self) -> None:
        """Update pulse animation for live indicators."""
        if self.current_state == "live":
            self._pulse_index = (self._pulse_index + 1) % len(self.PULSE_FRAMES)
            self._update_display()

    def _update_display(self) -> None:
        """Update the displayed icon based on current state."""
        try:
            label = self.query_one(f"#{self.id}-label", Static)
            if self.current_state == "live":
                icon = self.PULSE_FRAMES[self._pulse_index]
            elif self.current_state == "working":
                # Rotate through working icons
                working_frames = ["◐", "◓", "◑", "◒"]
                self._pulse_index = (self._pulse_index + 1) % len(working_frames)
                icon = working_frames[self._pulse_index]
            else:
                icon = self.ICONS.get(self.current_state, self.base_icon)
            label.update(f"{icon} {self.label_text}")
        except NoMatches:
            pass

    def set_state(self, state: str) -> None:
        """Set the indicator state and update styling."""
        old_state = self.current_state
        self.current_state = state

        # Update CSS classes
        for s in ("live", "working", "idle", "error"):
            self.remove_class(f"status-{s}")
        self.add_class(f"status-{state}")

        # Reset pulse index when state changes
        if old_state != state:
            self._pulse_index = 0
            self._update_display()


class StatusRow(Horizontal):
    """Dedicated row of status indicators with live updates."""

    def __init__(self, watcher: "GengoWatcher", **kwargs):
        super().__init__(**kwargs)
        self.watcher = watcher

    def on_mount(self) -> None:
        """Start periodic status refresh."""
        self.set_interval(1.0, self.refresh_status)

    def compose(self) -> ComposeResult:
        # 7 Indicators - reordered: WS, RSS next to each other, then Mail, Web, Captcha, Workflow, Auto
        yield StatusIndicator("●", "WS", id="ind-ws")
        yield StatusIndicator("⊛", "RSS", id="ind-rss")
        yield StatusIndicator("◉", "Mail", id="ind-email")
        yield StatusIndicator("◎", "Web", id="ind-web")
        yield StatusIndicator("⧗", "Captcha", id="ind-cap")
        yield StatusIndicator("⇄", "Workflow", id="ind-work")
        yield StatusIndicator("▶", "Auto", id="ind-auto")

    def refresh_status(self) -> None:
        """Refresh all status indicators based on watcher state."""
        if not self.watcher:
            return

        try:
            # WebSocket status
            ws_status = getattr(self.watcher, "websocket_status", "")
            ws_connected = getattr(self.watcher, "websocket_connected", False)
            if ws_connected or ws_status == "Live":
                self.query_one("#ind-ws", StatusIndicator).set_state("live")
            elif ws_status in ("Connecting", "Reconnecting"):
                self.query_one("#ind-ws", StatusIndicator).set_state("working")
            elif "error" in ws_status.lower() if ws_status else False:
                self.query_one("#ind-ws", StatusIndicator).set_state("error")
            else:
                self.query_one("#ind-ws", StatusIndicator).set_state("idle")

            # Email monitor status
            email_status = getattr(self.watcher, "email_monitor_status", "")
            email_enabled = getattr(self.watcher, "_email_monitor", None) is not None
            if email_status == "Polling" or email_status == "Connected":
                self.query_one("#ind-email", StatusIndicator).set_state("live")
            elif email_status == "Checking":
                self.query_one("#ind-email", StatusIndicator).set_state("working")
            elif "error" in email_status.lower() if email_status else False:
                self.query_one("#ind-email", StatusIndicator).set_state("error")
            elif email_enabled:
                self.query_one("#ind-email", StatusIndicator).set_state("idle")
            else:
                self.query_one("#ind-email", StatusIndicator).set_state("idle")

            # Website monitor status
            web_enabled = getattr(self.watcher, "_website_monitor", None) is not None
            web_status = getattr(self.watcher, "website_monitor_status", "")
            if web_status == "Monitoring":
                self.query_one("#ind-web", StatusIndicator).set_state("live")
            elif web_status == "Checking":
                self.query_one("#ind-web", StatusIndicator).set_state("working")
            elif "error" in web_status.lower() if web_status else False:
                self.query_one("#ind-web", StatusIndicator).set_state("error")
            else:
                self.query_one("#ind-web", StatusIndicator).set_state("idle")

            # RSS status
            rss_action = getattr(self.watcher, "rss_action", "")
            if "Fetching" in rss_action or "Checking" in rss_action:
                self.query_one("#ind-rss", StatusIndicator).set_state("working")
            elif "error" in rss_action.lower() if rss_action else False:
                self.query_one("#ind-rss", StatusIndicator).set_state("error")
            elif rss_action:
                self.query_one("#ind-rss", StatusIndicator).set_state("live")
            else:
                self.query_one("#ind-rss", StatusIndicator).set_state("idle")

            # Captcha solver status - check if captcha solving is enabled in config
            # For now, this feature isn't implemented, so show as idle
            captcha_enabled = getattr(self.watcher, "captcha_enabled", False)
            captcha_solving = getattr(self.watcher, "captcha_solving", False)
            if captcha_solving:
                self.query_one("#ind-cap", StatusIndicator).set_state("working")
            elif captcha_enabled:
                self.query_one("#ind-cap", StatusIndicator).set_state("live")
            else:
                self.query_one("#ind-cap", StatusIndicator).set_state("idle")

            # Workflow/job processing - only show as working when actively processing
            is_processing = getattr(self.watcher, "is_processing", False)
            if is_processing:
                self.query_one("#ind-work", StatusIndicator).set_state("working")
            else:
                self.query_one("#ind-work", StatusIndicator).set_state("idle")

            # Auto-accept status
            auto_accept = getattr(self.watcher, "auto_accept_enabled", False)
            self.query_one("#ind-auto", StatusIndicator).set_state(
                "live" if auto_accept else "idle"
            )

        except NoMatches:
            pass  # Widgets not mounted yet
        except Exception:
            pass  # Swallow errors during refresh


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
    """Recent activity log with colored output."""

    # Kanagawa-inspired colors (same as TextualLogHandler)
    COLORS = {
        "timestamp": "#727169",  # Fuji Gray (muted)
        "job_id": "#7E9CD8",  # Crystal Blue
        "money": "#E6C384",  # Carp Yellow
        "lang_pair": "#957FB8",  # Oni Violet
        "number": "#D27E99",  # Sakura Pink
        "success": "#98BB6C",  # Spring Green
        "error_word": "#C34043",  # Samurai Red
        "warning_word": "#E6C384",  # Carp Yellow
        "source_ws": "#957FB8",  # Oni Violet
        "source_email": "#FFA066",  # Surimi Orange
        "source_rss": "#7AA89F",  # Wave Aqua
        "source_web": "#7E9CD8",  # Crystal Blue
        "url": "#7AA89F",  # Wave Aqua
        "default": "#DCD7BA",  # Fuji White
    }

    # Regex patterns for content types
    PATTERNS = [
        (r"\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\]?", "timestamp"),
        (r"\b\d{2}:\d{2}:\d{2}\b", "timestamp"),
        (r"#\d{4,}", "job_id"),
        (r"\bjob[_-]?\d+\b", "job_id"),
        (r"\bID:?\s*\d+\b", "job_id"),
        (r"[\$¥€£]\d{1,3}(?:,\d{3})*(?:\.\d{2})?", "money"),
        (r"\b[A-Z]{2}[→\->][A-Z]{2}\b", "lang_pair"),
        (r"https?://[^\s]+", "url"),
        (
            r"\b(?:found|accepted|success|connected|started|completed|ok|passed)\b",
            "success",
        ),
        (
            r"\b(?:error|failed|failure|exception|crash|rejected|timeout|denied)\b",
            "error_word",
        ),
        (r"\b(?:warning|warn|caution|retry|retrying|slow|delayed)\b", "warning_word"),
        (r"\b(?:websocket|ws|socket)\b", "source_ws"),
        (r"\b(?:email|imap|mail)\b", "source_email"),
        (r"\b(?:rss|feed)\b", "source_rss"),
        (r"\b(?:web|http|browser|scrape)\b", "source_web"),
        (r"\b\d+(?:\.\d+)?\b", "number"),
    ]

    def __init__(self, **kwargs):
        super().__init__("Recent Activity", **kwargs)
        # Compile patterns
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), color_key)
            for pattern, color_key in self.PATTERNS
        ]

    def compose(self) -> ComposeResult:
        # Just yield content, border_title handles the header
        yield RichLog(id="activity-log", markup=True)

    def add_line(self, message: str, level: str = "info") -> None:
        """Add a colored line to the activity log.

        Args:
            message: The message to display
            level: One of 'info', 'warning', 'error', 'debug', 'success', 'job'
        """
        try:
            log = self.query_one("#activity-log", RichLog)
            colored_text = self._colorize_message(message, level)
            log.write(colored_text)
        except NoMatches:
            pass  # Widget not mounted yet

    def _colorize_message(self, msg: str, level: str = "info") -> Text:
        """Apply Rich markup coloring based on content patterns."""
        # Determine base color from level
        level_colors = {
            "debug": "#727169",
            "info": "#DCD7BA",
            "warning": "#E6C384",
            "error": "#C34043",
            "success": "#98BB6C",
            "job": "#7E9CD8",
        }
        base_color = level_colors.get(level, self.COLORS["default"])

        # Create text with base styling
        text = Text(msg, style=base_color)

        # Apply pattern-based highlighting
        for pattern, color_key in self._compiled_patterns:
            color = self.COLORS.get(color_key, base_color)
            for match in pattern.finditer(msg):
                start, end = match.span()
                # Apply bold for important items
                if color_key in ("job_id", "money", "success", "error_word"):
                    text.stylize(f"bold {color}", start, end)
                else:
                    text.stylize(color, start, end)

        return text


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
        except NoMatches:
            pass  # Widget not mounted yet

    def refresh_jobs(self):
        """Refresh jobs table with recent jobs from state."""
        if not self.state:
            return
        try:
            dt = self.query_one(DataTable)
            dt.clear()
            jobs = self.state.get_recent_jobs(limit=10)
            for job in jobs:
                job_id = str(job.get("id", "N/A"))[:8]
                pair = job.get("lang_pair", "??→??")
                words = str(job.get("word_count", job.get("words", 0)))
                reward = f"${job.get('reward', 0):.2f}"
                dt.add_row(job_id, pair, words, reward)
        except NoMatches:
            pass  # Widget not mounted yet


class JobsHourChart(DashboardQuadrant):
    """ASCII bar chart showing jobs per hour distribution."""

    # Bar characters for different fill levels
    BAR_CHARS = "▏▎▍▌▋▊▉█"
    MAX_BAR_WIDTH = 12  # Maximum bar width in characters

    def __init__(self, stats: "StatsManager | None" = None, **kwargs):
        super().__init__("Jobs/Hour", **kwargs)
        self.stats = stats

    def compose(self) -> ComposeResult:
        yield Static(id="chart-content", classes="chart-ascii")

    def on_mount(self):
        self.refresh_chart()

    def refresh_chart(self):
        """Refresh the chart with current hourly data."""
        try:
            content = self.query_one("#chart-content", Static)
            chart_text = self._render_chart()
            content.update(chart_text)
        except NoMatches:
            pass  # Widget not mounted yet

    def _render_chart(self) -> Text:
        """Render ASCII bar chart for hourly job distribution."""
        text = Text()

        # Get hourly counts from stats or use empty data
        if self.stats:
            hourly = dict(self.stats.hourly_counts)
            peak_hour, _ = self.stats.get_peak_hour()
        else:
            hourly = {}
            peak_hour = -1

        # Find max value for scaling
        max_count = max(hourly.values()) if hourly else 1

        # Show 6 time periods (4-hour blocks) to fit in quadrant
        periods = [
            ("00-03", range(0, 4)),
            ("04-07", range(4, 8)),
            ("08-11", range(8, 12)),
            ("12-15", range(12, 16)),
            ("16-19", range(16, 20)),
            ("20-23", range(20, 24)),
        ]

        for label, hours in periods:
            # Sum jobs in this period
            period_count = sum(hourly.get(h, 0) for h in hours)
            # Check if peak hour is in this period
            is_peak = peak_hour in hours

            # Calculate bar width
            if max_count > 0:
                bar_width = int((period_count / max_count) * self.MAX_BAR_WIDTH)
            else:
                bar_width = 0

            # Build the bar
            full_blocks = bar_width
            bar = "█" * full_blocks

            # Pad to consistent width
            bar_padded = bar.ljust(self.MAX_BAR_WIDTH, "░")

            # Format: "00-03 ████████░░░░ 12"
            count_str = f"{period_count:3d}" if period_count > 0 else "  0"

            # Add label
            text.append(f"{label} ", style="#737c73")  # Dragon Gray

            # Add bar with appropriate color
            if is_peak and period_count > 0:
                text.append(bar_padded, style="bold #8ba4b0")  # Dragon Blue (peak)
            elif period_count > 0:
                text.append(bar_padded, style="#8a9a7b")  # Dragon Green
            else:
                text.append(bar_padded, style="#393836")  # Dragon Black 5 (empty)

            # Add count
            if is_peak and period_count > 0:
                text.append(f" {count_str}", style="bold #8ba4b0")
            else:
                text.append(f" {count_str}", style="#737c73")

            text.append("\n")

        return text


# Keep for backwards compatibility
ChartPlaceholder = JobsHourChart


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
        """Refresh sources breakdown with job source statistics."""
        if not self.state:
            return
        try:
            jobs = self.state.get_recent_jobs(limit=1000)
            total = len(jobs) if jobs else 1  # Avoid division by zero

            # Count jobs by source
            ws_count = sum(1 for j in jobs if j.get("source") == "websocket")
            email_count = sum(1 for j in jobs if j.get("source") == "email")
            web_count = sum(1 for j in jobs if j.get("source") == "web")
            rss_count = sum(1 for j in jobs if j.get("source") == "rss")

            # Calculate percentages
            ws_pct = (ws_count / total) * 100 if total > 0 else 0
            email_pct = (email_count / total) * 100 if total > 0 else 0
            web_pct = (web_count / total) * 100 if total > 0 else 0
            rss_pct = (rss_count / total) * 100 if total > 0 else 0

            content = f"WS: {ws_pct:.0f}%\nEmail: {email_pct:.0f}%\nWeb: {web_pct:.0f}%\nRSS: {rss_pct:.0f}%"
            self.query_one("#sources-content", Static).update(content)
        except NoMatches:
            pass  # Widget not mounted yet


class StatsPanel(Static):
    """Full statistics panel for the Stats tab."""

    def __init__(self, stats: "StatsManager", **kwargs):
        super().__init__(**kwargs)
        self.stats = stats

    def on_mount(self):
        """Initialize stats display."""
        self.refresh_stats()

    def compose(self) -> ComposeResult:
        with Vertical():
            # Session Stats Section
            yield Static("── Session Stats ──", classes="stats-section-header")
            yield Static(
                "Jobs Found: 0\nAccepted: 0\nValue: $0.00", id="stats-session-content"
            )

            # All-Time Stats Section
            yield Static("── All-Time Stats ──", classes="stats-section-header")
            yield Static(
                "Total Jobs: 0\nTotal Accepted: 0\nTotal Value: $0.00",
                id="stats-alltime-content",
            )

    def refresh_stats(self):
        """Refresh stats display with current data."""
        if not self.stats:
            return
        try:
            # Session stats (from self.stats.session dataclass)
            session = self.stats.session
            session_text = (
                f"Jobs Found: {session.jobs_found}\n"
                f"Accepted: {session.jobs_accepted}\n"
                f"Value: ${session.total_value:.2f}"
            )
            self.query_one("#stats-session-content", Static).update(session_text)

            # All-time stats (from self.stats.all_time dataclass)
            alltime = self.stats.all_time
            alltime_text = (
                f"Total Jobs: {alltime.total_jobs}\n"
                f"Total Accepted: {alltime.total_sessions}\n"
                f"Total Value: ${alltime.total_value:.2f}"
            )
            self.query_one("#stats-alltime-content", Static).update(alltime_text)
        except NoMatches:
            pass  # Widget not mounted yet


class JobsPanel(Static):
    """Full jobs panel for the Jobs tab with detailed job listing."""

    def __init__(self, state: "AppState", **kwargs):
        super().__init__(**kwargs)
        self.state = state

    def on_mount(self):
        """Initialize the jobs table with columns."""
        try:
            dt = self.query_one("#jobs-table-full", DataTable)
            dt.add_columns(
                "ID", "Lang Pair", "Words", "Reward", "Source", "Status", "Time"
            )
            dt.cursor_type = "row"
        except NoMatches:
            pass
        self.refresh_jobs()

    def compose(self) -> ComposeResult:
        yield DataTable(id="jobs-table-full")

    def refresh_jobs(self):
        """Refresh the full jobs table with all recent jobs."""
        if not self.state:
            return
        try:
            dt = self.query_one("#jobs-table-full", DataTable)
            dt.clear()
            jobs = self.state.get_recent_jobs(limit=100)
            for job in jobs:
                job_id = str(job.get("id", "N/A"))[:12]
                pair = job.get("lang_pair", "??→??")
                words = str(job.get("word_count", job.get("words", 0)))
                reward = f"${job.get('reward', 0):.2f}"
                source = job.get("source", "unknown")
                status = "✓" if job.get("accepted", False) else "○"
                timestamp = job.get("timestamp", job.get("found_at", ""))
                if isinstance(timestamp, (int, float)):
                    timestamp = datetime.datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')
                elif isinstance(timestamp, str):
                    # Extract just the time portion if it's a full timestamp
                    if "T" in timestamp:
                        timestamp = timestamp.split("T")[1][:8]
                    elif " " in timestamp:
                        timestamp = timestamp.split(" ")[1][:8]
                    else:
                        timestamp = timestamp[:8]
                else:
                    timestamp = ""
                dt.add_row(job_id, pair, words, reward, source, status, timestamp)
        except NoMatches:
            pass  # Widget not mounted yet


class ChartsPanel(Static):
    """Charts panel showing various job statistics visualizations."""

    def __init__(self, stats: "StatsManager", state: "AppState", **kwargs):
        super().__init__(**kwargs)
        self.stats = stats
        self.state = state

    def on_mount(self):
        """Initialize charts display."""
        self.refresh_charts()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("── Jobs by Hour ──", classes="chart-section-header")
            yield Static(id="chart-hourly", classes="chart-ascii")
            yield Static("── Jobs by Source ──", classes="chart-section-header")
            yield Static(id="chart-sources", classes="chart-ascii")
            yield Static("── Value Trend ──", classes="chart-section-header")
            yield Static(id="chart-value", classes="chart-ascii")

    def refresh_charts(self):
        """Refresh all charts with current data."""
        try:
            # Hourly chart
            hourly_text = self._render_hourly_chart()
            self.query_one("#chart-hourly", Static).update(hourly_text)

            # Sources chart
            sources_text = self._render_sources_chart()
            self.query_one("#chart-sources", Static).update(sources_text)

            # Value trend
            value_text = self._render_value_trend()
            self.query_one("#chart-value", Static).update(value_text)
        except NoMatches:
            pass

    def _render_hourly_chart(self) -> Text:
        """Render hourly job distribution chart."""
        text = Text()
        if self.stats:
            hourly = dict(self.stats.hourly_counts)
            max_count = max(hourly.values()) if hourly else 1
        else:
            hourly = {}
            max_count = 1

        for hour in range(24):
            count = hourly.get(hour, 0)
            bar_width = int((count / max_count) * 20) if max_count > 0 else 0
            bar = "█" * bar_width
            bar_padded = bar.ljust(20, "░")
            text.append(f"{hour:02d}:00 ", style="#737c73")
            text.append(bar_padded, style="#8a9a7b" if count > 0 else "#393836")
            text.append(f" {count:3d}\n", style="#737c73")
        return text

    def _render_sources_chart(self) -> Text:
        """Render job sources distribution chart."""
        text = Text()
        if not self.state:
            text.append("No data available")
            return text

        jobs = self.state.get_recent_jobs(limit=1000)
        total = len(jobs) if jobs else 1

        sources = {"websocket": 0, "email": 0, "web": 0, "rss": 0, "unknown": 0}
        for job in jobs:
            src = job.get("source", "unknown")
            if src in sources:
                sources[src] += 1
            else:
                sources["unknown"] += 1

        max_count = max(sources.values()) if sources else 1
        colors = {
            "websocket": "#957FB8",
            "email": "#FFA066",
            "web": "#7E9CD8",
            "rss": "#7AA89F",
            "unknown": "#727169",
        }

        for source, count in sources.items():
            pct = (count / total) * 100 if total > 0 else 0
            bar_width = int((count / max_count) * 15) if max_count > 0 else 0
            bar = "█" * bar_width
            bar_padded = bar.ljust(15, "░")
            text.append(f"{source:10s} ", style="#737c73")
            text.append(
                bar_padded,
                style=colors.get(source, "#727169") if count > 0 else "#393836",
            )
            text.append(f" {count:4d} ({pct:5.1f}%)\n", style="#737c73")
        return text

    def _render_value_trend(self) -> Text:
        """Render value accumulation trend."""
        text = Text()
        if not self.state:
            text.append("No data available")
            return text

        jobs = self.state.get_recent_jobs(limit=50)
        if not jobs:
            text.append("No jobs recorded yet")
            return text

        # Calculate cumulative value over last N jobs
        cumulative = 0
        values = []
        for job in reversed(jobs[:20]):  # Last 20 jobs
            cumulative += job.get("reward", 0)
            values.append(cumulative)

        if not values:
            text.append("No value data")
            return text

        max_val = max(values) if values else 1
        for i, val in enumerate(values):
            bar_width = int((val / max_val) * 25) if max_val > 0 else 0
            bar = "▓" * bar_width
            bar_padded = bar.ljust(25, "░")
            text.append(f"{i + 1:2d} ", style="#737c73")
            text.append(bar_padded, style="#E6C384")
            text.append(f" ${val:.2f}\n", style="#E6C384")
        return text


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

        # Register callback for when new jobs are detected
        self.watcher.on_job_added_callback = self._on_job_added_from_thread

    def _on_job_added_from_thread(self, job_data: dict):
        """Called from watcher thread when a new job is added."""
        # Use call_from_thread to safely update UI from watcher thread
        self.call_from_thread(self._refresh_all_panels)

    def _refresh_all_panels(self):
        """Refresh all data panels when a new job is detected."""
        try:
            # Dashboard widgets
            self.query_one(MetricsRow).refresh_metrics()
            self.query_one(JobsPreview).refresh_jobs()
            self.query_one(JobsHourChart).refresh_chart()
            self.query_one(SessionStats).refresh_stats()
        except NoMatches:
            pass

        try:
            # Tab panels
            self.query_one(JobsPanel).refresh_jobs()
            self.query_one(ChartsPanel).refresh_charts()
            self.query_one(StatsPanel).refresh_stats()
        except NoMatches:
            pass

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
                        yield JobsHourChart(stats=self.stats)
                        yield ConfigPreview()  # Keep as bottom-right per doc
                        yield SessionStats(watcher=self.watcher, state=self.state)

                    yield ActivityPreview()

            with TabPane("Jobs", id="jobs"):
                yield JobsPanel(state=self.state)
            with TabPane("Activity", id="activity"):
                yield RichLog(id="activity-log-full", markup=True)
            with TabPane("Output", id="output"):
                yield RichLog(id="output-log", markup=True)
            with TabPane("Charts", id="charts"):
                yield ChartsPanel(stats=self.stats, state=self.state)
            with TabPane("Stats", id="stats"):
                yield StatsPanel(stats=self.stats)

        # 3. Input & Footer
        yield Input(placeholder="> help_")
        yield Footer()

    def call_from_thread(self, func, *args, **kwargs):
        # The base App.call_from_thread will be used, but we need to ensure we don't block
        super().call_from_thread(func, *args, **kwargs)


class TextualLogHandler(logging.Handler):
    """Redirects logs to the ActivityPreview widget with Rich markup coloring."""

    # Kanagawa-inspired colors
    COLORS = {
        "timestamp": "#727169",  # Fuji Gray (muted)
        "level_debug": "#727169",  # Fuji Gray
        "level_info": "#DCD7BA",  # Fuji White (default)
        "level_warning": "#E6C384",  # Carp Yellow
        "level_error": "#C34043",  # Samurai Red
        "level_critical": "#FF5D62",  # Peach Red
        "job_id": "#7E9CD8",  # Crystal Blue
        "money": "#E6C384",  # Carp Yellow
        "lang_pair": "#957FB8",  # Oni Violet
        "number": "#D27E99",  # Sakura Pink
        "success": "#98BB6C",  # Spring Green
        "error_word": "#C34043",  # Samurai Red
        "warning_word": "#E6C384",  # Carp Yellow
        "source_ws": "#957FB8",  # Oni Violet
        "source_email": "#FFA066",  # Surimi Orange
        "source_rss": "#7AA89F",  # Wave Aqua
        "source_web": "#7E9CD8",  # Crystal Blue
        "url": "#7AA89F",  # Wave Aqua
        "bracket": "#727169",  # Fuji Gray
        "punctuation": "#727169",  # Fuji Gray
    }

    # Regex patterns for different content types
    PATTERNS = [
        # Timestamps: [2024-01-15 12:34:56] or 2024-01-15 12:34:56
        (r"\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\]?", "timestamp"),
        # Time only: 12:34:56
        (r"\b\d{2}:\d{2}:\d{2}\b", "timestamp"),
        # Job IDs: #123456, job_123456, ID: 123456
        (r"#\d{4,}", "job_id"),
        (r"\bjob[_-]?\d+\b", "job_id"),
        (r"\bID:?\s*\d+\b", "job_id"),
        # Money: $12.34, $1,234.56, ¥1234
        (r"[\$¥€£]\d{1,3}(?:,\d{3})*(?:\.\d{2})?", "money"),
        (r"\b\d+\.\d{2}\s*(?:USD|JPY|EUR)\b", "money"),
        # Language pairs: JA→EN, EN-JA, Japanese→English
        (r"\b[A-Z]{2}[→\->][A-Z]{2}\b", "lang_pair"),
        (
            r"\b(?:Japanese|English|Chinese|Korean|German|French|Spanish)[→\->](?:Japanese|English|Chinese|Korean|German|French|Spanish)\b",
            "lang_pair",
        ),
        # URLs
        (r"https?://[^\s]+", "url"),
        # Success words
        (
            r"\b(?:found|accepted|success|connected|started|completed|ok|passed)\b",
            "success",
        ),
        # Error words
        (
            r"\b(?:error|failed|failure|exception|crash|rejected|timeout|denied)\b",
            "error_word",
        ),
        # Warning words
        (r"\b(?:warning|warn|caution|retry|retrying|slow|delayed)\b", "warning_word"),
        # Source indicators
        (r"\b(?:websocket|ws|socket)\b", "source_ws"),
        (r"\b(?:email|imap|mail)\b", "source_email"),
        (r"\b(?:rss|feed)\b", "source_rss"),
        (r"\b(?:web|http|browser|scrape)\b", "source_web"),
        # Numbers (but not part of other patterns)
        (r"\b\d+(?:\.\d+)?\b", "number"),
    ]

    def __init__(self, app):
        super().__init__()
        self.app = app
        # Compile patterns
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), color_key)
            for pattern, color_key in self.PATTERNS
        ]

    def emit(self, record):
        try:
            msg = self.format(record)
            level = record.levelno
            self.app.call_from_thread(self.write_log, msg, level)
        except Exception:
            pass  # Logging failures should not crash the app

    def write_log(self, msg: str, level: int = logging.INFO):
        colored_text = self._colorize_message(msg, level)
        # Write to dashboard activity log
        try:
            log = self.app.query_one("#activity-log", RichLog)
            log.write(colored_text)
        except NoMatches:
            pass  # Widget not mounted yet
        # Also write to full activity log tab
        try:
            log_full = self.app.query_one("#activity-log-full", RichLog)
            log_full.write(colored_text)
        except NoMatches:
            pass  # Widget not mounted yet
        # Also write to output log for system output
        if level >= logging.WARNING:
            try:
                output_log = self.app.query_one("#output-log", RichLog)
                output_log.write(colored_text)
            except NoMatches:
                pass  # Widget not mounted yet

    def _colorize_message(self, msg: str, level: int) -> Text:
        """Apply Rich markup coloring based on content patterns."""
        # Determine base color from log level
        level_colors = {
            logging.DEBUG: self.COLORS["level_debug"],
            logging.INFO: self.COLORS["level_info"],
            logging.WARNING: self.COLORS["level_warning"],
            logging.ERROR: self.COLORS["level_error"],
            logging.CRITICAL: self.COLORS["level_critical"],
        }
        base_color = level_colors.get(level, self.COLORS["level_info"])

        # Create text with base styling
        text = Text(msg, style=base_color)

        # Apply pattern-based highlighting
        for pattern, color_key in self._compiled_patterns:
            color = self.COLORS.get(color_key, base_color)
            for match in pattern.finditer(msg):
                start, end = match.span()
                # Apply bold for important items
                if color_key in ("job_id", "money", "success", "error_word"):
                    text.stylize(f"bold {color}", start, end)
                else:
                    text.stylize(color, start, end)

        # Style brackets and punctuation
        for match in re.finditer(r"[\[\](){}:,]", msg):
            start, end = match.span()
            text.stylize(self.COLORS["bracket"], start, end)

        return text
