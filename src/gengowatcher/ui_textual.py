"""
Textual-based TUI for GengoWatcher.

Strict implementation of the v2.0 Design Doc.
"""

import datetime
import logging
import re
import shlex
import socket
import sys
import threading
import time
from typing import Any, ClassVar, cast

from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import (
    DataTable,
    Footer,
    Input,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from .config import AppConfig
from .logging_setup import UILoggingHandler
from .state import AppState
from .stats import StatsManager
from .ui_charts import (
    BAR_CHARS,
    aggregate_series as _aggregate_series,
    render_chart as _render_chart,
    render_chart_with_axes as _render_chart_with_axes,
    render_plotext_bar_chart as _render_plotext_bar_chart,
)
from .ui_formatting import (
    ACTIVITY_LOG_MAX_LINES,
    ACTIVITY_PREVIEW_MAX_LINES,
    OUTPUT_LOG_MAX_LINES,
    SOURCE_BUCKET_CONFIG,
    TELEMETRY_LABELS,
    Icons,
    build_config_style_palette as _build_config_style_palette,
    build_semantic_color_palette as _build_semantic_color_palette,
    coerce_positive_int as _coerce_positive_int,
    derive_display_word_count as _derive_display_word_count,
    format_telemetry_metric as _format_telemetry_metric,
    format_timestamp as _format_timestamp,
    get_active_theme as _get_active_theme,
    iter_telemetry_entries as _iter_telemetry_entries,
    normalize_source as _normalize_source,
    parse_job_title_fallback as _parse_job_title_fallback,
    with_timestamp_prefix as _with_timestamp_prefix,
)
from .watcher import GengoWatcher

# =============================================================================
# Widgets
# =============================================================================

JOBS_PREVIEW_COLUMNS = ("ID", "Pair", "Words", "$$$", "Left")
JOBS_FULL_COLUMNS = (
    "ID",
    "Lang Pair",
    "Words",
    "Reward",
    "Source",
    "Status",
    "Left",
    "Time",
    "Order",
    "Workbench",
    "Text",
    "Segs",
)


def _format_duration_seconds(value: object) -> str:
    try:
        seconds = max(0, int(float(str(value))))
    except (TypeError, ValueError):
        return ""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s"


def _format_job_time_left(job: dict[str, Any]) -> str:
    if job.get("accepted_expired"):
        return "expired"
    accepted_time_left = str(job.get("accepted_time_left") or "").strip()
    if accepted_time_left:
        return accepted_time_left
    for key in ("seconds_left", "accepted_seconds_left"):
        formatted = _format_duration_seconds(job.get(key))
        if formatted:
            return formatted
    return ""


def _format_job_status(job: dict[str, Any]) -> str:
    if job.get("accepted", False):
        return "✓"
    state = str(job.get("acceptance_state") or job.get("lifecycle_state") or "").strip()
    if state:
        return state[:12]
    return "○"


def _format_job_order(job: dict[str, Any]) -> str:
    for key in ("order_id", "accepted_order_id"):
        value = job.get(key)
        if value not in (None, ""):
            return str(value)[:12]
    return ""


def _format_workbench_marker(job: dict[str, Any]) -> str:
    if job.get("workbench_visible"):
        return "visible"
    if job.get("workbench_url"):
        return "url"
    if job.get("workbench_payload") or job.get("accepted_workbench"):
        return "data"
    return ""


def _format_text_count(job: dict[str, Any]) -> str:
    for key in ("source_char_count", "accepted_source_char_count"):
        value = _coerce_positive_int(job.get(key))
        if value > 0:
            return f"{value}c"
    text = str(job.get("source_text") or job.get("accepted_source_text") or "")
    return f"{len(text)}c" if text else ""


def _format_segment_count(job: dict[str, Any]) -> str:
    for key in ("segment_count", "accepted_segment_count"):
        value = _coerce_positive_int(job.get(key))
        if value > 0:
            return str(value)
    segments = job.get("segments") or job.get("accepted_segments")
    if isinstance(segments, list) and segments:
        return str(len(segments))
    return ""


def _data_table_column_labels(dt: DataTable) -> tuple[str, ...]:
    labels: list[str] = []
    for column in dt.columns.values():
        label = getattr(column, "label", "")
        labels.append(str(getattr(label, "plain", label)))
    return tuple(labels)


def _ensure_data_table_columns(dt: DataTable, columns: tuple[str, ...]) -> None:
    if _data_table_column_labels(dt) == columns:
        return
    dt.clear(columns=True)
    dt.add_columns(*columns)


def _config_value(config: object, section: str, key: str, fallback: object = None):
    getter = getattr(config, "get", None)
    if not callable(getter):
        return fallback
    try:
        value = getter(section, key, fallback=fallback)
    except TypeError:
        try:
            value = getter(section, key)
        except Exception:
            return fallback
    except Exception:
        return fallback
    if isinstance(value, (str, int, float, bool, list, tuple, dict)) or value is None:
        return fallback if value is None else value
    return fallback


def _config_bool(
    config: object, section: str, key: str, fallback: bool = False
) -> bool:
    getter = getattr(config, "getboolean", None)
    if callable(getter):
        try:
            value = getter(section, key, fallback=fallback)
        except Exception:
            pass
        else:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"1", "true", "yes", "on", "enabled"}:
                    return True
                if normalized in {"0", "false", "no", "off", "disabled", ""}:
                    return False
    value = _config_value(config, section, key, fallback)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled", ""}:
            return False
    return fallback


def _api_socket_open(host: str, port: int, timeout: float = 0.05) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _api_health_entry(widget: object, watcher: object) -> dict[str, object]:
    config = getattr(watcher, "config", None)
    enabled = _config_bool(config, "WebServer", "enabled", False)
    host = str(_config_value(config, "WebServer", "host", "127.0.0.1") or "127.0.0.1")
    try:
        port = int(_config_value(config, "WebServer", "port", 8000) or 8000)
    except (TypeError, ValueError):
        port = 8000

    running = False
    app = getattr(widget, "app", None)
    app_running = getattr(app, "_api_is_running", None)
    if callable(app_running):
        try:
            running = bool(app_running())
        except Exception:
            running = False
    elif enabled:
        running = _api_socket_open(host, port)

    state = "healthy" if running else "error" if enabled else "disabled"
    detail = "listening" if running else "not reachable" if enabled else "off"
    return {
        "state": state,
        "detail": detail,
        "enabled": enabled,
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}",
        "running": running,
    }


def _with_api_health(
    widget: object,
    watcher: object,
    snapshot: dict[str, dict[str, object]] | object,
) -> dict[str, dict[str, object]]:
    merged = dict(snapshot) if isinstance(snapshot, dict) else {}
    merged["api"] = _api_health_entry(widget, watcher)
    return merged


def _format_job_row(
    job: dict[str, Any],
) -> tuple[str, str, str, str, str, str, str, str, str, str, str, str]:
    job_id = str(job.get("id", "N/A"))[:12]
    fallback_pair, fallback_words = _parse_job_title_fallback(job.get("title", ""))
    pair = job.get("lang_pair") or fallback_pair
    derived_words = _derive_display_word_count(job)
    words = str(
        derived_words if derived_words > 0 else _coerce_positive_int(fallback_words)
    )
    reward = f"${job.get('reward', 0):.2f}"
    source = job.get("source", "unknown")
    status = _format_job_status(job)
    time_left = _format_job_time_left(job)
    timestamp = _format_timestamp(job.get("timestamp", job.get("found_at")))
    return (
        job_id,
        pair,
        words,
        reward,
        source,
        status,
        time_left,
        timestamp,
        _format_job_order(job),
        _format_workbench_marker(job),
        _format_text_count(job),
        _format_segment_count(job),
    )


