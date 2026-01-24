# Dashboard Visual Overhaul Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform GengoWatcher TUI into a polished command-center with title bar, metric cards, status row, 4-quadrant dashboard, and Stats tab.

**Architecture:** Layered widget composition - new atomic widgets (TitleBar, MetricCard, StatusIndicator) compose into container widgets (MetricsRow, StatusRow, DashboardQuadrant). Stats tab uses dedicated `StatsManager` for historical data persistence. CSS uses Kanagawa 3-depth visual hierarchy.

**Tech Stack:** Textual 0.x, textual-plotext, Python dataclasses, JSON persistence

---

## Component Dependency Order

```
1. CSS Foundation (colors, spacing, panels)  ← No dependencies
2. TitleBar widget                           ← CSS Foundation
3. MetricCard + MetricsRow                   ← CSS Foundation
4. StatusIndicator + StatusRow               ← CSS Foundation
5. DashboardQuadrants (Activity, Jobs, Chart, Config) ← CSS + existing widgets
6. StatsManager (data layer)                 ← state.py
7. StatsPanel (Stats tab)                    ← StatsManager + CSS
8. Integration (compose refactor)            ← All above
```

---

## Task 1: CSS Foundation - Visual Hierarchy & Panel Styles

**Files:**
- Modify: `src/gengowatcher/gengo_watcher.tcss:1-314`

**Step 1.1: Add new CSS variables and base panel styles**

Add after line 24 (after existing color variables):

```css
/* ── Visual Hierarchy Depths ──────────────────────────────────────────── */
$depth-0: #16161D;              /* Deepest - screen background */
$depth-1: #1F1F28;              /* Main surface - tab panes */
$depth-2: #2A2A37;              /* Elevated - cards, panels */
$depth-3: #363646;              /* Borders, separators */

/* ── Card Accent Colors ────────────────────────────────────────────────── */
$card-found: #7E9CD8;           /* primary - blue */
$card-accepted: #98BB6C;        /* success - green */
$card-value: #DCA561;           /* warning - yellow */
$card-rate: #7AA89F;            /* accent - aqua */
$card-minword: #957FB8;         /* secondary - violet */
```

**Step 1.2: Add title bar styles**

```css
/* ══════════════════════════════════════════════════════════════════════════
   TITLE BAR
   ══════════════════════════════════════════════════════════════════════════ */

TitleBar {
    height: 3;
    background: $depth-2;
    border-left: tall $primary;
    padding: 0 2;
}

TitleBar .brand {
    color: $primary;
    text-style: bold;
}

TitleBar .session-time {
    color: $text;
}

TitleBar .clock {
    color: $text-muted;
    text-align: right;
}
```

**Step 1.3: Add metric card styles**

```css
/* ══════════════════════════════════════════════════════════════════════════
   METRIC CARDS
   ══════════════════════════════════════════════════════════════════════════ */

MetricsRow {
    height: 5;
    padding: 0 1;
    align: center middle;
}

MetricCard {
    width: 14;
    height: 3;
    background: $depth-2;
    border: round $depth-3;
    padding: 0 1;
    margin: 0 1;
}

MetricCard.found { border-left: tall $card-found; }
MetricCard.accepted { border-left: tall $card-accepted; }
MetricCard.value { border-left: tall $card-value; }
MetricCard.rate { border-left: tall $card-rate; }
MetricCard.minword { border-left: tall $card-minword; }

MetricCard .metric-value {
    color: $text;
    text-style: bold;
}

MetricCard .metric-label {
    color: $text-muted;
}
```

**Step 1.4: Add status row styles**

```css
/* ══════════════════════════════════════════════════════════════════════════
   STATUS ROW
   ══════════════════════════════════════════════════════════════════════════ */

StatusRow {
    height: 1;
    padding: 0 2;
    background: $depth-1;
}

StatusIndicator {
    width: auto;
    margin-right: 3;
}

StatusIndicator .status-icon {
    margin-right: 1;
}

StatusIndicator .status-live { color: $success; }
StatusIndicator .status-working { color: $warning; }
StatusIndicator .status-error { color: $error; }
StatusIndicator .status-idle { color: $text-muted; }
```

**Step 1.5: Add quadrant panel styles**

```css
/* ══════════════════════════════════════════════════════════════════════════
   DASHBOARD QUADRANTS
   ══════════════════════════════════════════════════════════════════════════ */

.dashboard-grid {
    layout: grid;
    grid-size: 2 2;
    grid-gutter: 1;
    padding: 1;
}

DashboardQuadrant {
    background: $depth-2;
    border: round $depth-3;
    padding: 0 1;
}

DashboardQuadrant.activity { border-left: tall $success; }
DashboardQuadrant.jobs-preview { border-left: tall $primary; }
DashboardQuadrant.chart { border-left: tall $accent; }
DashboardQuadrant.config { border-left: tall $secondary; }

DashboardQuadrant .quadrant-title {
    color: $text;
    text-style: bold;
    padding-bottom: 1;
}
```

**Step 1.6: Add stats panel styles**

```css
/* ══════════════════════════════════════════════════════════════════════════
   STATS PANEL
   ══════════════════════════════════════════════════════════════════════════ */

StatsPanel {
    padding: 1;
}

.stats-grid {
    layout: grid;
    grid-size: 2;
    grid-gutter: 1;
}

.stats-section {
    background: $depth-2;
    border: round $depth-3;
    padding: 1;
}

.stats-section.session { border-left: tall $primary; }
.stats-section.alltime { border-left: tall $secondary; }
.stats-section.source { border-left: tall $accent; }
.stats-section.language { border-left: tall $warning; }
.stats-section.times { border-left: tall $success; }

.stats-section .section-title {
    color: $text;
    text-style: bold;
    padding-bottom: 1;
}

.stats-row {
    height: 1;
}

.stats-label {
    color: $text-muted;
    width: 16;
}

.stats-value {
    color: $text;
}

.progress-bar {
    width: 100%;
    height: 1;
}

.progress-bar .bar-fill {
    background: $primary;
}

.progress-bar .bar-empty {
    background: $depth-3;
}
```

