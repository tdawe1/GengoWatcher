"""
Textual-based TUI for GengoWatcher.

Strict implementation of the v2.0 Design Doc.
"""

import datetime
import logging
import re
import time
from collections import deque
from typing import Any, ClassVar, cast

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


# Fractional block characters for bar chart rendering
# Characters arranged from empty to full: ▁▂▃▄▅▆▇█
BAR_CHARS = " ▁▂▃▄▅▆▇█"


def _render_chart(values: list[float], width: int = 20, height: int = 5) -> str:
    """
    Render a bar chart using fractional block characters.

    Args:
        values: List of numeric values to display
        width: Width of the chart in characters
        height: Height of the chart in lines

    Returns:
        String representation of the chart with newlines
    """
    if not values or width <= 0 or height <= 0:
        return ""

    # Normalize values to fit within the height
    max_val = max(values) if values else 1.0
    if max_val == 0:
        max_val = 1.0

    # Resample values to fit width if needed
    if len(values) > width:
        # Downsample by averaging buckets
        step = len(values) / width
        resampled = []
        for i in range(width):
            start_idx = int(i * step)
            end_idx = int((i + 1) * step)
            bucket = values[start_idx:end_idx]
            resampled.append(sum(bucket) / len(bucket) if bucket else 0)
        values = resampled
    elif len(values) < width:
        # Pad with zeros on the right
        values = list(values) + [0.0] * (width - len(values))

    # Normalize to chart height (using fractional blocks)
    # Each position can be 0 to (height * 8) where 8 is the number of fractional states
    max_units = height * 8
    normalized = [(v / max_val) * max_units for v in values]

    # Build chart from top to bottom
    lines = []
    for row in range(height - 1, -1, -1):
        line = ""
        for col_val in normalized:
            # Determine which character to use for this row
            # row represents height from bottom (0 = bottom row, height-1 = top row)
            units_at_col = col_val
            units_needed_for_row = row * 8

            if units_at_col > units_needed_for_row + 8:
                # Full block for this row
                line += BAR_CHARS[-1]  # █
            elif units_at_col > units_needed_for_row:
                # Partial block for this row
                fraction = int(units_at_col - units_needed_for_row)
                line += BAR_CHARS[min(fraction, len(BAR_CHARS) - 1)]
            else:
                # Empty for this row
                line += BAR_CHARS[0]  # space
        lines.append(line)

    return "\n".join(lines)


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
        "level_debug": "#727169",  # Fuji Gray
        "level_info": "#DCD7BA",  # Fuji White
        "level_warning": "#E6C384",  # Carp Yellow
        "level_error": "#C34043",  # Samurai Red
        "level_success": "#98BB6C",  # Spring Green
        "level_job": "#7E9CD8",  # Crystal Blue
    }

    # Mapping of level names to color keys
    LEVEL_COLORS = {
        "debug": "level_debug",
        "info": "level_info",
        "warning": "level_warning",
        "error": "level_error",
        "success": "level_success",
        "job": "level_job",
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
        color_key = self.LEVEL_COLORS.get(level, "default")
        base_color = self.COLORS[color_key]

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
        """
        Refresh the jobs preview table from the current application state.

        Populates the jobs DataTable with up to 10 most recent jobs from state, showing a truncated job ID (first 8 chars), language pair, word count and formatted reward. If the state is unavailable the method returns immediately. If the table widget is not mounted yet, the method quietly does nothing.
        """
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


class HourlyActivity(DashboardQuadrant):
    """Hourly activity stats with peak hour highlighting."""

    def __init__(self, stats: "StatsManager", **kwargs):
        super().__init__("Jobs/Hour", **kwargs)
        self.stats = stats

    def compose(self) -> ComposeResult:
        yield Static("No activity data", id="hourly-content")

    def on_mount(self) -> None:
        """Initialize widget with current data."""
        self.refresh_hourly()

    def refresh_hourly(self):
        """Refresh hourly activity display."""
        if not self.stats:
            return
        try:
            # Get peak hour info - unpacking both values as per fix
            peak_hour, peak_rate = self.stats.get_peak_hour()

            # FIX: Only treat as valid peak if peak_rate > 0
            # This prevents highlighting "12-15" period with zero activity
            if peak_rate > 0:
                # Valid peak hour with actual activity
                peak_period_start = (peak_hour // 3) * 3
                peak_period_end = peak_period_start + 3
                peak_period = f"{peak_period_start:02d}-{peak_period_end:02d}"

                content = f"Peak: {peak_period}\nJobs: {int(peak_rate)}"
            else:
                # No activity - don't highlight any period
                content = "No activity yet"

            self.query_one("#hourly-content", Static).update(content)
        except Exception:
            pass  # Widget not mounted yet


class ConfigPreview(DashboardQuadrant):
    """Configuration preview showing all config.ini options."""

    # Keys that should be masked for security
    SENSITIVE_KEYS: ClassVar[set[str]] = {
        "user_session",
        "user_key",
        "client_id",
        "client_secret",
        "refresh_token",
        "access_token",
        "auth_token",
        "session_cookie",
        "password",
        "secret",
        "token",
    }

    # Section display order for configuration
    SECTION_ORDER: ClassVar[list[str]] = [
        "Watcher",
        "WebSocket",
        "EmailMonitor",
        "WebsiteMonitor",
        "AutoAccept",
        "HighValue",
        "Cancellation",
        "Network",
        "Paths",
        "Logging",
        "DebugCategories",
        "RateLimit",
        "WebServer",
    ]

    # Layout constants for _render_config
    SECTION_HEADER_WIDTH = 18
    MAX_VALUE_LENGTH = 20
    MAX_VALUE_LENGTH_SHORT = 17

    def __init__(self, config: "AppConfig", **kwargs):
        super().__init__("Configuration", **kwargs)
        self.config = config

    def compose(self) -> ComposeResult:
        yield Static(id="config-content", classes="config-display")

    def on_mount(self):
        """Populate config display on mount."""
        self.refresh_config()

    def refresh_config(self):
        """Refresh the configuration display."""
        if not self.config:
            return
        try:
            content = self.query_one("#config-content", Static)
            config_text = self._render_config()
            content.update(config_text)
        except NoMatches:
            logging.getLogger(__name__).debug(
                "ConfigPreview.refresh_config: '#config-content' widget not found; skipping update."
            )

    def _is_sensitive(self, key: str) -> bool:
        """Check if a key contains sensitive information."""
        key_lower = key.lower()
        return any(s in key_lower for s in self.SENSITIVE_KEYS)

    def _mask_value(self, value: object) -> str:
        """Mask a sensitive value, showing only first/last chars."""
        if not value or len(str(value)) <= 4:
            return "****"
        val_str = str(value)
        return f"{val_str[:2]}...{val_str[-2:]}"

    def _format_value(self, key: str, value) -> str:
        """Format a config value for display."""
        if self._is_sensitive(key) and value:
            return self._mask_value(value)
        if isinstance(value, bool):
            return "✓" if value else "✗"
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        if isinstance(value, float):
            return f"{value:.2f}" if value != int(value) else str(int(value))
        if value is None or value == "":
            return "—"
        return str(value)

    def _render_config(self) -> Text:
        """Render all config sections and options."""
        text = Text()
        config = getattr(self, "config", None)
        list_all = getattr(config, "list_all", None)
        if not callable(list_all):
            # Gracefully handle cases where config is a mock or non-AppConfig without list_all()
            return text
        all_config = cast(dict[str, dict[str, Any]], list_all())

        for section in self.SECTION_ORDER:
            if section not in all_config:
                continue
            options = all_config[section]
            if not options:
                continue

            # Section header
            text.append(f"─ {section} ", style="bold #7E9CD8")
            text.append(
                "─" * max(1, self.SECTION_HEADER_WIDTH - len(section)), style="#727169"
            )
            text.append("\n")

            # Options
            for key, value in options.items():
                formatted_value = self._format_value(key, value)
                # Truncate long values
                if len(formatted_value) > self.MAX_VALUE_LENGTH:
                    formatted_value = (
                        formatted_value[: self.MAX_VALUE_LENGTH_SHORT] + "..."
                    )

                # Key styling
                text.append(f"  {key}: ", style="#727169")

                # Value styling based on type/content
                if self._is_sensitive(key):
                    text.append(formatted_value, style="#957FB8")
                elif isinstance(value, bool):
                    text.append(
                        formatted_value, style="#98BB6C" if value else "#C34043"
                    )
                elif isinstance(value, (int, float)):
                    text.append(formatted_value, style="#D27E99")
                else:
                    text.append(formatted_value, style="#DCD7BA")
                text.append("\n")

        return text


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
        """
        Builds and yields the application's main UI layout: title bar, tabbed content (Dashboard, Jobs, Activity, Output, Charts, Stats), and the bottom input and footer.

        Returns:
            ComposeResult: A result that yields the top TitleBar, the TabbedContent with dashboard panels and other tab panes, and the bottom Input and Footer widgets.
        """
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
                        yield HourlyActivity(stats=self.stats)
                        yield ConfigPreview(config=self.config)
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

    # Mapping of logging levels to color keys
    LEVEL_COLORS = {
        logging.DEBUG: "level_debug",
        logging.INFO: "level_info",
        logging.WARNING: "level_warning",
        logging.ERROR: "level_error",
        logging.CRITICAL: "level_critical",
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
        try:
            log = self.app.query_one("#activity-log", RichLog)
            colored_text = self._colorize_message(msg, level)
            log.write(colored_text)
        except NoMatches:
            pass  # Widget not mounted yet

    def _colorize_message(self, msg: str, level: int) -> Text:
        """Apply Rich markup coloring based on content patterns."""
        # Determine base color from log level
        color_key = self.LEVEL_COLORS.get(level, "level_info")
        base_color = self.COLORS[color_key]

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