def _populate_full_jobs_table(
    dt: DataTable,
    state: AppState | None,
    *,
    limit: int = 100,
) -> None:
    _ensure_data_table_columns(dt, JOBS_FULL_COLUMNS)
    dt.clear()
    if not state:
        return
    for job in state.get_recent_jobs(limit=limit):
        dt.add_row(*_format_job_row(job))


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

        # Line 2: Separator (handled by CSS border-bottom usually, but explicit
        # line requested)
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
            logging.getLogger(__name__).debug(
                "TitleBar.update_clock: widget not mounted yet"
            )

        # Session timer
        try:
            app = self.app
        except Exception:
            return
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
    """Metric card with centered stat value and border title."""

    def __init__(self, label: str, icon: str, value: str = "0", **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self.icon = icon
        self.value = value
        self.border_title = f"{icon} {label}"

    def compose(self) -> ComposeResult:
        # Border title already provides the card label, so the card body only
        # renders the current stat value centered.
        yield Static(
            self.value,
            classes="metric-value",
            id=f"val-{self.label.lower()}",
        )

    def update_value(self, value: str):
        try:
            self.query_one(f"#val-{self.label.lower()}", Static).update(value)
        except NoMatches:
            logging.getLogger(__name__).debug(
                "MetricCard.update_value: metric value widget not mounted yet"
            )


class MetricsRow(Horizontal):
    """Row of 5 metric cards with sparklines."""

    def __init__(self, state: "AppState", **kwargs):
        super().__init__(**kwargs)
        self.state = state

    def on_mount(self) -> None:
        """Start periodic metrics refresh."""
        self.set_interval(1.0, self.refresh_metrics)

    def compose(self) -> ComposeResult:
        yield MetricCard("Found", Icons.FOUND, id="card-found", classes="found")
        yield MetricCard(
            "Accepted", Icons.ACCEPTED, id="card-accepted", classes="accepted"
        )
        yield MetricCard("Value", Icons.VALUE, id="card-value", classes="value")
        yield MetricCard("Rate", Icons.RATE, id="card-rate", classes="rate")
        yield MetricCard("Today", Icons.TODAY, id="card-today", classes="today")

    def refresh_metrics(self) -> None:
        if not self.state:
            return
        try:
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
        except Exception:
            logging.getLogger(__name__).exception("MetricsRow.refresh_metrics failed")
            return

        updates = {
            "#card-found": str(found),
            "#card-accepted": str(accepted),
            "#card-value": f"${total_value:.2f}",
            "#card-rate": f"{rate:.1f}/hr",
            "#card-today": f"${total_value:.2f}",
        }
        for selector, value in updates.items():
            try:
                self.query_one(selector, MetricCard).update_value(value)
            except NoMatches:
                pass  # Widget not mounted yet


class StatusIndicator(Static):
    """Status indicator with dynamic icon and color based on state."""

    # Icons for different states
    ICONS = {
        "idle": "○",  # Empty circle
        "live": "●",  # Filled circle (will pulse)
        "working": "◐",  # Half circle (activity)
        "error": "✗",  # X mark
        "stale": "!",
        "disabled": "·",
    }

    STATE_FRAMES: ClassVar[dict[str, list[str]]] = {
        "live": ["●", "◉", "●", "○"],
        "working": ["◐", "◓", "◑", "◒"],
        "stale": ["!", "‼", "!", "·"],
        "error": ["✗", "✖", "✗", "✖"],
    }
    PULSE_FRAMES: ClassVar[dict[str, list[str]]] = STATE_FRAMES

    PULSE_STEPS: ClassVar[dict[str, int]] = {
        "live": 4,
        "working": 3,
        "stale": 2,
        "error": 1,
    }

    def __init__(self, base_icon: str, name: str, **kwargs):
        super().__init__(**kwargs)
        self.base_icon = base_icon
        self.label_text = name
        self.detail_text = ""
        self.current_state = "idle"
        self._pulse_index = 0
        self._tick_count = 0
        self.add_class("status-indicator")
        self.add_class("status-idle")

    def compose(self) -> ComposeResult:
        yield Static(
            self._render_label(self.ICONS["idle"]),
            classes="status-label",
            id=f"{self.id}-label",
        )

    def on_mount(self) -> None:
        """Start the pulse animation timer."""
        self.set_interval(0.2, self._pulse_tick)

    @classmethod
    def _pulse_frames_for_state(cls, state: str) -> list[str]:
        return cls.STATE_FRAMES.get(state, [cls.ICONS.get(state, "·")])

    @classmethod
    def _pulse_step_for_state(cls, state: str) -> int:
        return cls.PULSE_STEPS.get(state, 999999)

    def _pulse_tick(self) -> None:
        """Update pulse animation for live indicators."""
        self._tick_count += 1
        frames = self._pulse_frames_for_state(self.current_state)
        step = self._pulse_step_for_state(self.current_state)
        if len(frames) > 1 and step > 0 and self._tick_count % step == 0:
            self._pulse_index = (self._pulse_index + 1) % len(frames)
            self._update_display()

    def _update_display(self) -> None:
        """Update the displayed icon based on current state."""
        try:
            label = self.query_one(f"#{self.id}-label", Static)
            frames = self._pulse_frames_for_state(self.current_state)
            icon = (
                frames[self._pulse_index]
                if len(frames) > 1
                else self.ICONS.get(self.current_state, self.base_icon)
            )
            label.update(self._render_label(icon))
        except NoMatches:
            pass

    def _render_label(self, status_icon: str) -> str:
        detail = f" {self.detail_text}" if self.detail_text else ""
        if self.base_icon:
            return f"{status_icon} {self.base_icon}  {self.label_text}{detail}"
        return f"{status_icon} {self.label_text}{detail}"

    def set_state(self, state: str, detail: str = "") -> None:
        """Set the indicator state and update styling."""
        old_state = self.current_state
        old_detail = self.detail_text
        self.current_state = state
        self.detail_text = detail

        # Update CSS classes
        for s in ("live", "working", "idle", "error", "stale", "disabled"):
            self.remove_class(f"status-{s}")
        self.add_class(f"status-{state}")

        # Reset pulse index when state changes
        if old_state != state:
            self._pulse_index = 0
            self._tick_count = 0

        if old_state != state or old_detail != detail:
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
        # Keep API/browser first so narrow terminals show the active control
        # surfaces instead of burying them behind legacy transport indicators.
        yield StatusIndicator(Icons.API, "API", id="ind-api")
        yield StatusIndicator(Icons.WEB, "Web", id="ind-web")
        yield StatusIndicator(Icons.RSS, "RSS", id="ind-rss")
        yield StatusIndicator(Icons.WEBSOCKET, "WS", id="ind-ws")
        yield StatusIndicator(Icons.WORKFLOW, "Flow", id="ind-work")
        yield StatusIndicator(Icons.AUTO, "Auto", id="ind-auto")
        yield StatusIndicator(Icons.EMAIL, "Mail", id="ind-email")
        yield StatusIndicator(Icons.CAPTCHA, "Cap", id="ind-cap")

    def _set_indicator_state(self, selector: str, state: str) -> None:
        self.query_one(selector, StatusIndicator).set_state(state)

    @staticmethod
    def _state_from_health(snapshot: dict | None, key: str) -> tuple[str, str]:
        if not isinstance(snapshot, dict):
            return "idle", ""
        entry = snapshot.get(key)
        if not isinstance(entry, dict):
            return "idle", ""
        state = str(entry.get("state") or "idle")
        detail = str(entry.get("detail") or "")
        mapping = {
            "healthy": "live",
            "working": "working",
            "stale": "stale",
            "error": "error",
            "disabled": "disabled",
            "idle": "idle",
        }
        compact = {
            "ok": "ok",
            "off": "off",
            "ready": "ready",
            "manual": "manual",
            "running": "run",
            "sync failed": "sync!",
            "misconfig": "cfg!",
            "blocked": "blocked",
            "never checked": "never",
            "no pong": "nopong",
        }
        return mapping.get(state, "idle"), compact.get(detail, detail[:10])

    @staticmethod
    def _has_error(status: str) -> bool:
        return bool(status and "error" in status.lower())

    def _websocket_state(self) -> str:
        ws_status = getattr(self.watcher, "websocket_status", "")
        ws_connected = getattr(self.watcher, "websocket_connected", False)
        if ws_connected or ws_status == "Live":
            return "live"
        if ws_status in ("Connecting", "Reconnecting"):
            return "working"
        if self._has_error(ws_status):
            return "error"
        return "idle"

    def _email_state(self) -> str:
        email_status = getattr(self.watcher, "email_monitor_status", "")
        if email_status in ("Polling", "Connected"):
            return "live"
        if email_status == "Checking":
            return "working"
        if self._has_error(email_status):
            return "error"
        return "idle"

    def _website_state(self) -> str:
        web_status = getattr(self.watcher, "website_monitor_status", "")
        if web_status == "Monitoring":
            return "live"
        if web_status == "Checking":
            return "working"
        if self._has_error(web_status):
            return "error"
        return "idle"

    def _rss_state(self) -> str:
        rss_action = getattr(self.watcher, "rss_action", "")
        if "Fetching" in rss_action or "Checking" in rss_action:
            return "working"
        if self._has_error(rss_action):
            return "error"
        if rss_action:
            return "live"
        return "idle"

    def _captcha_state(self) -> str:
        captcha_enabled = getattr(self.watcher, "captcha_enabled", False)
        captcha_solving = getattr(self.watcher, "captcha_solving", False)
        if captcha_solving:
            return "working"
        if captcha_enabled:
            return "live"
        return "idle"

    def _workflow_state(self) -> str:
        is_processing = getattr(self.watcher, "is_processing", False)
        return "working" if is_processing else "idle"

    def _auto_state(self) -> str:
        auto_accept = getattr(self.watcher, "auto_accept_enabled", False)
        return "live" if auto_accept else "idle"

    def _api_state(self) -> tuple[str, str]:
        entry = _api_health_entry(self, self.watcher)
        state = str(entry.get("state") or "disabled")
        detail = str(entry.get("detail") or "")
        mapping = {
            "healthy": "live",
            "working": "working",
            "stale": "stale",
            "error": "error",
            "disabled": "disabled",
        }
        compact_details = {
            "listening": "on",
            "ready": "ready",
            "ingress ready": "in",
            "no outgoing targets": "in",
            "off": "off",
        }
        compact = compact_details.get(detail, detail[:8])
        return mapping.get(state, "idle"), compact

    def refresh_status(self) -> None:
        """Refresh all status indicators based on watcher state."""
        if not self.watcher:
            return

        try:
            health_snapshot = None
            health_getter = getattr(self.watcher, "get_health_snapshot", None)
            if callable(health_getter):
                candidate = health_getter()
                if isinstance(candidate, dict):
                    health_snapshot = candidate

            if health_snapshot:
                alert_health = getattr(self.watcher, "alert_on_health_snapshot", None)
                if callable(alert_health):
                    alert_health(health_snapshot)
                ws_state, ws_detail = self._state_from_health(
                    health_snapshot, "websocket"
                )
                rss_state, rss_detail = self._state_from_health(health_snapshot, "rss")
                auto_state, auto_detail = self._state_from_health(
                    health_snapshot, "auto"
                )
                workflow_state, workflow_detail = self._state_from_health(
                    health_snapshot, "workflow"
                )
                browser_state, browser_detail = self._state_from_health(
                    health_snapshot, "browser"
                )
                email_state, email_detail = self._state_from_health(
                    health_snapshot, "email"
                )
                api_state, api_detail = self._api_state()
                self.query_one("#ind-ws", StatusIndicator).set_state(ws_state)
                self.query_one("#ind-rss", StatusIndicator).set_state(rss_state)
                self.query_one("#ind-api", StatusIndicator).set_state(
                    api_state, api_detail
                )
                self.query_one("#ind-auto", StatusIndicator).set_state(auto_state)
                self.query_one("#ind-work", StatusIndicator).set_state(workflow_state)
                self.query_one("#ind-web", StatusIndicator).set_state(
                    browser_state, browser_detail
                )
                self.query_one("#ind-email", StatusIndicator).set_state(
                    email_state, email_detail
                )
            else:
                self._set_indicator_state("#ind-ws", self._websocket_state())
                self._set_indicator_state("#ind-rss", self._rss_state())
                self._set_indicator_state("#ind-work", self._workflow_state())
                self._set_indicator_state("#ind-auto", self._auto_state())
                api_state, api_detail = self._api_state()
                self.query_one("#ind-api", StatusIndicator).set_state(
                    api_state,
                    api_detail,
                )
                self._set_indicator_state("#ind-email", self._email_state())
                self._set_indicator_state("#ind-web", self._website_state())

            self._set_indicator_state("#ind-cap", self._captcha_state())

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
            r"\b(?:found|accepted|success|connected|started|completed|ok|" r"passed)\b",
            "success",
        ),
        (
            r"\b(?:error|failed|failure|exception|crash|rejected|timeout|" r"denied)\b",
            "error_word",
        ),
        (
            r"\b(?:warning|warn|caution|retry|retrying|slow|delayed)\b",
            "warning_word",
        ),
        (r"\b(?:websocket|ws|socket)\b", "source_ws"),
        (r"\b(?:webhook|webhooks|hook|hooks)\b", "source_ws"),
        (r"\b(?:email|imap|mail)\b", "source_email"),
        (r"\b(?:rss|feed)\b", "source_rss"),
        (r"\b(?:web|http|browser|scrape)\b", "source_web"),
        (r"\b\d+(?:\.\d+)?\b", "number"),
    ]

    def __init__(self, **kwargs):
        super().__init__(f"{Icons.PANEL_ACTIVITY} Recent Activity", **kwargs)
        # Compile patterns
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), color_key)
            for pattern, color_key in self.PATTERNS
        ]

    def compose(self) -> ComposeResult:
        # Just yield content, border_title handles the header
        yield RichLog(
            id="activity-log",
            markup=True,
            max_lines=ACTIVITY_PREVIEW_MAX_LINES,
        )

    def add_line(self, message: str, level: str = "info") -> None:
        """Add a colored line to the activity log.

        Args:
            message: The message to display
            level: One of 'info', 'warning', 'error', 'debug', 'success', 'job'
        """
        try:
            log = self.query_one("#activity-log", RichLog)
            line = _with_timestamp_prefix(message)
            colored_text = self._colorize_message(line, level)
            log.write(colored_text)
        except NoMatches:
            pass  # Widget not mounted yet

    def _colorize_message(self, msg: str, level: str = "info") -> Text:
        """Apply Rich markup coloring based on content patterns."""
        colors = _build_semantic_color_palette(_get_active_theme(self))

        # Determine base color from level
        color_key = self.LEVEL_COLORS.get(level, "default")
        base_color = colors[color_key]

        # Create text with base styling
        text = Text(msg, style=base_color)

        # Apply pattern-based highlighting
        for pattern, color_key in self._compiled_patterns:
            color = colors.get(color_key, base_color)
            for match in pattern.finditer(msg):
                start, end = match.span()
                # Apply bold for important items
                if color_key in ("job_id", "money", "success", "error_word"):
                    text.stylize(f"bold {color}", start, end)
                else:
                    text.stylize(color, start, end)

        return text