**Step 1.7: Run linter to verify CSS syntax**

Run: `cd /home/thomas/GengoWatcher && python -c "from textual.css.parse import parse_css; parse_css('src/gengowatcher/gengo_watcher.tcss')"`
Expected: No errors

**Step 1.8: Commit CSS foundation**

```bash
git add src/gengowatcher/gengo_watcher.tcss
git commit -m "feat(ui): add CSS foundation for dashboard visual overhaul"
```

---

## Task 2: TitleBar Widget

**Files:**
- Modify: `src/gengowatcher/ui_textual.py` (add after line 148, before JobsChart)

**Step 2.1: Write the TitleBar widget class**

```python
class TitleBar(Static):
    """Branded title bar with session timer and clock."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._start_time = time.time()

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("◆ GENGOWATCHER v2.0", classes="brand")
            yield Static("", id="session-time", classes="session-time")
            yield Static("", id="clock", classes="clock")

    def on_mount(self) -> None:
        self.set_interval(1.0, self._update_time)
        self._update_time()

    def _update_time(self) -> None:
        # Session duration
        elapsed = int(time.time() - self._start_time)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        session_str = f"Session: {hours}h {minutes:02d}m {seconds:02d}s"
        self.query_one("#session-time", Static).update(session_str)

        # Current time
        now = datetime.datetime.now()
        clock_str = now.strftime("%a %b %d  %H:%M:%S %Z")
        self.query_one("#clock", Static).update(clock_str)
```

**Step 2.2: Add required imports at top of file**

Ensure these imports exist (add if missing):
```python
import time
import datetime
```

**Step 2.3: Write test for TitleBar**

Create file `tests/test_title_bar.py`:

```python
"""Tests for TitleBar widget."""
import pytest
from textual.app import App, ComposeResult

from gengowatcher.ui_textual import TitleBar


class TitleBarTestApp(App):
    def compose(self) -> ComposeResult:
        yield TitleBar()


@pytest.mark.asyncio
async def test_title_bar_renders():
    """TitleBar should render brand, session time, and clock."""
    app = TitleBarTestApp()
    async with app.run_test() as pilot:
        title_bar = app.query_one(TitleBar)
        assert title_bar is not None

        # Check brand text exists
        brand = title_bar.query_one(".brand")
        assert "GENGOWATCHER" in str(brand.renderable)


@pytest.mark.asyncio
async def test_title_bar_session_time_updates():
    """Session time should be displayed."""
    app = TitleBarTestApp()
    async with app.run_test() as pilot:
        await pilot.pause()  # Allow timer to tick
        session_time = app.query_one("#session-time")
        content = str(session_time.renderable)
        assert "Session:" in content
```

**Step 2.4: Run test to verify**

Run: `cd /home/thomas/GengoWatcher && pytest tests/test_title_bar.py -v`
Expected: 2 tests PASS

**Step 2.5: Commit TitleBar**

```bash
git add src/gengowatcher/ui_textual.py tests/test_title_bar.py
git commit -m "feat(ui): add TitleBar widget with session timer and clock"
```

---

## Task 3: MetricCard & MetricsRow Widgets

**Files:**
- Modify: `src/gengowatcher/ui_textual.py` (add after TitleBar class)

**Step 3.1: Write MetricCard widget**

```python
class MetricCard(Static):
    """Individual metric display card with accent border."""

    def __init__(self, label: str, value: str = "0", card_class: str = "", **kwargs):
        super().__init__(**kwargs)
        self._label = label
        self._value = value
        if card_class:
            self.add_class(card_class)

    def compose(self) -> ComposeResult:
        yield Static(self._value, classes="metric-value", id=f"metric-{self._label.lower()}-value")
        yield Static(self._label, classes="metric-label")

    def update_value(self, value: str) -> None:
        """Update the displayed metric value."""
        self._value = value
        try:
            self.query_one(".metric-value", Static).update(value)
        except Exception:
            pass  # Widget may not be mounted yet
```

**Step 3.2: Write MetricsRow container**

```python
class MetricsRow(Horizontal):
    """Container for the 5 metric cards."""

    def __init__(self, state: "AppState", **kwargs):
        super().__init__(**kwargs)
        self._state = state

    def compose(self) -> ComposeResult:
        yield MetricCard("Found", "0", card_class="found", id="card-found")
        yield MetricCard("Accepted", "0", card_class="accepted", id="card-accepted")
        yield MetricCard("Value", "$0.00", card_class="value", id="card-value")
        yield MetricCard("Rate", "0/hr", card_class="rate", id="card-rate")
        yield MetricCard("Min/Word", "$0.00", card_class="minword", id="card-minword")

    def refresh_metrics(self) -> None:
        """Update all metric values from state."""
        jobs = self._state.get_recent_jobs(limit=1000)
        found = len(jobs)
        accepted = sum(1 for j in jobs if j.get("accepted", False))
        total_value = sum(j.get("reward", 0) for j in jobs)

        self.query_one("#card-found", MetricCard).update_value(str(found))
        self.query_one("#card-accepted", MetricCard).update_value(str(accepted))
        self.query_one("#card-value", MetricCard).update_value(f"${total_value:.2f}")

        # Calculate rate (jobs per hour based on session time)
        # Simplified: use state's sparkline data length as proxy
        sparkline_len = len(self._state.sparkline_data)
        rate = found / max(sparkline_len / 60, 1) if sparkline_len > 0 else 0
        self.query_one("#card-rate", MetricCard).update_value(f"~{rate:.1f}/hr")
```

**Step 3.3: Write tests for MetricCard and MetricsRow**

Create file `tests/test_metric_cards.py`:

```python
"""Tests for MetricCard and MetricsRow widgets."""
import pytest
from unittest.mock import MagicMock
from textual.app import App, ComposeResult

from gengowatcher.ui_textual import MetricCard, MetricsRow


class MetricCardTestApp(App):
    def compose(self) -> ComposeResult:
        yield MetricCard("Found", "42", card_class="found")


class MetricsRowTestApp(App):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        yield MetricsRow(self._state)


@pytest.mark.asyncio
async def test_metric_card_displays_value():
    """MetricCard should display label and value."""
    app = MetricCardTestApp()
    async with app.run_test() as pilot:
        card = app.query_one(MetricCard)
        value_widget = card.query_one(".metric-value")
        label_widget = card.query_one(".metric-label")
        assert "42" in str(value_widget.renderable)
        assert "Found" in str(label_widget.renderable)


@pytest.mark.asyncio
async def test_metric_card_update_value():
    """MetricCard.update_value should change displayed value."""
    app = MetricCardTestApp()
    async with app.run_test() as pilot:
        card = app.query_one(MetricCard)
        card.update_value("99")
        await pilot.pause()
        value_widget = card.query_one(".metric-value")
        assert "99" in str(value_widget.renderable)


@pytest.mark.asyncio
async def test_metrics_row_renders_five_cards():
    """MetricsRow should contain 5 metric cards."""
    state = MagicMock()
    state.get_recent_jobs.return_value = []
    state.sparkline_data = []

    app = MetricsRowTestApp(state)
    async with app.run_test() as pilot:
        cards = app.query(MetricCard)
        assert len(cards) == 5
```

**Step 3.4: Run tests**

Run: `cd /home/thomas/GengoWatcher && pytest tests/test_metric_cards.py -v`
Expected: 3 tests PASS

**Step 3.5: Commit**

```bash
git add src/gengowatcher/ui_textual.py tests/test_metric_cards.py
git commit -m "feat(ui): add MetricCard and MetricsRow widgets"
```

---

## Task 4: StatusIndicator & StatusRow Widgets

**Files:**
- Modify: `src/gengowatcher/ui_textual.py` (add after MetricsRow class)

**Step 4.1: Write StatusIndicator widget**

```python
class StatusIndicator(Static):
    """Single status indicator with icon, label, and live state."""

    ICONS = {
        "websocket": "●",
        "email": "◉",
        "website": "◎",
        "captcha": "⧗",
        "workflow": "⇄",
    }

    STATES = {
        "live": ("∿∿∿ Live", "status-live"),
        "connecting": ("◐ Connecting", "status-working"),
        "polling": ("↻ Polling", "status-working"),
        "idle": ("○ Idle", "status-idle"),
        "error": ("✗ Error", "status-error"),
        "ready": ("Ready", "status-live"),
        "solving": ("Solving...", "status-working"),
        "auto": ("Auto", "status-live"),
        "manual": ("Manual", "status-idle"),
    }

    def __init__(self, name: str, initial_state: str = "idle", **kwargs):
        super().__init__(**kwargs)
        self._name = name
        self._state = initial_state
        self._icon = self.ICONS.get(name.lower(), "●")

    def compose(self) -> ComposeResult:
        state_text, state_class = self.STATES.get(self._state, ("Unknown", "status-idle"))
        yield Static(f"{self._icon} {self._name.upper()}", classes="status-icon")
        yield Static(state_text, classes=f"status-text {state_class}", id=f"status-{self._name.lower()}")

    def set_state(self, state: str) -> None:
        """Update the indicator state."""
        self._state = state
        state_text, state_class = self.STATES.get(state, ("Unknown", "status-idle"))
        try:
            status_widget = self.query_one(f"#status-{self._name.lower()}", Static)
            status_widget.update(state_text)
            # Update classes for color
            status_widget.remove_class("status-live", "status-working", "status-error", "status-idle")
            status_widget.add_class(state_class)
        except Exception:
            pass


class StatusRow(Horizontal):
    """Row of status indicators for all monitored sources."""

    def __init__(self, watcher: "GengoWatcher", **kwargs):
        super().__init__(**kwargs)
        self._watcher = watcher

    def compose(self) -> ComposeResult:
        yield StatusIndicator("WebSocket", "idle", id="ind-websocket")
        yield StatusIndicator("Email", "idle", id="ind-email")
        yield StatusIndicator("Website", "idle", id="ind-website")
        yield StatusIndicator("Captcha", "ready", id="ind-captcha")
        yield StatusIndicator("Workflow", "auto", id="ind-workflow")

    def refresh_status(self) -> None:
        """Update all indicators from watcher state."""
        # WebSocket
        ws_state = "live" if self._watcher.websocket_connected else "idle"
        self.query_one("#ind-websocket", StatusIndicator).set_state(ws_state)

        # Email
        email_enabled = getattr(self._watcher.email_monitor, "enabled", False) if hasattr(self._watcher, "email_monitor") else False
        email_state = "polling" if email_enabled else "idle"
        self.query_one("#ind-email", StatusIndicator).set_state(email_state)

        # Website
        web_enabled = getattr(self._watcher.website_monitor, "enabled", False) if hasattr(self._watcher, "website_monitor") else False
        web_state = "polling" if web_enabled else "idle"
        self.query_one("#ind-website", StatusIndicator).set_state(web_state)
```