class CommandInput(Input):
    """Bottom command prompt that leaves bare app shortcuts available."""

    def check_consume_key(self, key: str, character: str | None) -> bool:
        if key == "q" and not str(self.value or ""):
            return False
        return super().check_consume_key(key, character)


class JobsPreview(DashboardQuadrant):
    def __init__(self, state: "AppState", **kwargs):
        super().__init__(f"{Icons.PANEL_JOBS} Jobs Preview", **kwargs)
        self.state = state

    def compose(self) -> ComposeResult:
        yield DataTable(id="jobs-table")

    def on_mount(self):
        """Initialize table columns and start periodic refresh."""
        self.set_interval(2.0, self.refresh_jobs)
        try:
            dt = self.query_one(DataTable)
            _ensure_data_table_columns(dt, JOBS_PREVIEW_COLUMNS)
        except NoMatches:
            pass  # Widget not mounted yet
        self.refresh_jobs()

    def refresh_jobs(self):
        """
        Refresh the jobs preview table from the current application state.

        Populates the jobs DataTable with up to 10 most recent jobs from
        state, showing a truncated job ID (first 8 chars), language pair,
        word count and formatted reward. If state is unavailable, the method
        returns immediately. If the table widget is not mounted yet, the
        method quietly does nothing.
        """
        if not self.state:
            return
        try:
            dt = self.query_one(DataTable)
            _ensure_data_table_columns(dt, JOBS_PREVIEW_COLUMNS)
            dt.clear()
            jobs = self.state.get_recent_jobs(limit=10)
            for job in jobs:
                job_id = str(job.get("id", "N/A"))[:8]
                fallback_pair, fallback_words = _parse_job_title_fallback(
                    job.get("title", "")
                )
                pair = job.get("lang_pair") or fallback_pair
                derived_words = _derive_display_word_count(job)
                words = str(
                    derived_words
                    if derived_words > 0
                    else _coerce_positive_int(fallback_words)
                )
                reward = f"${job.get('reward', 0):.2f}"
                dt.add_row(job_id, pair, words, reward, _format_job_time_left(job))
        except NoMatches:
            pass  # Widget not mounted yet