**Step 4.2: Write tests**

Create file `tests/test_status_indicators.py`:

```python
"""Tests for StatusIndicator and StatusRow widgets."""
import pytest
from unittest.mock import MagicMock
from textual.app import App, ComposeResult

from gengowatcher.ui_textual import StatusIndicator, StatusRow


class StatusIndicatorTestApp(App):
    def compose(self) -> ComposeResult:
        yield StatusIndicator("WebSocket", "live")


class StatusRowTestApp(App):
    def __init__(self, watcher):
        super().__init__()
        self._watcher = watcher

    def compose(self) -> ComposeResult:
        yield StatusRow(self._watcher)


@pytest.mark.asyncio
async def test_status_indicator_displays_icon_and_state():
    """StatusIndicator should show icon and state text."""
    app = StatusIndicatorTestApp()
    async with app.run_test() as pilot:
        indicator = app.query_one(StatusIndicator)
        # Check icon is rendered
        icon_widget = indicator.query_one(".status-icon")
        assert "●" in str(icon_widget.renderable)
        assert "WEBSOCKET" in str(icon_widget.renderable)


@pytest.mark.asyncio
async def test_status_indicator_set_state():
    """StatusIndicator.set_state should update display."""
    app = StatusIndicatorTestApp()
    async with app.run_test() as pilot:
        indicator = app.query_one(StatusIndicator)
        indicator.set_state("error")
        await pilot.pause()
        status_text = indicator.query_one(".status-text")
        assert "Error" in str(status_text.renderable)


@pytest.mark.asyncio
async def test_status_row_renders_five_indicators():
    """StatusRow should contain 5 status indicators."""
    watcher = MagicMock()
    watcher.websocket_connected = False
    watcher.email_monitor = MagicMock(enabled=False)
    watcher.website_monitor = MagicMock(enabled=False)

    app = StatusRowTestApp(watcher)
    async with app.run_test() as pilot:
        indicators = app.query(StatusIndicator)
        assert len(indicators) == 5
```

**Step 4.3: Run tests**

Run: `cd /home/thomas/GengoWatcher && pytest tests/test_status_indicators.py -v`
Expected: 3 tests PASS

**Step 4.4: Commit**

```bash
git add src/gengowatcher/ui_textual.py tests/test_status_indicators.py
git commit -m "feat(ui): add StatusIndicator and StatusRow widgets"
```

---

## Task 5: Dashboard Quadrant Widgets

**Files:**
- Modify: `src/gengowatcher/ui_textual.py` (add after StatusRow class)

**Step 5.1: Write DashboardQuadrant base widget**

```python
class DashboardQuadrant(Static):
    """Base class for dashboard quadrant panels."""

    def __init__(self, title: str, quadrant_class: str = "", **kwargs):
        super().__init__(**kwargs)
        self._title = title
        if quadrant_class:
            self.add_class(quadrant_class)

    def compose(self) -> ComposeResult:
        yield Static(f"─ {self._title} ", classes="quadrant-title")
        yield from self._compose_content()

    def _compose_content(self) -> ComposeResult:
        """Override in subclasses to add content."""
        yield Static("")


class ActivityPreview(DashboardQuadrant):
    """Mini activity log for dashboard."""

    def __init__(self, **kwargs):
        super().__init__("Recent Activity", quadrant_class="activity", **kwargs)
        self._log_lines: list[str] = []

    def _compose_content(self) -> ComposeResult:
        yield Static("", id="activity-content")

    def add_line(self, text: str) -> None:
        """Add a line to the activity preview."""
        timestamp = datetime.datetime.now().strftime("%H:%M")
        line = f"{timestamp} {text}"
        self._log_lines.append(line)
        # Keep only last 6 lines
        self._log_lines = self._log_lines[-6:]
        try:
            content = "\n".join(self._log_lines)
            self.query_one("#activity-content", Static).update(content)
        except Exception:
            pass


class JobsPreview(DashboardQuadrant):
    """Mini jobs table for dashboard."""

    def __init__(self, state: "AppState", **kwargs):
        super().__init__("Jobs Preview", quadrant_class="jobs-preview", **kwargs)
        self._state = state

    def _compose_content(self) -> ComposeResult:
        yield Static("", id="jobs-preview-content")

    def refresh_jobs(self) -> None:
        """Update jobs preview from state."""
        jobs = self._state.get_recent_jobs(limit=4)
        if not jobs:
            content = "No jobs yet"
        else:
            lines = []
            for job in jobs:
                job_id = str(job.get("id", "?"))[:6]
                lang = job.get("lang_pair", "?")[:6]
                reward = job.get("reward", 0)
                lines.append(f"#{job_id}  {lang}  ${reward:.2f}")
            content = "\n".join(lines)
        try:
            self.query_one("#jobs-preview-content", Static).update(content)
        except Exception:
            pass


class ConfigPreview(DashboardQuadrant):
    """Configuration summary for dashboard."""

    def __init__(self, config: "AppConfig", **kwargs):
        super().__init__("Configuration", quadrant_class="config", **kwargs)
        self._config = config

    def _compose_content(self) -> ComposeResult:
        lines = [
            f"Languages: {self._config.source_lang}↔{self._config.target_lang}",
            f"Min Reward: ${self._config.min_reward:.2f}",
            f"Check Interval: {self._config.check_interval}s",
            f"Auto-Accept: {'On' if self._config.autoaccept_enabled else 'Off'}",
        ]
        yield Static("\n".join(lines), id="config-content")
```

**Step 5.2: Write tests**

Create file `tests/test_dashboard_quadrants.py`:

```python
"""Tests for Dashboard Quadrant widgets."""
import pytest
from unittest.mock import MagicMock
from textual.app import App, ComposeResult

from gengowatcher.ui_textual import ActivityPreview, JobsPreview, ConfigPreview


class ActivityPreviewTestApp(App):
    def compose(self) -> ComposeResult:
        yield ActivityPreview()


class JobsPreviewTestApp(App):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        yield JobsPreview(self._state)


@pytest.mark.asyncio
async def test_activity_preview_add_line():
    """ActivityPreview should display added lines."""
    app = ActivityPreviewTestApp()
    async with app.run_test() as pilot:
        preview = app.query_one(ActivityPreview)
        preview.add_line("Job detected #1234")
        await pilot.pause()
        content = preview.query_one("#activity-content")
        assert "Job detected" in str(content.renderable)


@pytest.mark.asyncio
async def test_jobs_preview_displays_jobs():
    """JobsPreview should display recent jobs."""
    state = MagicMock()
    state.get_recent_jobs.return_value = [
        {"id": "123456", "lang_pair": "JA→EN", "reward": 12.50},
        {"id": "123457", "lang_pair": "EN→JA", "reward": 8.00},
    ]

    app = JobsPreviewTestApp(state)
    async with app.run_test() as pilot:
        preview = app.query_one(JobsPreview)
        preview.refresh_jobs()
        await pilot.pause()
        content = preview.query_one("#jobs-preview-content")
        rendered = str(content.renderable)
        assert "$12.50" in rendered or "12.5" in rendered
```

**Step 5.3: Run tests**

Run: `cd /home/thomas/GengoWatcher && pytest tests/test_dashboard_quadrants.py -v`
Expected: 2 tests PASS

**Step 5.4: Commit**

```bash
git add src/gengowatcher/ui_textual.py tests/test_dashboard_quadrants.py
git commit -m "feat(ui): add Dashboard Quadrant widgets (Activity, Jobs, Config)"
```

---

## Task 6: StatsManager Data Layer

**Files:**
- Create: `src/gengowatcher/stats.py`
- Modify: `src/gengowatcher/state.py` (add stats integration)

**Step 6.1: Create StatsManager class**

Create file `src/gengowatcher/stats.py`:

```python
"""Historical statistics management for GengoWatcher."""
import json
import pathlib
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from collections import defaultdict
import datetime


@dataclass
class SessionStats:
    """Statistics for the current session."""
    start_time: float = field(default_factory=time.time)
    jobs_found: int = 0
    jobs_accepted: int = 0
    total_value: float = 0.0

    @property
    def duration_seconds(self) -> int:
        return int(time.time() - self.start_time)

    @property
    def rate_per_hour(self) -> float:
        hours = self.duration_seconds / 3600
        return self.jobs_found / max(hours, 0.01)


@dataclass
class AllTimeStats:
    """Aggregate statistics across all sessions."""
    total_jobs: int = 0
    total_value: float = 0.0
    total_sessions: int = 0
    best_day_value: float = 0.0
    best_day_date: str = ""

    @property
    def avg_job_value(self) -> float:
        return self.total_value / max(self.total_jobs, 1)


@dataclass
class SourceStats:
    """Statistics broken down by job source."""
    websocket: int = 0
    email: int = 0
    website: int = 0

    @property
    def total(self) -> int:
        return self.websocket + self.email + self.website

    def percentages(self) -> Dict[str, float]:
        total = max(self.total, 1)
        return {
            "websocket": self.websocket / total * 100,
            "email": self.email / total * 100,
            "website": self.website / total * 100,
        }


class StatsManager:
    """Manages historical statistics persistence and calculation."""

    STATS_FILE = "stats.json"

    def __init__(self, stats_path: Optional[pathlib.Path] = None):
        self._lock = threading.RLock()
        self._stats_path = stats_path or pathlib.Path(self.STATS_FILE)

        self.session = SessionStats()
        self.all_time = AllTimeStats()
        self.by_source = SourceStats()
        self.by_language: Dict[str, int] = defaultdict(int)
        self.hourly_counts: Dict[int, int] = defaultdict(int)  # hour -> count
        self.daily_counts: Dict[str, int] = defaultdict(int)  # day_name -> count
        self.daily_earnings: Dict[str, float] = defaultdict(float)  # date -> earnings

        self._load()

    def _load(self) -> None:
        """Load stats from file."""
        try:
            if self._stats_path.exists():
                with open(self._stats_path, "r") as f:
                    data = json.load(f)
                    self.all_time = AllTimeStats(**data.get("all_time", {}))
                    src = data.get("by_source", {})
                    self.by_source = SourceStats(**src)
                    self.by_language = defaultdict(int, data.get("by_language", {}))
                    self.hourly_counts = defaultdict(int, {int(k): v for k, v in data.get("hourly_counts", {}).items()})
                    self.daily_counts = defaultdict(int, data.get("daily_counts", {}))
                    self.daily_earnings = defaultdict(float, data.get("daily_earnings", {}))
        except (json.JSONDecodeError, IOError, TypeError):
            pass  # Start fresh

    def save(self) -> None:
        """Persist stats to file."""
        with self._lock:
            data = {
                "all_time": asdict(self.all_time),
                "by_source": asdict(self.by_source),
                "by_language": dict(self.by_language),
                "hourly_counts": dict(self.hourly_counts),
                "daily_counts": dict(self.daily_counts),
                "daily_earnings": dict(self.daily_earnings),
            }
            with open(self._stats_path, "w") as f:
                json.dump(data, f, indent=2)

    def record_job(self, reward: float, source: str, lang_pair: str, accepted: bool = False) -> None:
        """Record a job detection."""
        with self._lock:
            now = datetime.datetime.now()

            # Session stats
            self.session.jobs_found += 1
            if accepted:
                self.session.jobs_accepted += 1
                self.session.total_value += reward

            # All-time stats
            self.all_time.total_jobs += 1
            if accepted:
                self.all_time.total_value += reward

            # Source stats
            source_lower = source.lower()
            if "websocket" in source_lower or "ws" in source_lower:
                self.by_source.websocket += 1
            elif "email" in source_lower:
                self.by_source.email += 1
            elif "web" in source_lower:
                self.by_source.website += 1

            # Language stats
            self.by_language[lang_pair] += 1

            # Time-based stats
            self.hourly_counts[now.hour] += 1
            self.daily_counts[now.strftime("%A")] += 1

            if accepted:
                date_str = now.strftime("%Y-%m-%d")
                self.daily_earnings[date_str] += reward
                # Check for best day
                if self.daily_earnings[date_str] > self.all_time.best_day_value:
                    self.all_time.best_day_value = self.daily_earnings[date_str]
                    self.all_time.best_day_date = date_str

    def end_session(self) -> None:
        """Call when session ends to update totals."""
        with self._lock:
            self.all_time.total_sessions += 1
            self.save()

    def get_peak_hour(self) -> tuple[int, float]:
        """Return (hour, rate) for peak activity."""
        if not self.hourly_counts:
            return (12, 0.0)
        peak_hour = max(self.hourly_counts, key=self.hourly_counts.get)
        return (peak_hour, self.hourly_counts[peak_hour])

    def get_slowest_hour(self) -> tuple[int, float]:
        """Return (hour, rate) for slowest activity."""
        if not self.hourly_counts:
            return (4, 0.0)
        slow_hour = min(self.hourly_counts, key=self.hourly_counts.get)
        return (slow_hour, self.hourly_counts[slow_hour])

    def get_recent_earnings(self, days: int = 7) -> Dict[str, float]:
        """Get earnings for the last N days."""
        result = {}
        today = datetime.date.today()
        for i in range(days):
            date = today - datetime.timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            result[date.strftime("%a")] = self.daily_earnings.get(date_str, 0.0)
        return dict(reversed(list(result.items())))
```