class HourlyActivity(DashboardQuadrant):
    """Hourly activity stats with peak hour highlighting."""

    def __init__(
        self, stats: "StatsManager", state: "AppState | None" = None, **kwargs
    ):
        super().__init__(f"{Icons.PANEL_CHART} Jobs/Hour", **kwargs)
        self.stats = stats
        self.state = state

    def compose(self) -> ComposeResult:
        yield Static("No activity data", id="hourly-content")

    def on_mount(self) -> None:
        """Initialize widget with current data and start periodic refresh."""
        self.refresh_hourly()
        self.set_interval(5.0, self.refresh_hourly)

    def refresh_hourly(self):
        """Refresh hourly activity display."""
        try:
            rolling_values = self._rolling_hourly_counts_from_state()
            if rolling_values:
                peak_index = max(
                    range(len(rolling_values)), key=lambda i: rolling_values[i]
                )
                peak_rate = float(rolling_values[peak_index])
                peak_period = self._format_peak_period_for_bucket(
                    peak_index, total_buckets=len(rolling_values)
                )
                # Use 2-hour bins for readability in compact dashboard cards.
                chart_values = _aggregate_series(rolling_values, bin_size=2)
                chart = _render_plotext_bar_chart(
                    chart_values,
                    width=30,
                    height=8,
                    x_left="24h",
                    x_mid="12h",
                    x_right="now",
                ) or _render_chart_with_axes(
                    chart_values,
                    width=len(chart_values),
                    height=4,
                    x_left="24h",
                    x_right="now",
                )
                content_parts = []
                if chart.strip():
                    content_parts.append(chart)
                content_parts.append(f"Peak: {peak_period}  Jobs: {int(peak_rate)}")
                content = "\n".join(content_parts)
            else:
                hourly_counts = self._hourly_counts_from_stats()
                if not hourly_counts:
                    hourly_counts = self._hourly_counts_from_state()

                if hourly_counts:
                    peak_hour = max(hourly_counts, key=lambda h: hourly_counts[h])
                    peak_rate = float(hourly_counts[peak_hour])
                    peak_period_start = (peak_hour // 3) * 3
                    peak_period_end = peak_period_start + 3
                    peak_period = f"{peak_period_start:02d}-{peak_period_end:02d}"
                    values = [hourly_counts.get(hour, 0.0) for hour in range(24)]
                    chart_values = _aggregate_series(values, bin_size=2)
                    chart = _render_plotext_bar_chart(
                        chart_values,
                        width=30,
                        height=8,
                        x_left="00:00",
                        x_mid="12:00",
                        x_right="23:59",
                    ) or _render_chart_with_axes(
                        chart_values,
                        width=len(chart_values),
                        height=4,
                        x_left="00:00",
                        x_right="23:59",
                    )

                    content_parts = []
                    if chart.strip():
                        content_parts.append(chart)
                    content_parts.append(f"Peak: {peak_period}  Jobs: {int(peak_rate)}")
                    content = "\n".join(content_parts)
                else:
                    content = "No activity yet"

            self.query_one("#hourly-content", Static).update(content)
        except Exception:
            pass  # Widget not mounted yet

    def _hourly_counts_from_stats(self) -> dict[int, float]:
        """Get positive hourly counts from StatsManager."""
        if not self.stats:
            return {}

        raw_counts = getattr(self.stats, "hourly_counts", {}) or {}
        counts: dict[int, float] = {}
        for hour, count in raw_counts.items():
            try:
                hour_i = int(hour)
                count_f = float(count)
            except (TypeError, ValueError):
                continue
            if 0 <= hour_i <= 23 and count_f > 0:
                counts[hour_i] = count_f
        return counts

    def _hourly_counts_from_state(self) -> dict[int, float]:
        """Derive hourly counts from persisted AppState jobs."""
        if not self.state:
            return {}

        counts: dict[int, float] = {}
        jobs = self.state.get_recent_jobs(limit=1000)
        for job in jobs:
            ts = job.get("timestamp")
            hour = self._extract_hour(ts)
            if hour is None:
                continue
            counts[hour] = counts.get(hour, 0.0) + 1.0
        return counts

    def _coerce_timestamp(self, timestamp: Any) -> float | None:
        """Convert numeric/ISO timestamps to epoch seconds."""
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            value = float(timestamp)
            return value if value > 0 else None

        if isinstance(timestamp, str):
            cleaned = timestamp.strip()
            if not cleaned:
                return None
            iso_candidate = (
                cleaned[:-1] + "+00:00" if cleaned.endswith("Z") else cleaned
            )
            try:
                return datetime.datetime.fromisoformat(iso_candidate).timestamp()
            except ValueError:
                return None

        return None

    def _rolling_hourly_counts_from_state(
        self,
        window_hours: int = 24,
    ) -> list[float]:
        """
        Build rolling hourly buckets from oldest->newest for recent state jobs.

        The rightmost bucket represents the current hour; earlier buckets step
        backwards in one-hour increments.
        """
        if not self.state or window_hours <= 0:
            return []

        buckets = [0.0] * window_hours
        now_ts = time.time()
        jobs = self.state.get_recent_jobs(limit=1000)
        for job in jobs:
            ts = self._coerce_timestamp(job.get("timestamp"))
            if ts is None:
                continue
            delta_seconds = now_ts - ts
            if delta_seconds < 0:
                continue
            hours_ago = int(delta_seconds // 3600)
            if hours_ago >= window_hours:
                continue
            bucket_index = window_hours - 1 - hours_ago
            buckets[bucket_index] += 1.0

        return buckets if any(v > 0 for v in buckets) else []

    def _format_peak_period_for_bucket(
        self, bucket_index: int, total_buckets: int = 24
    ) -> str:
        """Format a rolling bucket index as an HH-HH one-hour period."""
        now_hour = datetime.datetime.now().replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        hours_ago = max(0, (total_buckets - 1) - bucket_index)
        start = now_hour - datetime.timedelta(hours=hours_ago)
        end = start + datetime.timedelta(hours=1)
        return f"{start:%H}-{end:%H}"

    def _peak_hour_from_state(self) -> tuple[int, float]:
        """Compute peak hour from state when stats has no activity."""
        hourly_counts = self._hourly_counts_from_state()

        if not hourly_counts:
            return (12, 0.0)

        peak_hour = max(hourly_counts, key=lambda h: hourly_counts[h])
        return (peak_hour, float(hourly_counts[peak_hour]))

    def _extract_hour(self, timestamp: Any) -> int | None:
        """Extract an hour (0-23) from a numeric or string timestamp value."""
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            try:
                hour = datetime.datetime.fromtimestamp(float(timestamp)).hour
                return hour if 0 <= hour <= 23 else None
            except (OSError, OverflowError, ValueError):
                return None

        if isinstance(timestamp, str):
            cleaned = timestamp.strip()
            if not cleaned:
                return None

            iso_candidate = cleaned
            if iso_candidate.endswith("Z"):
                iso_candidate = iso_candidate[:-1] + "+00:00"
            try:
                hour = datetime.datetime.fromisoformat(iso_candidate).hour
                return hour if 0 <= hour <= 23 else None
            except ValueError:
                pass

            match = re.search(r"(\d{2}):\d{2}:\d{2}", cleaned)
            if match:
                try:
                    hour = int(match.group(1))
                    return hour if 0 <= hour <= 23 else None
                except ValueError:
                    return None

        return None


class ConfigPreview(DashboardQuadrant):
    """Configuration preview showing all config.toml options."""

    # Keys that should be masked for security
    SENSITIVE_KEYS: ClassVar[frozenset[str]] = frozenset(
        {
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
    )

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
        super().__init__(f"{Icons.PANEL_CONFIG} Configuration", **kwargs)
        self.config = config

    def compose(self) -> ComposeResult:
        with Vertical(id="config-scroll"):
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
                "ConfigPreview.refresh_config: '#config-content' widget "
                "not found; skipping update."
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
        """Format a config value for display.

        Only None or empty string render as em dash. Numeric zero is preserved.
        """
        if self._is_sensitive(key) and value:
            formatted = self._mask_value(value)
        elif isinstance(value, bool):
            formatted = "✓" if value else "✗"
        elif isinstance(value, list):
            formatted = ", ".join(str(v) for v in value)
        elif isinstance(value, float):
            formatted = f"{value:.2f}" if value != int(value) else str(int(value))
        else:
            formatted = str(value) if value else "—"

        return formatted

    def _value_width_limit(self) -> int:
        """Return the value width currently used by config rendering."""
        return self.MAX_VALUE_LENGTH

    def _render_config(self) -> Text:
        """Render all config sections and options."""
        text = Text()
        styles = _build_config_style_palette(_get_active_theme(self))
        config = getattr(self, "config", None)
        list_all = getattr(config, "list_all", None)
        if not callable(list_all):
            # Gracefully handle cases where config is a mock or non-AppConfig
            # without list_all()
            return text
        all_config = cast(dict[str, dict[str, Any]], list_all())

        # Render known sections first in preferred order, then any additional
        # sections
        sections_to_render = list(self.SECTION_ORDER) + [
            s for s in all_config if s not in self.SECTION_ORDER
        ]

        for section in sections_to_render:
            if section not in all_config:
                continue
            options = all_config[section]
            if not options:
                continue

            # Section header
            text.append(f"─ {section} ", style=styles["section_header"])
            text.append(
                "─" * max(1, self.SECTION_HEADER_WIDTH - len(section)),
                style=styles["section_rule"],
            )
            text.append("\n")

            # Options
            for key, value in options.items():
                formatted_value = self._format_value(key, value)
                # Truncate long values
                value_width_limit = self._value_width_limit()
                if len(formatted_value) > value_width_limit:
                    formatted_value = (
                        formatted_value[: self.MAX_VALUE_LENGTH_SHORT] + "..."
                    )

                # Key styling
                text.append(f"  {key}: ", style=styles["key"])

                # Value styling based on type/content
                if self._is_sensitive(key):
                    text.append(formatted_value, style="#957FB8")
                elif isinstance(value, bool):
                    text.append(
                        formatted_value,
                        style=(styles["bool_true"] if value else styles["bool_false"]),
                    )
                elif isinstance(value, (int, float)):
                    text.append(formatted_value, style=styles["number"])
                else:
                    text.append(formatted_value, style=styles["value"])
                text.append("\n")

        return text


class SessionStats(DashboardQuadrant):
    """Session statistics summary."""

    def __init__(self, watcher: "GengoWatcher", state: "AppState", **kwargs):
        super().__init__(f"{Icons.PANEL_SESSION} Session", **kwargs)
        self.watcher = watcher
        self.state = state

    def compose(self) -> ComposeResult:
        with Vertical(id="session-stats-content"):
            yield Static("Duration: 0h 00m", id="stat-duration")
            yield Static("Found: 0", id="stat-found")
            yield Static("Accepted: 0", id="stat-accepted")
            yield Static("Value: $0.00", id="stat-value")

    def on_mount(self) -> None:
        """Start periodic stats refresh."""
        self.set_interval(1.0, self.refresh_stats)

    def refresh_stats(self):
        if not self.watcher or not self.state:
            return
        elapsed = int(time.time() - self.watcher.start_time)
        h, m = divmod(elapsed // 60, 60)
        jobs = self.state.get_recent_jobs(limit=1000)
        found = len(jobs)
        accepted = sum(1 for j in jobs if j.get("accepted", False))
        total = sum(j.get("reward", 0) for j in jobs)

        updates = {
            "#stat-duration": f"Duration: {h}h {m:02d}m",
            "#stat-found": f"Found: {found}",
            "#stat-accepted": f"Accepted: {accepted}",
            "#stat-value": f"Value: ${total:.2f}",
        }
        for selector, value in updates.items():
            try:
                self.query_one(selector, Static).update(value)
            except NoMatches:
                pass  # Widget not mounted yet


class TelemetryPanel(DashboardQuadrant):
    """Compact dashboard telemetry card for quick health checks."""

    HEALTH_ICONS: ClassVar[dict[str, str]] = {
        "healthy": "●",
        "working": "◐",
        "stale": "!",
        "error": "✗",
        "disabled": "·",
    }

    ROWS: ClassVar[list[tuple[str, str]]] = [
        ("websocket", "WS"),
        ("rss", "RSS"),
        ("api", "API"),
        ("session", "Session"),
        ("email", "Email"),
        ("browser", "Browser"),
        ("workflow", "Workflow"),
        ("auto", "Auto"),
    ]

    DETAIL_FIELDS: ClassVar[dict[str, tuple[str, ...]]] = {
        "websocket": ("last_pong_age_sec", "last_message_age_sec", "ping_latency_ms"),
        "rss": ("last_success_age_sec", "failure_count", "next_check_in_sec"),
        "api": ("url", "enabled"),
        "session": ("last_sync_age_sec", "sync_interval_sec"),
        "email": ("last_check_age_sec", "jobs_found_session"),
        "browser": ("collection_id", "last_check_age_sec"),
        "workflow": tuple(),
        "auto": tuple(),
    }

    STATE_STYLE_KEYS: ClassVar[dict[str, str]] = {
        "healthy": "success",
        "working": "warning_word",
        "stale": "warning_word",
        "error": "error_word",
        "disabled": "timestamp",
    }

    def __init__(self, watcher: "GengoWatcher", **kwargs):
        super().__init__(f"{Icons.PANEL_TELEMETRY} Telemetry", **kwargs)
        self.watcher = watcher
        self._tick_count = 0
        self._last_snapshot: dict[str, dict[str, object]] = {}

    def compose(self) -> ComposeResult:
        yield Static("Loading telemetry...", id="telemetry-content")

    def on_mount(self) -> None:
        self.set_interval(1.0, self.refresh_telemetry)
        self.set_interval(0.2, self._pulse_tick)

    def _pulse_tick(self) -> None:
        self._tick_count += 1
        self._render_cached_snapshot()

    def _render_compact(self, snapshot: dict[str, dict[str, object]]) -> Text:
        text = Text()
        colors = _build_semantic_color_palette(_get_active_theme(self))
        enabled_rows = []
        disabled_rows = []
        for key, label in self.ROWS:
            entry = snapshot.get(key, {}) if isinstance(snapshot, dict) else {}
            state = str(entry.get("state") or "disabled")
            payload = (key, label, entry if isinstance(entry, dict) else {}, state)
            (disabled_rows if state == "disabled" else enabled_rows).append(payload)

        self._append_section(text, "Enabled", enabled_rows, colors)
        if enabled_rows and disabled_rows:
            text.append("\n\n")
        self._append_section(text, "Disabled", disabled_rows, colors)
        return text

    def _append_section(
        self, text: Text, title: str, rows, colors: dict[str, str]
    ) -> None:
        if not rows:
            return
        text.append(f"{title}\n", style=f"bold {colors['source_ws']}")
        for idx, (key, label, entry, state) in enumerate(rows):
            detail = str(entry.get("detail") or "")
            icon = self._animated_icon(state)
            state_style = colors[self.STATE_STYLE_KEYS.get(state, "default")]
            text.append(f"{icon} {label:<10}  ", style="bold")
            text.append(f"{state.upper():<9}", style=f"bold {state_style}")
            extras = self._compact_extras(key, entry)
            segments = [detail] if detail else []
            if extras:
                segments.append(extras)
            if segments:
                text.append("  " + "  ".join(segments), style=colors["default"])
            if idx < len(rows) - 1:
                text.append("\n")

    def _animated_icon(self, state: str) -> str:
        frames = StatusIndicator._pulse_frames_for_state(
            {"healthy": "live"}.get(state, state)
        )
        step = StatusIndicator._pulse_step_for_state(
            {"healthy": "live"}.get(state, state)
        )
        if len(frames) > 1 and step > 0:
            return frames[(self._tick_count // step) % len(frames)]
        return self.HEALTH_ICONS.get(state, "·")

    def _compact_extras(self, key: str, entry: dict[str, object]) -> str:
        extras = []
        for field in self.DETAIL_FIELDS.get(key, tuple()):
            value = entry.get(field)
            formatted = self._format_detail_field(field, value)
            if formatted:
                extras.append(formatted)
        return " ".join(extras[:2])

    @staticmethod
    def _format_detail_field(field: str, value: object) -> str:
        if value is None:
            return ""
        if field.endswith("_age_sec") or field.endswith("_in_sec"):
            try:
                return f"{int(float(str(value)))}s"
            except (TypeError, ValueError):
                return ""
        if field.endswith("_ms"):
            try:
                return f"{int(float(str(value)))}ms"
            except (TypeError, ValueError):
                return ""
        return str(value)

    def refresh_telemetry(self) -> None:
        if not self.watcher:
            return
        getter = getattr(self.watcher, "get_health_snapshot", None)
        snapshot = getter() if callable(getter) else {}
        self._last_snapshot = _with_api_health(self, self.watcher, snapshot)
        self._render_cached_snapshot()

    def _render_cached_snapshot(self) -> None:
        try:
            content = self.query_one("#telemetry-content", Static)
            content.update(self._render_compact(self._last_snapshot))
        except NoMatches:
            pass


class TelemetryTab(Static):
    """Detailed telemetry diagnostics tab."""

    def __init__(self, watcher: "GengoWatcher", **kwargs):
        super().__init__(**kwargs)
        self.watcher = watcher
        self._tick_count = 0
        self._last_snapshot: dict[str, dict[str, object]] = {}

    def compose(self) -> ComposeResult:
        yield Static("Telemetry details unavailable", id="telemetry-tab-content")

    def on_mount(self) -> None:
        self.refresh_telemetry()
        self.set_interval(1.0, self.refresh_telemetry)
        self.set_interval(0.2, self._pulse_tick)

    def _pulse_tick(self) -> None:
        self._tick_count += 1
        self._render_cached_snapshot()

    def refresh_telemetry(self) -> None:
        getter = getattr(self.watcher, "get_health_snapshot", None)
        snapshot = getter() if callable(getter) else {}
        self._last_snapshot = _with_api_health(self, self.watcher, snapshot)
        self._render_cached_snapshot()

    def _render_cached_snapshot(self) -> None:
        text = Text()
        snapshot = self._last_snapshot
        colors = _build_semantic_color_palette(_get_active_theme(self))
        if isinstance(snapshot, dict):
            ordered = []
            for key, _label in TelemetryPanel.ROWS:
                entry = snapshot.get(key)
                if isinstance(entry, dict):
                    ordered.append((key, entry, str(entry.get("state") or "disabled")))
            enabled = [row for row in ordered if row[2] != "disabled"]
            disabled = [row for row in ordered if row[2] == "disabled"]
            self._append_detailed_section(text, "ENABLED MODULES", enabled, colors)
            if enabled and disabled:
                text.append("\n")
            self._append_detailed_section(text, "DISABLED MODULES", disabled, colors)
        try:
            self.query_one("#telemetry-tab-content", Static).update(text)
        except NoMatches:
            pass

    def _append_detailed_section(
        self, text: Text, title: str, rows, colors: dict[str, str]
    ) -> None:
        if not rows:
            return
        text.append(f"{title}\n", style=f"bold {colors['source_ws']}")
        for idx, (key, entry, state) in enumerate(rows):
            pulse_state = str({"healthy": "live"}.get(state, state))
            frames = StatusIndicator._pulse_frames_for_state(pulse_state)
            step = StatusIndicator._pulse_step_for_state(pulse_state)
            icon = (
                frames[(self._tick_count // step) % len(frames)]
                if len(frames) > 1 and step > 0
                else TelemetryPanel.HEALTH_ICONS.get(state, "·")
            )
            state_style = colors[TelemetryPanel.STATE_STYLE_KEYS.get(state, "default")]
            label = key.upper()
            text.append(f"{icon} {label:<12}  ", style="bold")
            text.append(f"{state.upper()}\n", style=f"bold {state_style}")
            for field, value in entry.items():
                text.append(f"  {field:<20}  ", style=colors["timestamp"])
                text.append(f"{value}\n", style=colors["default"])
            if idx < len(rows) - 1:
                text.append("\n")


class ApiTab(Static):
    """Detailed API ingress/egress and audit diagnostics."""

    def __init__(self, watcher: "GengoWatcher", **kwargs):
        super().__init__(**kwargs)
        self.watcher = watcher

    def compose(self) -> ComposeResult:
        yield Static("API details unavailable", id="api-tab-content")

    def on_mount(self) -> None:
        self.refresh_api()
        self.set_interval(1.0, self.refresh_api)

    def _websocket_job_feed_summary(self, snapshot: dict[str, Any]) -> str:
        websocket_health = (
            snapshot.get("websocket") if isinstance(snapshot, dict) else {}
        )
        if isinstance(websocket_health, dict):
            state = str(websocket_health.get("state") or "").strip()
            detail = str(websocket_health.get("detail") or "").strip()
            if state or detail:
                suffix = f" {detail}" if detail else ""
                return f"WebSocket {state or 'unknown'}{suffix}"

        config = getattr(self.watcher, "config", None)
        enabled = True
        if config is not None:
            try:
                enabled = bool(
                    config.getboolean("WebSocket", "enable_websocket", fallback=True)
                )
            except Exception:
                enabled = True
        status = str(getattr(self.watcher, "websocket_status", "") or "").strip()
        if not enabled:
            return "WebSocket disabled"
        return f"WebSocket enabled {status}".strip()

    def _browser_collected_jobs(self, limit: int = 8) -> list[dict[str, Any]]:
        state = getattr(self.watcher, "state", None)
        getter = getattr(state, "get_recent_jobs", None)
        if not callable(getter):
            return []
        try:
            jobs = getter(limit=50)
        except TypeError:
            jobs = getter(50)
        except Exception:
            return []
        collected = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            if any(
                job.get(key)
                for key in (
                    "workbench_visible",
                    "workbench_url",
                    "workbench_payload",
                    "accepted_workbench",
                    "seconds_left",
                    "source_text",
                    "accepted_source_text",
                )
            ):
                collected.append(job)
            if len(collected) >= limit:
                break
        return collected

    def _append_browser_collected_section(
        self,
        text: Text,
        colors: dict[str, str],
    ) -> None:
        text.append(
            "\nBROWSER-COLLECTED JOB DATA\n", style=f"bold {colors['source_ws']}"
        )
        jobs = self._browser_collected_jobs()
        if not jobs:
            text.append(
                "No browser-collected job data yet.\n", style=colors["timestamp"]
            )
            return

        for job in jobs:
            job_id = str(job.get("id") or "?")[:12]
            state = str(
                job.get("acceptance_state") or job.get("lifecycle_state") or "observed"
            )
            left = _format_job_time_left(job) or "--"
            order = _format_job_order(job) or "--"
            text_count = _format_text_count(job) or "0c"
            segments = _format_segment_count(job) or "0"
            workbench = _format_workbench_marker(job) or "--"

            text.append(f"{job_id:<12} ", style=colors["job_id"])
            text.append(f"{state:<12} ", style=colors["source_rss"])
            text.append(f"left={left:<9} ", style=colors["warning_word"])
            text.append(f"order={order:<12} ", style=colors["default"])
            text.append(f"wb={workbench:<7} ", style=colors["source_web"])
            text.append(
                f"text={text_count:<7} segs={segments}\n", style=colors["default"]
            )

    def refresh_api(self) -> None:
        colors = _build_semantic_color_palette(_get_active_theme(self))
        text = Text()
        health_getter = getattr(self.watcher, "get_health_snapshot", None)
        snapshot = health_getter() if callable(health_getter) else {}
        api_health = _api_health_entry(self, self.watcher)
        event_health = {}
        if isinstance(snapshot, dict):
            candidate = snapshot.get("api_events") or snapshot.get("webhooks")
            if isinstance(candidate, dict):
                event_health = candidate

        audit_logger = getattr(self.watcher, "webhook_audit_logger", None)
        summary_getter = getattr(audit_logger, "summary", None)
        summary = summary_getter(12) if callable(summary_getter) else {}
        recent = summary.get("recent", []) if isinstance(summary, dict) else []

        api_state = str(api_health.get("state") or "disabled")
        api_detail = str(api_health.get("detail") or "off")
        api_state_style = colors[
            TelemetryPanel.STATE_STYLE_KEYS.get(api_state, "default")
        ]
        text.append("HTTP API\n", style=f"bold {colors['source_ws']}")
        text.append("Server          ", style=colors["timestamp"])
        text.append(f"{api_state.upper()} ", style=f"bold {api_state_style}")
        text.append(f"{api_detail}\n", style=colors["default"])
        text.append("URL             ", style=colors["timestamp"])
        text.append(f"{api_health.get('url')}\n", style=colors["url"])
        text.append("Enabled         ", style=colors["timestamp"])
        text.append(f"{api_health.get('enabled')}\n", style=colors["default"])
        text.append("Gengo job feed  ", style=colors["timestamp"])
        text.append(
            f"{self._websocket_job_feed_summary(snapshot)}\n",
            style=colors["default"],
        )
        self._append_browser_collected_section(text, colors)

        event_state = str(event_health.get("state") or "disabled")
        event_detail = str(event_health.get("detail") or "off")
        event_state_style = colors[
            TelemetryPanel.STATE_STYLE_KEYS.get(event_state, "default")
        ]
        text.append("\nAPI JOB EVENTS\n", style=f"bold {colors['source_ws']}")
        text.append("State           ", style=colors["timestamp"])
        text.append(f"{event_state.upper()} ", style=f"bold {event_state_style}")
        text.append(f"{event_detail}\n", style=colors["default"])
        for label, key in (
            ("Ingress", "incoming_enabled"),
            ("Outgoing", "outbound_enabled"),
            ("Targets", "target_count"),
            ("Audit", "audit_enabled"),
            ("Debug", "debug_enabled"),
        ):
            text.append(f"{label:<15} ", style=colors["timestamp"])
            text.append(f"{event_health.get(key)}\n", style=colors["default"])

        text.append("Audit log       ", style=colors["timestamp"])
        text.append(f"{event_health.get('audit_log_path', '')}\n", style=colors["url"])
        text.append("Counters        ", style=colors["timestamp"])
        text.append(
            "in={incoming_total} out={outgoing_total} processed={processed_total} "
            "delivered={delivered_total} failed={failed_total} duplicate={duplicate_total}\n".format(
                **{
                    key: event_health.get(key, 0)
                    for key in (
                        "incoming_total",
                        "outgoing_total",
                        "processed_total",
                        "delivered_total",
                        "failed_total",
                        "duplicate_total",
                    )
                }
            ),
            style=colors["default"],
        )

        text.append("\nRECENT API AUDIT\n", style=f"bold {colors['source_ws']}")
        if not recent:
            text.append("No API audit records yet.", style=colors["timestamp"])
        for entry in recent[-12:]:
            if not isinstance(entry, dict):
                continue
            ts = _format_timestamp(entry.get("ts")) or "--:--:--"
            direction = str(entry.get("direction") or "?")
            stage = str(entry.get("stage") or "?")
            status = str(entry.get("status") or "")
            event_type = str(entry.get("event_type") or "")
            event_id = str(entry.get("event_id") or entry.get("request_id") or "")
            error = str(entry.get("error") or "")
            status_key = "error_word" if status in {"failed", "rejected"} else "success"
            text.append(f"{ts} ", style=colors["timestamp"])
            text.append(f"{direction:<8} ", style=colors["source_web"])
            text.append(f"{stage:<18} ", style=colors["source_rss"])
            text.append(f"{status:<10} ", style=colors[status_key])
            if event_type:
                text.append(f"{event_type} ", style=colors["source_ws"])
            if event_id:
                text.append(f"{event_id} ", style=colors["job_id"])
            if error:
                text.append(f"{error[:120]}", style=colors["error_word"])
            text.append("\n")

        try:
            self.query_one("#api-tab-content", Static).update(text)
        except NoMatches:
            pass


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
                "Jobs Found: 0\nAccepted: 0\nValue: $0.00",
                id="stats-session-content",
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
                f"Total Accepted: {alltime.total_jobs_accepted}\n"
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
            _ensure_data_table_columns(dt, JOBS_FULL_COLUMNS)
            dt.cursor_type = "row"
        except NoMatches:
            logging.getLogger(__name__).debug(
                "JobsPanel.on_mount: full jobs table not yet mounted"
            )
        self.refresh_jobs()

    def compose(self) -> ComposeResult:
        yield DataTable(id="jobs-table-full")

    def refresh_jobs(self):
        """Refresh the full jobs table with all recent jobs."""
        if not self.state:
            return
        try:
            dt = self.query_one("#jobs-table-full", DataTable)
            _populate_full_jobs_table(dt, self.state)
        except NoMatches:
            logging.getLogger(__name__).debug(
                "JobsPanel.refresh_jobs: full jobs table missing during refresh"
            )


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
            # Chart widgets may not be present yet
            # (e.g., during initial layout);
            # safely ignore missing targets when refreshing charts.
            logging.getLogger(__name__).debug(
                "ChartsPanel.refresh_charts: chart widgets not found; skipping update"
            )

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
            text.append(
                bar_padded,
                style="#8a9a7b" if count > 0 else "#393836",
            )
            text.append(f" {count:3d}\n", style="#737c73")
        return text

    def _render_sources_chart(self) -> Text:
        """Render job sources distribution chart."""
        text = Text()
        if not self.state:
            text.append("No data available")
            return text

        colors = _build_semantic_color_palette(_get_active_theme(self))
        source_styles = {
            "secondary": colors["source_ws"],
            "accent": colors["source_email"],
            "primary": colors["source_web"],
            "success": colors["source_rss"],
            "text-muted": colors["timestamp"],
        }

        jobs = self.state.get_recent_jobs(limit=1000)
        sources = {key: 0 for key in SOURCE_BUCKET_CONFIG}
        for job in jobs:
            bucket = _normalize_source(job.get("source"))
            sources[bucket] += 1

        total = sum(sources.values()) or 1
        max_count = max(sources.values()) if sources else 1
        if max_count == 0:
            max_count = 1

        for bucket_key, bucket in SOURCE_BUCKET_CONFIG.items():
            count = sources.get(bucket_key, 0)
            pct = (count / total) * 100 if total > 0 else 0
            bar_width = int((count / max_count) * 15) if max_count > 0 else 0
            bar = "█" * bar_width
            bar_padded = bar.ljust(15, "░")
            label = bucket["label"]
            color = source_styles.get(bucket["color"], colors["default"])
            if count <= 0:
                color = "#393836"
            text.append(f"{label:10s} ", style="#737c73")
            text.append(bar_padded, style=color)
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

        # Calculate cumulative value over the most recent 20 jobs
        cumulative = 0
        values = []
        recent_jobs = jobs[:20]
        for job in reversed(recent_jobs):
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
    DEFAULT_THEME_NAME = "nord"
    DASHBOARD_PANEL_MIN_WIDTH = 44
    DASHBOARD_GRID_CHROME_WIDTH = 12
    DASHBOARD_CONTENT_FULL_HEIGHT = 22
    COMMAND_ALIASES: ClassVar[dict[str, str]] = {
        "?": "help",
        "h": "help",
        "c": "check",
        "p": "pause",
        "r": "resume",
        "n": "notify",
        "notifytest": "notify",
        "q": "quit",
        "exit": "quit",
        "cfg": "config",
        "config": "config",
        "configure": "config",
        "settings": "config",
        "mail": "setup-email",
        "email": "setup-email",
        "site": "setup-website",
        "web": "setup-website",
    }
    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("c", "check", "Check"),
        Binding("p", "pause", "Pause"),
        Binding("?", "help", "Help"),
    ]

    def __init__(
        self,
        config: AppConfig,
        state: AppState,
        watcher: GengoWatcher,
        stats: StatsManager,
        ui_log_handler: UILoggingHandler | None = None,
        api_thread: threading.Thread | None = None,
        api_host: str | None = None,
        api_port: int | None = None,
    ):
        super().__init__()
        self.config = config
        self.state = state
        self.watcher = watcher
        self.stats = stats
        self._ui_log_handler = ui_log_handler
        self._initializing_theme = True
        self._persist_theme_changes = True
        self.theme = self._configured_theme_name()
        self._initializing_theme = False
        self._log_source = cast(
            logging.Logger,
            getattr(self.watcher, "logger", logging.getLogger("gengowatcher")),
        )
        self._textual_log_handler = TextualLogHandler(
            self, ui_thread_id=threading.get_ident()
        )
        self._logging_attached = False
        self._job_added_callback = self._on_job_added_from_thread
        self._buffered_logs_replayed = False
        self._api_thread = api_thread
        self._api_host = api_host or getattr(api_thread, "gengowatcher_api_host", None)
        self._api_port = api_port or getattr(api_thread, "gengowatcher_api_port", None)
        self._api_server = getattr(api_thread, "gengowatcher_api_server", None)

        # Register callback for when new jobs are detected
        self.watcher.on_job_added_callback = self._job_added_callback

    def _on_job_added_from_thread(self, _job_data: dict):
        """Called from watcher thread when a new job is added."""
        try:
            self.call_from_thread(self._refresh_all_panels)
        except RuntimeError:
            pass

    def _refresh_all_panels(self):
        """Refresh relevant data panels when a new job is detected."""
        # Determine which tab is currently active so we only refresh visible
        # panels.
        try:
            tabbed_content = self.query_one(TabbedContent)
            active_tab_id = tabbed_content.active
        except NoMatches:
            # If TabbedContent can't be found, fall back to refreshing
            # dashboard widgets.
            active_tab_id = None

        # Widgets that live on the dashboard tab.
        dashboard_widgets = self._dashboard_refresh_targets()

        widgets_to_refresh = []

        # When no active tab is known, or when the dashboard is active,
        # refresh the dashboard widgets to keep the main view up to date.
        if active_tab_id in (None, "dashboard"):
            widgets_to_refresh.extend(dashboard_widgets)

        # Only refresh widgets belonging to the currently active non-dashboard
        # tab.
        if active_tab_id == "jobs":
            widgets_to_refresh.append((JobsPanel, "refresh_jobs"))
        elif active_tab_id == "charts":
            widgets_to_refresh.append((ChartsPanel, "refresh_charts"))
        elif active_tab_id == "telemetry":
            widgets_to_refresh.append((TelemetryTab, "refresh_telemetry"))
        elif active_tab_id == "api":
            widgets_to_refresh.append((ApiTab, "refresh_api"))

        for widget_class, method_name in widgets_to_refresh:
            self._refresh_widget(widget_class, method_name)

    def _refresh_widget(
        self,
        widget_class,
        method_name: str,
        *,
        missing_level: int = logging.DEBUG,
    ) -> None:
        """Attempt to refresh a specific widget and log when it's missing."""
        widget_name = (
            widget_class
            if isinstance(widget_class, str)
            else getattr(widget_class, "__name__", str(widget_class))
        )
        try:
            widget = self.query_one(widget_class)
        except NoMatches:
            logging.getLogger(__name__).log(
                missing_level,
                "Widget %s missing while refreshing %s",
                widget_name,
                method_name,
            )
            return

        method = getattr(widget, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                logging.getLogger(__name__).warning(
                    "Failed refreshing %s via %s",
                    widget_name,
                    method_name,
                    exc_info=True,
                )
        else:
            logging.getLogger(__name__).warning(
                "Widget %s has no method %s",
                widget_name,
                method_name,
            )

    def _setup_logging(self):
        if self._logging_attached:
            return
        self._log_source.addHandler(self._textual_log_handler)
        self._logging_attached = True

    def _replay_buffered_logs(self) -> None:
        if self._buffered_logs_replayed or self._ui_log_handler is None:
            return

        queued_logs = list(getattr(self._ui_log_handler, "log_queue", ()))
        for entry in queued_logs:
            if not isinstance(entry, Text):
                continue
            self._textual_log_handler.append_log("#activity-log", entry)
            self._textual_log_handler.append_log("#activity-log-full", entry)
            self._textual_log_handler.append_log("#output-log", entry)

        self._buffered_logs_replayed = True

    def on_unmount(self) -> None:
        """Detach callbacks and log handlers owned by this app instance."""
        current_callback = getattr(self.watcher, "on_job_added_callback", None)
        if current_callback is self._job_added_callback:
            self.watcher.on_job_added_callback = None
        if self._logging_attached:
            self._log_source.removeHandler(self._textual_log_handler)
            self._logging_attached = False

    def on_mount(self) -> None:
        """Initialize the jobs table with columns when the app mounts."""
        self._setup_logging()
        self._replay_buffered_logs()
        logging.getLogger(__name__).debug(
            "TUI mounted: size=%sx%s theme=%s",
            self.size.width,
            self.size.height,
            self.theme,
        )
        self._refresh_responsive_layout()
        self.call_after_refresh(self._refresh_responsive_layout)
        self.call_after_refresh(self._force_initial_repaint)
        self._setup_jobs_table()
        self._refresh_dashboard_panels()
        self.set_interval(1.0, self._refresh_dashboard_panels)
        self.call_after_refresh(self._focus_command_input)

    def _force_initial_repaint(self) -> None:
        try:
            self.refresh(repaint=True, layout=True)
            self.screen.refresh(repaint=True, layout=True)
        except Exception:
            logging.getLogger(__name__).debug(
                "Initial TUI repaint failed",
                exc_info=True,
            )

    def _focus_command_input(self) -> None:
        try:
            self.query_one(CommandInput).focus()
        except NoMatches:
            pass

    def on_resize(self, event: events.Resize) -> None:
        """Update responsive layout classes when the terminal changes size."""
        self._apply_responsive_layout(event.size.width, event.size.height)
        self.call_after_refresh(self._refresh_responsive_layout)

    def _configured_theme_name(self) -> str:
        """Return the saved theme when valid, otherwise the app default."""
        try:
            configured = self.config.get("UI", "theme_name")
        except Exception:
            configured = None

        theme_name = str(configured or self.DEFAULT_THEME_NAME)
        if theme_name in self.available_themes:
            return theme_name
        return self.DEFAULT_THEME_NAME

    def _persist_theme_name(self, theme_name: str) -> None:
        if theme_name not in self.available_themes:
            return
        try:
            current_theme = self.config.get("UI", "theme_name")
            if str(current_theme or "") == theme_name:
                return
            self.config.set("UI", "theme_name", theme_name)
            self.config.save_config()
        except Exception:
            logging.getLogger(__name__).warning(
                "Failed to persist UI theme %s",
                theme_name,
                exc_info=True,
            )

    def _watch_theme(self, theme_name: str) -> None:
        """Apply and persist theme changes made through Textual."""
        super()._watch_theme(theme_name)
        if getattr(self, "_persist_theme_changes", False) and not getattr(
            self, "_initializing_theme", False
        ):
            self._persist_theme_name(theme_name)

    def watch_theme(self, theme_name: str) -> None:
        """Compatibility hook used by tests and older Textual integrations."""
        if not getattr(self, "_initializing_theme", False):
            self._persist_theme_name(theme_name)

    def _refresh_responsive_layout(self) -> None:
        """Apply responsive classes from the measured dashboard content area."""
        width = self.size.width
        height = self.size.height
        try:
            dashboard_content = self.query_one("#dashboard-content")
        except NoMatches:
            pass
        except Exception:
            pass
        else:
            width = dashboard_content.size.width or width
            height = dashboard_content.size.height or height
        self._apply_responsive_layout(width, height)

    def _apply_responsive_layout(self, width: int, height: int) -> None:
        """Toggle layout classes derived from dashboard content geometry."""
        two_column_width = (
            self.DASHBOARD_PANEL_MIN_WIDTH * 2 + self.DASHBOARD_GRID_CHROME_WIDTH
        )
        needs_compact = height < self.DASHBOARD_CONTENT_FULL_HEIGHT
        self.set_class(width <= two_column_width or needs_compact, "dashboard-stacked")
        self.set_class(needs_compact, "dashboard-compact")

    def _dashboard_refresh_targets(self) -> list[tuple[type, str]]:
        """Return the required refresh targets for mounted dashboard widgets."""
        return [
            (MetricsRow, "refresh_metrics"),
            (JobsPreview, "refresh_jobs"),
            (HourlyActivity, "refresh_hourly"),
            (TelemetryPanel, "refresh_telemetry"),
        ]

    def _run_command(self, command: str) -> None:
        try:
            parts = shlex.split(command)
        except ValueError as error:
            self._write_command_output(f"Command parse error: {error}", logging.ERROR)
            return
        if not parts:
            return

        normalized = self.COMMAND_ALIASES.get(parts[0].lower(), parts[0].lower())
        args = parts[1:]
        if normalized == "check":
            event = getattr(self.watcher, "check_now_event", None)
            setter = getattr(event, "set", None)
            if callable(setter):
                setter()
            self._write_command_output("Check requested.")
        elif normalized == "pause":
            pause = getattr(self.watcher, "pause_monitoring", None)
            if callable(pause):
                pause()
            self._write_command_output("Watcher paused.")
        elif normalized == "resume":
            resume = getattr(self.watcher, "resume_monitoring", None)
            if callable(resume):
                resume()
            self._write_command_output("Watcher resumed.")
        elif normalized == "notify":
            notify = getattr(self.watcher, "run_notify_test", None)
            if callable(notify):
                notify()
            self._write_command_output("Notification test requested.")
        elif normalized == "ping":
            queue_test = getattr(self.watcher, "queue_websocket_test_command", None)
            if callable(queue_test):
                queue_test("ping")
            self._write_command_output("WebSocket ping test queued.")
        elif normalized == "quit":
            self.action_quit()
        elif normalized == "help":
            self._show_command_help()
        elif normalized in {"config", "get", "set", "list"}:
            self._run_config_command(normalized, args)
        elif normalized == "api":
            self._run_api_command(args)
        else:
            self._write_command_output(
                f"Unknown command: {parts[0]}. Type help for commands.",
                logging.WARNING,
            )

    def _write_command_output(self, message: str, level: int = logging.INFO) -> None:
        def write_direct() -> None:
            self._textual_log_handler.write_log(message, level)

        try:
            ui_thread_id = getattr(self._textual_log_handler, "ui_thread_id", None)
            if ui_thread_id is not None and ui_thread_id != threading.get_ident():
                self.call_from_thread(write_direct)
            else:
                write_direct()
        except Exception:
            logging.getLogger(__name__).log(level, message)

    def _show_command_help(self) -> None:
        for line in (
            "Commands:",
            "  check                         trigger an immediate RSS check",
            "  pause|resume                  pause or resume RSS checks",
            "  notify                        send a test notification",
            "  api status|start|enable|disable",
            "  config list [Section]",
            "  get Section.key",
            "  set Section.key value",
            "  quit",
        ):
            self._write_command_output(line)

    @staticmethod
    def _is_sensitive_config_key(key: str) -> bool:
        lowered = key.lower()
        return any(
            marker in lowered
            for marker in ("secret", "token", "session", "password", "auth", "key")
        )

    def _format_config_value(self, key: str, value: object) -> str:
        if self._is_sensitive_config_key(key) and value:
            text = str(value)
            if len(text) <= 8:
                return "***"
            return f"{text[:4]}...{text[-4:]}"
        return repr(value)

    def _config_snapshot(self) -> dict[str, dict[str, object]]:
        lister = getattr(self.config, "list_all", None)
        if callable(lister):
            snapshot = lister()
            if isinstance(snapshot, dict):
                return snapshot
        return {}

    def _parse_config_reference(
        self,
        args: list[str],
    ) -> tuple[str, str, list[str]] | None:
        if not args:
            self._write_command_output("Missing config key.", logging.ERROR)
            return None
        if "." in args[0]:
            section, key = args[0].split(".", 1)
            rest = args[1:]
        elif len(args) >= 2:
            section, key = args[0], args[1]
            rest = args[2:]
        else:
            self._write_command_output(
                "Use Section.key or Section key.",
                logging.ERROR,
            )
            return None
        section = section.strip()
        key = key.strip()
        if not section or not key:
            self._write_command_output("Invalid config key.", logging.ERROR)
            return None
        return section, key, rest

    def _coerce_config_value(
        self,
        section: str,
        key: str,
        raw_value: str,
        current_value: object,
    ) -> object:
        if isinstance(current_value, bool):
            return AppConfig.coerce_bool(raw_value)
        if isinstance(current_value, int) and not isinstance(current_value, bool):
            return int(raw_value)
        if isinstance(current_value, float):
            return float(raw_value)
        if isinstance(current_value, list):
            if raw_value.strip().startswith("["):
                import ast

                parsed = ast.literal_eval(raw_value)
                if not isinstance(parsed, list):
                    raise ValueError("expected a list value")
                return parsed
            return [item.strip() for item in raw_value.split(",") if item.strip()]
        return raw_value

    def _save_config_value(self, section: str, key: str, value: object) -> None:
        self.config.set(section, key, value)
        for validator_name in (
            "_validate_auto_accept_config",
            "_validate_native_browser_config",
        ):
            validator = getattr(self.config, validator_name, None)
            if callable(validator):
                validator()
        self.config.save_config()

    def _run_config_command(self, command: str, args: list[str]) -> None:
        action = command
        if command == "config":
            action = args[0].lower() if args else "help"
            args = args[1:] if args else []
            if action not in {"help", "list", "get", "set"}:
                if len(args) == 0:
                    args = [action]
                    action = "list"
                elif len(args) == 1:
                    args = [action, *args]
                    action = "get"
                else:
                    args = [action, *args]
                    action = "set"

        if action in {"help", "?"}:
            self._write_command_output("config list [Section]")
            self._write_command_output("get Section.key")
            self._write_command_output("set Section.key value")
            return

        snapshot = self._config_snapshot()
        if action == "list":
            if not args:
                sections = ", ".join(sorted(snapshot))
                self._write_command_output(f"Config sections: {sections}")
                return
            section = args[0]
            values = snapshot.get(section)
            if not isinstance(values, dict):
                self._write_command_output(
                    f"Unknown config section: {section}", logging.ERROR
                )
                return
            for key, value in values.items():
                self._write_command_output(
                    f"{section}.{key} = {self._format_config_value(key, value)}"
                )
            return

        parsed = self._parse_config_reference(args)
        if parsed is None:
            return
        section, key, rest = parsed
        values = snapshot.get(section)
        if not isinstance(values, dict) or key not in values:
            self._write_command_output(
                f"Unknown config key: {section}.{key}", logging.ERROR
            )
            return

        if action == "get":
            value = self.config.get(section, key, fallback=values.get(key))
            self._write_command_output(
                f"{section}.{key} = {self._format_config_value(key, value)}"
            )
            return

        if action == "set":
            if not rest:
                self._write_command_output(
                    "Missing value for set command.", logging.ERROR
                )
                return
            raw_value = " ".join(rest)
            try:
                value = self._coerce_config_value(section, key, raw_value, values[key])
                self._save_config_value(section, key, value)
            except Exception as error:
                self._write_command_output(
                    f"Failed setting {section}.{key}: {error}",
                    logging.ERROR,
                )
                return
            self._write_command_output(
                f"Set {section}.{key} = {self._format_config_value(key, value)}"
            )
            if section == "WebServer":
                self._refresh_api_bind_from_config()
            return

        self._write_command_output(f"Unknown config action: {action}", logging.WARNING)

    def _refresh_api_bind_from_config(self) -> tuple[str, int]:
        host = str(
            self.config.get("WebServer", "host", fallback=self._api_host or "127.0.0.1")
            or "127.0.0.1"
        )
        try:
            port = int(
                self.config.get("WebServer", "port", fallback=self._api_port or 8000)
                or 8000
            )
        except (TypeError, ValueError):
            port = 8000
        self._api_host = host
        self._api_port = port
        return host, port

    def _api_port_open(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            return False

    def _api_is_running(self) -> bool:
        host, port = self._refresh_api_bind_from_config()
        thread_running = bool(self._api_thread and self._api_thread.is_alive())
        return thread_running or self._api_port_open(host, port)

    def _set_web_server_enabled(self, enabled: bool) -> None:
        self._save_config_value("WebServer", "enabled", enabled)

    def _start_api_server(self) -> None:
        host, port = self._refresh_api_bind_from_config()
        if self._api_is_running():
            self._write_command_output(f"API already reachable at http://{host}:{port}")
            return

        try:
            from .web import start_web_server_thread

            thread = start_web_server_thread(
                host=host,
                port=port,
                config=self.config,
                state=self.state,
                logger=self._log_source,
                watcher=self.watcher,
                start_watcher_thread=False,
            )
        except Exception as error:
            self._write_command_output(f"API server failed: {error}", logging.ERROR)
            return

        self._api_thread = thread
        self._api_server = getattr(thread, "gengowatcher_api_server", None)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            startup_error = getattr(self._api_server, "startup_error", None)
            if startup_error is not None:
                self._write_command_output(
                    f"API server failed: {startup_error}",
                    logging.ERROR,
                )
                return
            if self._api_port_open(host, port):
                self._write_command_output(f"API started at http://{host}:{port}")
                return
            time.sleep(0.1)

        self._write_command_output(
            f"API start requested at http://{host}:{port}; still waiting for the port.",
            logging.WARNING,
        )

    def _stop_api_server(self) -> bool:
        server = self._api_server or getattr(
            self._api_thread,
            "gengowatcher_api_server",
            None,
        )
        if server is None:
            return False
        stopper = getattr(server, "stop", None)
        if not callable(stopper):
            return False
        stopped = bool(stopper(timeout=5.0))
        if stopped:
            self._api_thread = None
            self._api_server = None
        return stopped

    def _run_api_command(self, args: list[str]) -> None:
        action = args[0].lower() if args else "status"
        host, port = self._refresh_api_bind_from_config()
        if action in {"help", "?"}:
            self._write_command_output("api status")
            self._write_command_output("api start")
            self._write_command_output("api enable")
            self._write_command_output("api disable")
            return
        if action == "status":
            enabled = self.config.getboolean("WebServer", "enabled", fallback=False)
            state = "running" if self._api_is_running() else "stopped"
            self._write_command_output(
                f"API {state}; enabled={enabled}; url=http://{host}:{port}"
            )
            return
        if action in {"start", "enable"}:
            try:
                self._set_web_server_enabled(True)
            except Exception as error:
                self._write_command_output(
                    f"Failed enabling API: {error}", logging.ERROR
                )
                return
            self._start_api_server()
            return
        if action in {"disable", "stop"}:
            try:
                self._set_web_server_enabled(False)
            except Exception as error:
                self._write_command_output(
                    f"Failed disabling API: {error}", logging.ERROR
                )
                return
            if self._stop_api_server():
                self._write_command_output("API stopped and disabled.")
            elif self._api_is_running():
                self._write_command_output(
                    "API disabled for next launch; the live server was not started by this TUI.",
                    logging.WARNING,
                )
            else:
                self._write_command_output("API disabled.")
            return
        self._write_command_output(f"Unknown API command: {action}", logging.WARNING)

    def action_check(self) -> None:
        """Trigger an immediate watcher check."""
        self._run_command("check")

    def action_quit(self) -> None:
        """Quit the Textual app."""
        self.exit()

    @on(Input.Submitted)
    def _on_command_submitted(self, event: Input.Submitted) -> None:
        if not isinstance(event.input, CommandInput):
            return
        command = str(event.value or "").strip()
        event.input.value = ""
        event.stop()
        if command:
            self._run_command(command)

    def _refresh_dashboard_panels(self) -> None:
        """Refresh dashboard widgets that depend on live/persisted state."""
        # Drain TUI event store (wired to event bus)
        try:
            from .tui_store import TuiStore

            store = TuiStore.get_instance()
            store.drain_events()
        except Exception as e:
            logging.getLogger(__name__).debug(f"TuiStore drain failed: {e}")

        for widget_class, method_name in self._dashboard_refresh_targets():
            self._refresh_widget(
                widget_class,
                method_name,
                missing_level=logging.WARNING,
            )

    def _setup_jobs_table(self) -> None:
        """Set up the jobs DataTable with columns."""
        try:
            from textual.widgets import DataTable

            dt = self.query_one("#jobs-table-full", DataTable)
            _ensure_data_table_columns(dt, JOBS_FULL_COLUMNS)
            dt.cursor_type = "row"
        except NoMatches:
            pass  # Widget not mounted yet
        except Exception as e:
            logging.getLogger(__name__).error(
                "Failed to set up jobs table: %s", e, exc_info=True
            )

    def _load_jobs_into_table(self) -> None:
        """Load current jobs from state into the jobs DataTable."""
        if not self.state:
            return
        try:
            panel = self.query_one(JobsPanel)
        except NoMatches:
            try:
                from textual.widgets import DataTable

                dt = self.query_one("#jobs-table-full", DataTable)
                _populate_full_jobs_table(dt, self.state)
            except NoMatches:
                pass  # Widget not mounted yet
            except Exception:
                logging.getLogger(__name__).warning(
                    "Failed loading jobs into table",
                    exc_info=True,
                )
        else:
            panel.refresh_jobs()

    @on(TabbedContent.TabActivated)
    def _refresh_tab_content(self, event: TabbedContent.TabActivated) -> None:
        pane_id = event.pane.id
        if pane_id == "jobs":
            self._load_jobs_into_table()
        elif pane_id == "activity":
            self._refresh_widget("#activity-log-full", "refresh")
        elif pane_id == "output":
            self._refresh_widget("#output-log", "refresh")
        elif pane_id == "charts":
            self._refresh_widget("#charts-content", "refresh")
        elif pane_id == "telemetry":
            self._refresh_widget(TelemetryTab, "refresh_telemetry")
        elif pane_id == "api":
            self._refresh_widget(ApiTab, "refresh_api")

    def compose(self) -> ComposeResult:
        # 1. Title Bar
        """
        Build and yield the main UI layout: title bar, tabbed content
        (Dashboard, Jobs, Activity, Output, Charts, Stats), and the
        bottom input/footer.

        Returns:
            ComposeResult: Yields the top TitleBar, TabbedContent with
            dashboard panels and other tab panes, and the bottom Input
            and Footer widgets.
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
                        yield HourlyActivity(
                            stats=self.stats,
                            state=self.state,
                        )
                        yield ConfigPreview(config=self.config)
                        yield TelemetryPanel(watcher=self.watcher)

                    yield ActivityPreview()

            with TabPane("Jobs", id="jobs"):
                yield JobsPanel(state=self.state)
            with TabPane("Activity", id="activity"):
                yield RichLog(
                    id="activity-log-full",
                    markup=True,
                    max_lines=ACTIVITY_LOG_MAX_LINES,
                )
            with TabPane("Output", id="output"):
                yield RichLog(
                    id="output-log",
                    markup=True,
                    max_lines=OUTPUT_LOG_MAX_LINES,
                )
            with TabPane("Charts", id="charts"):
                yield Static("Charts Content", id="charts-content")
            with TabPane("Telemetry", id="telemetry"):
                yield TelemetryTab(watcher=self.watcher)
            with TabPane("API", id="api"):
                yield ApiTab(watcher=self.watcher)

        # 3. Input & Footer
        yield CommandInput(placeholder="> help_")
        yield Footer()

    def call_from_thread(self, func, *args, **kwargs):
        # Delegate to the parent implementation and return its result
        return super().call_from_thread(func, *args, **kwargs)


class TextualLogHandler(logging.Handler):
    """Redirect logs to ActivityPreview with Rich markup coloring."""

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
            r"\b(?:Japanese|English|Chinese|Korean|German|French|Spanish)"
            r"[→\->](?:Japanese|English|Chinese|Korean|German|French|"
            r"Spanish)\b",
            "lang_pair",
        ),
        # URLs
        (r"https?://[^\s]+", "url"),
        # Success words
        (
            r"\b(?:found|accepted|success|connected|started|completed|ok|" r"passed)\b",
            "success",
        ),
        # Error words
        (
            r"\b(?:error|failed|failure|exception|crash|rejected|timeout|" r"denied)\b",
            "error_word",
        ),
        # Warning words
        (
            r"\b(?:warning|warn|caution|retry|retrying|slow|delayed)\b",
            "warning_word",
        ),
        # Source indicators
        (r"\b(?:websocket|ws|socket)\b", "source_ws"),
        (r"\b(?:webhook|webhooks|hook|hooks)\b", "source_ws"),
        (r"\b(?:email|imap|mail)\b", "source_email"),
        (r"\b(?:rss|feed)\b", "source_rss"),
        (r"\b(?:web|http|browser|scrape)\b", "source_web"),
        # Numbers (but not part of other patterns)
        (r"\b\d+(?:\.\d+)?\b", "number"),
    ]

    def __init__(self, app, ui_thread_id: int | None = None):
        super().__init__()
        self.app = app
        self.ui_thread_id = ui_thread_id
        # Compile patterns
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), color_key)
            for pattern, color_key in self.PATTERNS
        ]

    def emit(self, record):
        try:
            msg = self._format_ui_message(record)
            level = record.levelno
            if (
                self.ui_thread_id is not None
                and self.ui_thread_id == threading.get_ident()
            ):
                self.write_log(msg, level)
            else:
                self.app.call_from_thread(self.write_log, msg, level)
        except Exception:
            pass  # Logging failures should not crash the app

    def _format_ui_message(self, record: logging.LogRecord) -> str:
        """Render a concise single-line message for TUI log panels."""
        message = str(record.getMessage()).replace("\r", " ").replace("\n", " ")

        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            if exc_type is not None:
                exc_name = exc_type.__name__
                exc_text = str(exc_value).strip()
                suffix = exc_name if not exc_text else f"{exc_name}: {exc_text}"
                return f"{message} | {suffix}" if message else suffix

        return message

    def _write_to_log(self, widget_id: str, colored_text: Text) -> None:
        try:
            log = self.app.query_one(widget_id, RichLog)
            log.write(colored_text)
        except NoMatches:
            pass  # Widget not mounted yet

    def append_log(self, widget_id: str, colored_text: Text) -> None:
        """Append an already formatted log entry to a specific log widget."""
        self._write_to_log(widget_id, colored_text)

    def write_log(self, msg: str, level: int = logging.INFO):
        colored_text = self._colorize_message(msg, level)
        # Write to dashboard activity log
        self._write_to_log("#activity-log", colored_text)
        # Also write to full activity log tab
        self._write_to_log("#activity-log-full", colored_text)
        # Also write to output log for the full system output stream.
        self._write_to_log("#output-log", colored_text)

    def _colorize_message(self, msg: str, level: int) -> Text:
        """Apply Rich markup coloring based on content patterns."""
        colors = _build_semantic_color_palette(_get_active_theme(self))

        # Determine base color from log level
        color_key = self.LEVEL_COLORS.get(level, "level_info")
        base_color = colors[color_key]

        # Create text with base styling
        text = Text(msg, style=base_color)

        # Apply pattern-based highlighting
        for pattern, color_key in self._compiled_patterns:
            color = colors.get(color_key, base_color)
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
            text.stylize(colors["bracket"], start, end)

        return text