**Step 6.2: Write tests for StatsManager**

Create file `tests/test_stats_manager.py`:

```python
"""Tests for StatsManager."""
import pytest
import tempfile
import pathlib
from gengowatcher.stats import StatsManager, SessionStats


def test_session_stats_duration():
    """SessionStats should track duration."""
    stats = SessionStats()
    # Duration should be near 0 at start
    assert stats.duration_seconds < 2


def test_stats_manager_record_job():
    """StatsManager should record job stats."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        manager.record_job(10.0, "WebSocket", "JA→EN", accepted=True)

        assert manager.session.jobs_found == 1
        assert manager.session.jobs_accepted == 1
        assert manager.session.total_value == 10.0
        assert manager.by_source.websocket == 1
        assert manager.by_language["JA→EN"] == 1


def test_stats_manager_persistence():
    """StatsManager should persist and reload stats."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"

        # First manager - record data
        manager1 = StatsManager(stats_path=path)
        manager1.record_job(25.0, "Email", "EN→JA", accepted=True)
        manager1.all_time.total_jobs = 100
        manager1.save()

        # Second manager - reload
        manager2 = StatsManager(stats_path=path)
        assert manager2.all_time.total_jobs == 100
        assert manager2.by_source.email == 1
```

**Step 6.3: Run tests**

Run: `cd /home/thomas/GengoWatcher && pytest tests/test_stats_manager.py -v`
Expected: 3 tests PASS

**Step 6.4: Commit**

```bash
git add src/gengowatcher/stats.py tests/test_stats_manager.py
git commit -m "feat(stats): add StatsManager for historical statistics"
```

---

## Task 7: StatsPanel Widget (Stats Tab)

**Files:**
- Modify: `src/gengowatcher/ui_textual.py` (add after ConfigPreview class)

**Step 7.1: Write StatsPanel widget**

```python
class StatsPanel(Static):
    """Full stats tab content with multiple sections."""

    def __init__(self, stats_manager: "StatsManager", **kwargs):
        super().__init__(**kwargs)
        self._stats = stats_manager

    def compose(self) -> ComposeResult:
        # Top row: Session and All-Time
        with Horizontal(classes="stats-grid"):
            with Static(classes="stats-section session"):
                yield Static("─ Session ", classes="section-title")
                yield Static("", id="stats-session-content")
            with Static(classes="stats-section alltime"):
                yield Static("─ All-Time ", classes="section-title")
                yield Static("", id="stats-alltime-content")

        # Source breakdown
        with Static(classes="stats-section source"):
            yield Static("─ By Source ", classes="section-title")
            yield Static("", id="stats-source-content")

        # Bottom row: Language and Best Times
        with Horizontal(classes="stats-grid"):
            with Static(classes="stats-section language"):
                yield Static("─ By Language ", classes="section-title")
                yield Static("", id="stats-language-content")
            with Static(classes="stats-section times"):
                yield Static("─ Best Times ", classes="section-title")
                yield Static("", id="stats-times-content")

        # Earnings chart
        with Static(classes="stats-section"):
            yield Static("─ Earnings (7 days) ", classes="section-title")
            yield Static("", id="stats-earnings-content")

    def on_mount(self) -> None:
        self.set_interval(5.0, self.refresh_stats)
        self.refresh_stats()

    def refresh_stats(self) -> None:
        """Update all stats displays."""
        s = self._stats

        # Session
        dur = s.session.duration_seconds
        h, m = divmod(dur // 60, 60)
        session_lines = [
            f"Duration     {h}h {m:02d}m",
            f"Jobs Found   {s.session.jobs_found}",
            f"Accepted     {s.session.jobs_accepted}",
            f"Value        ${s.session.total_value:.2f}",
            f"Rate         {s.session.rate_per_hour:.1f}/hr",
        ]
        self._update_content("#stats-session-content", "\n".join(session_lines))

        # All-Time
        alltime_lines = [
            f"Total Jobs   {s.all_time.total_jobs:,}",
            f"Total Value  ${s.all_time.total_value:,.2f}",
            f"Avg Value    ${s.all_time.avg_job_value:.2f}",
            f"Best Day     ${s.all_time.best_day_value:.2f}",
            f"Sessions     {s.all_time.total_sessions}",
        ]
        self._update_content("#stats-alltime-content", "\n".join(alltime_lines))

        # Source
        pct = s.by_source.percentages()
        source_lines = [
            self._bar("WebSocket", s.by_source.websocket, pct["websocket"]),
            self._bar("Email", s.by_source.email, pct["email"]),
            self._bar("Website", s.by_source.website, pct["website"]),
        ]
        self._update_content("#stats-source-content", "\n".join(source_lines))

        # Language
        lang_items = sorted(s.by_language.items(), key=lambda x: x[1], reverse=True)[:4]
        total_lang = sum(s.by_language.values()) or 1
        lang_lines = [
            self._bar(lang, count, count / total_lang * 100)
            for lang, count in lang_items
        ]
        self._update_content("#stats-language-content", "\n".join(lang_lines) if lang_lines else "No data")

        # Best Times
        peak_h, peak_c = s.get_peak_hour()
        slow_h, slow_c = s.get_slowest_hour()
        times_lines = [
            f"Peak Hour    {peak_h:02d}:00-{peak_h+1:02d}:00  ({peak_c} jobs)",
            f"Slowest      {slow_h:02d}:00-{slow_h+1:02d}:00  ({slow_c} jobs)",
        ]
        self._update_content("#stats-times-content", "\n".join(times_lines))

        # Earnings
        earnings = s.get_recent_earnings(7)
        earnings_lines = [f"{day} ${val:.0f}" for day, val in earnings.items()]
        self._update_content("#stats-earnings-content", "  ".join(earnings_lines))

    def _bar(self, label: str, count: int, pct: float) -> str:
        """Create a text-based progress bar."""
        filled = int(pct / 5)  # 20 chars max
        bar = "█" * filled + "░" * (20 - filled)
        return f"{label:10} {bar} {count:,} ({pct:.0f}%)"

    def _update_content(self, selector: str, text: str) -> None:
        try:
            self.query_one(selector, Static).update(text)
        except Exception:
            pass
```

**Step 7.2: Add Stats tab to GengoWatcherApp**

Add import at top of file:
```python
from gengowatcher.stats import StatsManager
```

In `GengoWatcherApp.__init__`, add:
```python
self._stats_manager = StatsManager()
```

In `GengoWatcherApp.compose`, add Stats tab after Charts tab:
```python
with TabPane("Stats", id="stats-tab"):
    yield StatsPanel(self._stats_manager, id="stats-panel")
```

Add action for tab 6:
```python
def action_tab_stats(self) -> None:
    self.query_one(TabbedContent).active = "stats-tab"
```

Add key binding in BINDINGS:
```python
Binding("6", "tab_stats", "Stats", show=False),
```

**Step 7.3: Write tests**

Create file `tests/test_stats_panel.py`:

```python
"""Tests for StatsPanel widget."""
import pytest
import tempfile
import pathlib
from unittest.mock import MagicMock
from textual.app import App, ComposeResult

from gengowatcher.stats import StatsManager
from gengowatcher.ui_textual import StatsPanel


class StatsPanelTestApp(App):
    def __init__(self, stats_manager):
        super().__init__()
        self._stats = stats_manager

    def compose(self) -> ComposeResult:
        yield StatsPanel(self._stats)


@pytest.mark.asyncio
async def test_stats_panel_renders_sections():
    """StatsPanel should render all stat sections."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)

        app = StatsPanelTestApp(manager)
        async with app.run_test() as pilot:
            panel = app.query_one(StatsPanel)
            # Check section titles exist
            assert panel.query_one("#stats-session-content") is not None
            assert panel.query_one("#stats-alltime-content") is not None


@pytest.mark.asyncio
async def test_stats_panel_refresh_updates_content():
    """StatsPanel.refresh_stats should update displayed values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "stats.json"
        manager = StatsManager(stats_path=path)
        manager.record_job(50.0, "WebSocket", "JA→EN", accepted=True)

        app = StatsPanelTestApp(manager)
        async with app.run_test() as pilot:
            panel = app.query_one(StatsPanel)
            panel.refresh_stats()
            await pilot.pause()

            session_content = panel.query_one("#stats-session-content")
            rendered = str(session_content.renderable)
            assert "1" in rendered  # jobs_found
```

**Step 7.4: Run tests**

Run: `cd /home/thomas/GengoWatcher && pytest tests/test_stats_panel.py -v`
Expected: 2 tests PASS

**Step 7.5: Commit**

```bash
git add src/gengowatcher/ui_textual.py tests/test_stats_panel.py
git commit -m "feat(ui): add StatsPanel widget and Stats tab"
```

---

## Task 8: Integration - Refactor compose() and Wire Everything

**Files:**
- Modify: `src/gengowatcher/ui_textual.py:786-850` (compose method)

**Step 8.1: Update imports**

Ensure all new widget imports are at the top:
```python
from gengowatcher.stats import StatsManager
```

**Step 8.2: Refactor compose() method**

Replace the compose method in GengoWatcherApp (around line 786):

```python
def compose(self) -> ComposeResult:
    """Create child widgets for the application."""
    # Title Bar (replaces old header)
    yield TitleBar(id="title-bar")

    # Metrics Row
    yield MetricsRow(self._state, id="metrics-row")

    # Status Row
    yield StatusRow(self._watcher, id="status-row")

    # Main tabbed content
    with TabbedContent(id="main-tabs"):
        # Dashboard Tab (4 quadrants)
        with TabPane("Dashboard", id="dashboard-tab"):
            with Container(classes="dashboard-grid"):
                yield ActivityPreview(id="activity-preview")
                yield JobsChart(self._state, id="jobs-chart-mini")
                yield JobsPreview(self._state, id="jobs-preview")
                yield ConfigPreview(self._config, id="config-preview")

        # Jobs Tab
        with TabPane("Jobs", id="jobs-tab"):
            yield JobsTable(id="jobs-table")

        # Activity Tab
        with TabPane("Activity", id="activity-tab"):
            yield RichLog(id="activity-log", highlight=True, markup=True, wrap=True)

        # Output Tab
        with TabPane("Output", id="output-tab"):
            yield RichLog(id="output-log", highlight=True, markup=True, wrap=True)

        # Charts Tab
        with TabPane("Charts", id="charts-tab"):
            yield JobsChart(self._state, id="jobs-chart-full")

        # Stats Tab (NEW)
        with TabPane("Stats", id="stats-tab"):
            yield StatsPanel(self._stats_manager, id="stats-panel")

    # Command Input
    yield HistoryInput(placeholder="Type command or press ? for help...", id="command-input")

    # Footer
    yield Footer()
```

**Step 8.3: Update _refresh_ui to include new widgets**

In `_refresh_ui` method, add refresh calls:

```python
def _refresh_ui(self) -> None:
    """Refresh all UI components."""
    # Existing refreshes...

    # New widget refreshes
    try:
        self.query_one("#metrics-row", MetricsRow).refresh_metrics()
    except Exception:
        pass

    try:
        self.query_one("#status-row", StatusRow).refresh_status()
    except Exception:
        pass

    try:
        self.query_one("#jobs-preview", JobsPreview).refresh_jobs()
    except Exception:
        pass
```

**Step 8.4: Wire ActivityPreview to log messages**

In the log queueing mechanism, also push to ActivityPreview:

```python
def _drain_log_queue(self) -> None:
    """Drain the log queue and update the UI."""
    # Existing code...

    # Also update activity preview
    try:
        activity = self.query_one("#activity-preview", ActivityPreview)
        for msg in messages:
            activity.add_line(str(msg))
    except Exception:
        pass
```

**Step 8.5: Update tab bindings**

In BINDINGS, ensure tab 6 is included:

```python
BINDINGS = [
    # ... existing bindings ...
    Binding("1", "tab_dashboard", "Dashboard", show=False),
    Binding("2", "tab_jobs", "Jobs", show=False),
    Binding("3", "tab_activity", "Activity", show=False),
    Binding("4", "tab_output", "Output", show=False),
    Binding("5", "tab_charts", "Charts", show=False),
    Binding("6", "tab_stats", "Stats", show=False),
]
```

**Step 8.6: Run full test suite**

Run: `cd /home/thomas/GengoWatcher && pytest tests/ -v --ignore=tests/test_watcher.py`
Expected: All tests PASS

**Step 8.7: Visual smoke test**

Run: `cd /home/thomas/GengoWatcher && timeout 5 python -m gengowatcher.main --help || true`
Expected: No import errors

**Step 8.8: Commit integration**

```bash
git add src/gengowatcher/ui_textual.py
git commit -m "feat(ui): integrate all dashboard visual overhaul components"
```

---

## Task 9: Final CSS Polish & Testing

**Files:**
- Modify: `src/gengowatcher/gengo_watcher.tcss`

**Step 9.1: Adjust spacing and alignment**

Review CSS and adjust any spacing issues found during visual testing.

**Step 9.2: Run manual visual test**

Run: `cd /home/thomas/GengoWatcher && python -m gengowatcher.main`

Verify:
- [ ] TitleBar shows brand, session time, clock
- [ ] 5 metric cards display correctly with colored borders
- [ ] Status row shows all 5 indicators
- [ ] Dashboard tab shows 4 quadrants
- [ ] Stats tab shows all sections with data
- [ ] Tab navigation 1-6 works
- [ ] Colors match Kanagawa palette

**Step 9.3: Run full test suite**

Run: `cd /home/thomas/GengoWatcher && make test`
Expected: All tests PASS

**Step 9.4: Final commit**

```bash
git add -A
git commit -m "feat(ui): complete dashboard visual overhaul polish"
```

---

## Summary

| Task | Component | Files | Tests |
|------|-----------|-------|-------|
| 1 | CSS Foundation | gengo_watcher.tcss | Linter |
| 2 | TitleBar | ui_textual.py | test_title_bar.py |
| 3 | MetricCard/Row | ui_textual.py | test_metric_cards.py |
| 4 | StatusIndicator/Row | ui_textual.py | test_status_indicators.py |
| 5 | Dashboard Quadrants | ui_textual.py | test_dashboard_quadrants.py |
| 6 | StatsManager | stats.py | test_stats_manager.py |
| 7 | StatsPanel | ui_textual.py | test_stats_panel.py |
| 8 | Integration | ui_textual.py | Full suite |
| 9 | Polish | tcss | Visual + full suite |

**Total estimated time:** 2-3 hours
**Commit count:** 9 incremental commits

---

*Plan created: 2026-01-24*
