# GengoWatcher UI Revamp Design Specification

**Date:** 2026-01-23  
**Status:** Draft  
**Branch:** `feat/ui-revamp`  
**Inspiration:** [Toad](https://github.com/Textualize/toad) (Textual), btop++, glances  
**Theme:** Kanagawa Wave  

---

## Table of Contents

1. [Color Palette](#1-color-palette)
2. [Layout Structure](#2-layout-structure)
3. [Panel Definitions](#3-panel-definitions)
4. [Status Indicators](#4-status-indicators)
5. [Charts Integration](#5-charts-integration)
6. [Command Autocomplete](#6-command-autocomplete)
7. [Keyboard Shortcuts](#7-keyboard-shortcuts)
8. [Incremental Refactor Phases](#8-incremental-refactor-phases)
9. [Test Strategy](#9-test-strategy)

---

## 1. Color Palette

### Kanagawa Wave Theme

Replacing Tokyo Night with the Kanagawa Wave palette from [kanagawa.nvim](https://github.com/rebelot/kanagawa.nvim). This theme draws inspiration from the famous "The Great Wave off Kanagawa" painting, featuring deep ink blacks, ocean blues, and natural accent colors.

#### CSS Variables (gengo_watcher.tcss)

```css
/* ══════════════════════════════════════════════════════════════════════════
   KANAGAWA WAVE COLOR PALETTE
   Source: https://github.com/rebelot/kanagawa.nvim
   ══════════════════════════════════════════════════════════════════════════ */

/* ── Background Shades (sumiInk = ink black) ───────────────────────────── */
$surface-darkest: #16161D;      /* sumiInk0 - deepest background */
$surface-darker: #1F1F28;       /* sumiInk3 - main background */
$surface: #1F1F28;              /* sumiInk3 - primary surface */
$surface-lighten-1: #2A2A37;    /* sumiInk4 - elevated surfaces */
$surface-lighten-2: #363646;    /* sumiInk5 - borders, separators */
$surface-lighten-3: #54546D;    /* sumiInk6 - subtle foreground */

/* ── Panel Backgrounds ─────────────────────────────────────────────────── */
$panel-bg: #1F1F28;             /* sumiInk3 - main panel background */
$panel-bg-elevated: #2A2A37;    /* sumiInk4 - elevated panel */
$panel-bg-popup: #223249;       /* waveBlue1 - popups, floats */
$panel-bg-hover: #2D4F67;       /* waveBlue2 - hover states */

/* ── Primary Colors (blues) ────────────────────────────────────────────── */
$primary: #7E9CD8;              /* crystalBlue - main accent */
$primary-muted: #658594;        /* dragonBlue - muted blue */
$primary-light: #7FB4CA;        /* springBlue - light blue accent */
$primary-bright: #A3D4D5;       /* lightBlue - bright highlights */

/* ── Secondary Colors (purples/violets) ────────────────────────────────── */
$secondary: #957FB8;            /* oniViolet - secondary accent */
$secondary-muted: #938AA9;      /* springViolet1 - muted violet */
$secondary-light: #9CABCA;      /* springViolet2 - light violet */

/* ── Accent Colors ─────────────────────────────────────────────────────── */
$accent: #7AA89F;               /* waveAqua2 - accent/cyan */
$accent-bright: #6A9589;        /* waveAqua1 - brighter aqua */

/* ── Semantic Colors ───────────────────────────────────────────────────── */
$success: #98BB6C;              /* springGreen - success states */
$success-muted: #76946A;        /* autumnGreen - muted success */
$warning: #DCA561;              /* autumnYellow - warnings */
$warning-bright: #E6C384;       /* carpYellow - bright yellow */
$warning-muted: #C0A36E;        /* boatYellow2 - muted yellow */
$error: #C34043;                /* autumnRed - errors */
$error-bright: #E46876;         /* waveRed - bright red */
$error-muted: #FF5D62;          /* peachRed - alerts */
$error-critical: #E82424;       /* samuraiRed - critical errors */

/* ── Text Colors ───────────────────────────────────────────────────────── */
$text: #DCD7BA;                 /* fujiWhite - primary text */
$text-muted: #727169;           /* fujiGray - muted/secondary text */
$text-accent: #C8C093;          /* oldWhite - accent text */
$text-primary: #7E9CD8;         /* crystalBlue - primary-colored text */
$text-secondary: #957FB8;       /* oniViolet - secondary-colored text */
$text-success: #98BB6C;         /* springGreen */
$text-warning: #DCA561;         /* autumnYellow */
$text-error: #C34043;           /* autumnRed */

/* ── Special Colors ────────────────────────────────────────────────────── */
$pink: #D27E99;                 /* sakuraPink - highlights */
$orange: #FFA066;               /* surimiOrange - attention */
$orange-muted: #FF9E3B;         /* roninYellow - notices */

/* ── Diff Colors (for future git integration) ──────────────────────────── */
$diff-add-bg: #2B3328;          /* winterGreen */
$diff-remove-bg: #43242B;       /* winterRed */
$diff-change-bg: #49443C;       /* winterYellow */
$diff-neutral-bg: #252535;      /* winterBlue */
```

#### Color Mapping (Tokyo Night → Kanagawa Wave)

| Purpose | Tokyo Night | Kanagawa Wave | Variable |
|---------|-------------|---------------|----------|
| Background | `#1a1b26` | `#1F1F28` | `$surface` |
| Panel BG | `#24283b` | `#2A2A37` | `$panel-bg-elevated` |
| Primary | `#7aa2f7` | `#7E9CD8` | `$primary` |
| Secondary | `#bb9af7` | `#957FB8` | `$secondary` |
| Accent | `#7dcfff` | `#7AA89F` | `$accent` |
| Success | `#9ece6a` | `#98BB6C` | `$success` |
| Warning | `#e0af68` | `#DCA561` | `$warning` |
| Error | `#f7768e` | `#C34043` | `$error` |
| Text | `#c0caf5` | `#DCD7BA` | `$text` |
| Text Muted | `#565f89` | `#727169` | `$text-muted` |

---

## 2. Layout Structure

### Toad-Inspired Split Panel Design

Drawing from Toad's layout patterns with GengoWatcher's specific needs. The layout uses a responsive grid with collapsible panels.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ [HeaderPanel] GengoWatcher v2.0 — Session: 0h 32m — Jobs: 12 found         │
├───────────────────────────┬─────────────────────────────────────────────────┤
│                           │                                                 │
│  [SideBar] (collapsible)  │  [MainContent]                                  │
│  ┌─────────────────────┐  │  ┌───────────────────────────────────────────┐  │
│  │ Runtime Status      │  │  │ Jobs Table                                │  │
│  │ ├─ Watcher: Running │  │  │ ┌─────────────────────────────────────┐  │  │
│  │ ├─ Uptime: 0:32:15  │  │  │ │ ID │ Lang │ Words │ Price │ Status │  │  │
│  │ ├─ Jobs Found: 12   │  │  │ ├────┼──────┼───────┼───────┼────────┤  │  │
│  │ └─ Jobs Accepted: 3 │  │  │ │ ...│ ...  │ ...   │ ...   │ ...    │  │  │
│  ├─────────────────────┤  │  │ └─────────────────────────────────────┘  │  │
│  │ Monitors            │  │  └───────────────────────────────────────────┘  │
│  │ ├─ Email: Polling   │  │  ┌───────────────────────────────────────────┐  │
│  │ │   Last: 2m ago    │  │  │ Activity Log / Output (Tabbed)           │  │
│  │ ├─ Website: Idle    │  │  │ [Activity] [Output] [Charts]             │  │
│  │ │   Last: 5m ago    │  │  │ ┌─────────────────────────────────────┐  │  │
│  │ └─ Jobs: E:5 W:3    │  │  │ │ 14:32:15 Job detected: JP-EN #1234 │  │  │
│  ├─────────────────────┤  │  │ │ 14:32:18 Checking requirements...  │  │  │
│  │ Quick Filters       │  │  │ │ 14:32:20 Auto-accepted job #1234   │  │  │
│  │ [All] [JP] [EN]     │  │  │ └─────────────────────────────────────┘  │  │
│  │ [High$] [Available] │  │  └───────────────────────────────────────────┘  │
│  └─────────────────────┘  │                                                 │
│                           │                                                 │
├───────────────────────────┴─────────────────────────────────────────────────┤
│ [CommandInput] > help                                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│ [StatusBar] F1:Help  F2:Settings  F5:Refresh  Ctrl+Q:Quit                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Layout Modes

1. **Default (Wide)**: Sidebar + Main Content side-by-side
2. **Compact (Narrow)**: Sidebar hidden, toggle with `F3` or `;sidebar`
3. **Focus Mode**: Only Jobs Table + minimal status, toggle with `F4`

### CSS Grid Structure

```css
/* Main layout grid */
MainScreen {
    background: $surface;
    layout: grid;
    grid-size: 2;
    grid-columns: auto 1fr;
    grid-rows: auto 1fr auto auto;
}

/* Sidebar (collapsible) */
SideBar {
    width: 32;
    min-width: 28;
    max-width: 40%;
    dock: left;
    border-right: tall $surface-lighten-2;
    background: $surface;
    overflow: hidden scroll;
    scrollbar-size: 0 0;
}

/* Hide sidebar in compact mode */
App.-compact-mode SideBar {
    display: none;
}

/* Main content area */
MainContent {
    width: 1fr;
    height: 1fr;
    layout: vertical;
}
```

---

## 3. Panel Definitions

### 3.1 HeaderPanel

Compact header showing essential info at a glance.

```python
class HeaderPanel(Static):
    """Top header with app title, session info, and quick stats."""
    
    DEFAULT_CSS = """
    HeaderPanel {
        height: 1;
        background: $surface-lighten-1;
        color: $text;
        padding: 0 1;
    }
    HeaderPanel .title {
        color: $primary;
        text-style: bold;
    }
    HeaderPanel .stat {
        color: $text-muted;
    }
    HeaderPanel .stat-value {
        color: $accent;
    }
    """
```

### 3.2 RuntimeStatusPanel (Enhanced)

Collapsible panel with monitor status and metrics.

```python
class RuntimeStatusPanel(Static):
    """Runtime stats with collapsible sections."""
    
    # Sections:
    # - Watcher Status (running/paused/error)
    # - Session Stats (uptime, jobs found, accepted)
    # - Monitor Status (email, website - from previous work)
    # - Quick Actions (pause, refresh, clear)
```

### 3.3 JobsTable (Enhanced)

Feature-rich table with filtering and sorting.

```python
class JobsTable(DataTable):
    """Jobs table with filtering, sorting, and row actions."""
    
    BINDINGS = [
        ("f", "filter", "Filter"),
        ("s", "sort", "Sort"),
        ("enter", "view_details", "Details"),
        ("a", "accept_job", "Accept"),
    ]
    
    # New features:
    # - Column sorting (click header)
    # - Quick filters (language, price, status)
    # - Row highlighting based on job value
    # - Inline actions (accept, reject, details)
```

### 3.4 ActivityLog (Tabbed with Charts)

Tabbed container for activity, output, and charts.

```python
class ActivityContainer(TabbedContent):
    """Tabbed container: Activity | Output | Charts"""
    
    def compose(self):
        with TabbedContent():
            with TabPane("Activity", id="activity-tab"):
                yield RichLog(id="activity-log")
            with TabPane("Output", id="output-tab"):
                yield RichLog(id="output-log")
            with TabPane("Charts", id="charts-tab"):
                yield JobsChart()  # textual-plotext
```

### 3.5 CommandInput (Enhanced with Autocomplete)

Command input with history and autocomplete.

```python
class CommandInput(Input):
    """Command input with autocomplete and history."""
    
    # Features:
    # - Command autocomplete (textual-autocomplete)
    # - History navigation (up/down arrows)
    # - Slash commands (/help, /filter, /accept)
    # - Tab completion for arguments
```

---

## 4. Status Indicators

### Status Color Coding

| Status | Color Variable | Hex | Use Case |
|--------|---------------|-----|----------|
| Running/Active | `$success` | `#98BB6C` | Watcher running, monitor polling |
| Idle/Waiting | `$text-muted` | `#727169` | No activity, waiting |
| Connecting | `$primary` | `#7E9CD8` | Establishing connection |
| Warning | `$warning` | `#DCA561` | Rate limited, slow response |
| Error | `$error` | `#C34043` | Connection failed, auth error |
| Critical | `$error-critical` | `#E82424` | Unrecoverable error |

### CSS Status Classes

```css
/* Watcher Status */
.status-running { color: $success; }
.status-paused { color: $warning; }
.status-stopped { color: $text-muted; }
.status-error { color: $error; }

/* Monitor Status */
.status-email-polling { color: $success; }
.status-email-idle { color: $text-muted; }
.status-email-connecting { color: $primary; }
.status-email-error { color: $error; }

.status-website-scraping { color: $success; }
.status-website-idle { color: $text-muted; }
.status-website-init { color: $primary; }
.status-website-error { color: $error; }

/* Job Status */
.job-available { color: $success; }
.job-accepted { color: $primary; }
.job-completed { color: $text-muted; }
.job-expired { color: $error; }

/* Job Value Highlighting */
.job-high-value { background: $warning 15%; }
.job-premium { background: $orange 10%; border-left: thick $orange; }
```

---

## 5. Charts Integration

### Using textual-plotext

Install: `pip install textual-plotext`

```python
from textual_plotext import PlotextPlot

class JobsChart(PlotextPlot):
    """Real-time chart showing jobs over time."""
    
    def __init__(self):
        super().__init__()
        self.jobs_data = []
        self.timestamps = []
    
    def on_mount(self):
        self.set_interval(60, self.update_chart)
    
    def update_chart(self):
        # Update with latest job counts
        self.plt.clear_data()
        self.plt.plot(self.timestamps, self.jobs_data)
        self.plt.title("Jobs Found (Last Hour)")
        self.plt.xlabel("Time")
        self.plt.ylabel("Jobs")
        self.refresh()
```

### Chart Types to Implement

1. **Jobs Timeline**: Line chart showing jobs found over time
2. **Language Distribution**: Bar chart of jobs by language pair
3. **Acceptance Rate**: Pie chart of accepted vs. passed jobs
4. **Earnings Tracker**: Area chart of estimated earnings

---

## 6. Command Autocomplete

### Using textual-autocomplete

Install: `pip install textual-autocomplete`

```python
from textual_autocomplete import AutoComplete, Dropdown, DropdownItem

class CommandInput(Input):
    """Command input with autocomplete."""
    
    def compose(self):
        yield AutoComplete(
            Input(placeholder="Type a command..."),
            Dropdown(items=self.get_completions),
        )
    
    def get_completions(self, value: str) -> list[DropdownItem]:
        commands = [
            DropdownItem("help", "Show help"),
            DropdownItem("status", "Show status"),
            DropdownItem("pause", "Pause watcher"),
            DropdownItem("resume", "Resume watcher"),
            DropdownItem("filter", "Filter jobs"),
            DropdownItem("accept", "Accept job by ID"),
            DropdownItem("emailstats", "Email monitor stats"),
            DropdownItem("websitestats", "Website monitor stats"),
            DropdownItem("clear", "Clear logs"),
            DropdownItem("quit", "Exit application"),
        ]
        return [c for c in commands if value.lower() in c.main.lower()]
```

---

## 7. Keyboard Shortcuts

### Global Bindings

| Key | Action | Description |
|-----|--------|-------------|
| `F1` | `toggle_help` | Show/hide help panel |
| `F2` | `settings` | Open settings |
| `F3` | `toggle_sidebar` | Show/hide sidebar |
| `F4` | `focus_mode` | Toggle focus mode |
| `F5` | `refresh` | Force refresh |
| `Ctrl+Q` | `quit` | Exit application |
| `Ctrl+C` | `interrupt` | Cancel current operation |
| `Ctrl+L` | `clear_logs` | Clear activity log |
| `/` | `command_focus` | Focus command input |
| `?` | `quick_help` | Show quick help |

### Jobs Table Bindings

| Key | Action | Description |
|-----|--------|-------------|
| `Enter` | `view_details` | View job details |
| `a` | `accept_job` | Accept selected job |
| `r` | `reject_job` | Mark as rejected |
| `f` | `filter_dialog` | Open filter dialog |
| `s` | `sort_dialog` | Open sort dialog |
| `j/k` | `navigate` | Move up/down |
| `g` | `goto_top` | Go to first row |
| `G` | `goto_bottom` | Go to last row |

### Implementation

```python
class GengoWatcherApp(App):
    BINDINGS = [
        Binding("f1", "toggle_help", "Help", priority=True),
        Binding("f2", "settings", "Settings"),
        Binding("f3", "toggle_sidebar", "Sidebar"),
        Binding("f4", "toggle_focus_mode", "Focus"),
        Binding("f5", "refresh", "Refresh"),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+l", "clear_logs", "Clear", show=False),
        Binding("slash", "focus_command", "Command", show=False),
        Binding("question_mark", "quick_help", "Help", show=False),
    ]
```

---

## 8. Incremental Refactor Phases

### Phase 1: Color Palette Swap (Low Risk)
**Effort:** 1-2 hours | **Files:** 1 | **Risk:** Low

- [ ] Replace Tokyo Night CSS variables with Kanagawa Wave
- [ ] Update status indicator colors
- [ ] Test visual appearance
- [ ] Commit: `style: swap Tokyo Night for Kanagawa Wave theme`

### Phase 2: Layout Restructure (Medium Risk)
**Effort:** 4-6 hours | **Files:** 2-3 | **Risk:** Medium

- [ ] Add `SideBar` collapsible container
- [ ] Move `RuntimeStatusPanel` into sidebar
- [ ] Add `MainContent` wrapper
- [ ] Implement layout toggle (F3)
- [ ] Commit: `feat: add collapsible sidebar layout`

### Phase 3: Enhanced Status Panel (Low Risk)
**Effort:** 2-3 hours | **Files:** 1-2 | **Risk:** Low

- [ ] Add collapsible sections to `RuntimeStatusPanel`
- [ ] Improve metric display formatting
- [ ] Add quick action buttons
- [ ] Commit: `feat: enhance runtime status panel with collapsible sections`

### Phase 4: Charts Integration (Medium Risk)
**Effort:** 3-4 hours | **Files:** 2 | **Risk:** Medium

- [ ] Add `textual-plotext` dependency
- [ ] Create `JobsChart` widget
- [ ] Add "Charts" tab to activity container
- [ ] Implement basic jobs timeline chart
- [ ] Commit: `feat: add real-time jobs chart using textual-plotext`

### Phase 5: Command Autocomplete (Low Risk)
**Effort:** 2-3 hours | **Files:** 1-2 | **Risk:** Low

- [ ] Add `textual-autocomplete` dependency
- [ ] Integrate autocomplete into `HistoryInput`
- [ ] Add command completions
- [ ] Commit: `feat: add command autocomplete`

### Phase 6: Keyboard Shortcuts (Low Risk)
**Effort:** 2-3 hours | **Files:** 1-2 | **Risk:** Low

- [ ] Define all keyboard bindings
- [ ] Implement action handlers
- [ ] Add help overlay showing shortcuts
- [ ] Commit: `feat: add comprehensive keyboard shortcuts`

### Phase 7: Job Filtering (Medium Risk)
**Effort:** 3-4 hours | **Files:** 2-3 | **Risk:** Medium

- [ ] Add filter state to `JobsTable`
- [ ] Create filter dialog/popover
- [ ] Implement quick filter chips in sidebar
- [ ] Commit: `feat: add job filtering by language, price, status`

### Phase 8: Tests & Polish (Low Risk)
**Effort:** 4-6 hours | **Files:** 3-5 | **Risk:** Low

- [ ] Add snapshot tests for main panels
- [ ] Add component tests for interactions
- [ ] Fix any visual issues
- [ ] Update README with new features
- [ ] Commit: `test: add UI snapshot and component tests`

---

## 9. Test Strategy

### Snapshot Tests

Using Textual's built-in snapshot testing:

```python
# tests/test_ui_snapshots.py
import pytest
from textual.testing import SnapshotTestResult

from gengowatcher.ui_textual import GengoWatcherApp

async def test_main_screen_snapshot(snap_compare):
    """Snapshot test for main screen layout."""
    async with GengoWatcherApp().run_test() as pilot:
        assert snap_compare(pilot.app)

async def test_sidebar_collapsed_snapshot(snap_compare):
    """Snapshot test with sidebar collapsed."""
    async with GengoWatcherApp().run_test() as pilot:
        await pilot.press("f3")  # Toggle sidebar
        assert snap_compare(pilot.app)

async def test_jobs_table_with_data(snap_compare):
    """Snapshot test with sample job data."""
    app = GengoWatcherApp()
    # ... add test data
    async with app.run_test() as pilot:
        assert snap_compare(pilot.app)
```

### Component Tests

```python
# tests/test_ui_components.py
import pytest
from textual.testing import AppTest

async def test_command_input_autocomplete():
    """Test command autocomplete functionality."""
    async with GengoWatcherApp().run_test() as pilot:
        await pilot.click("#command-input")
        await pilot.type("hel")
        # Assert autocomplete dropdown appears with "help"
        assert pilot.app.query_one("Dropdown").visible
        
async def test_job_filter_toggle():
    """Test job filtering toggles."""
    async with GengoWatcherApp().run_test() as pilot:
        # Click JP filter
        await pilot.click(".filter-chip-jp")
        # Assert table is filtered
        table = pilot.app.query_one("JobsTable")
        # ... verify filtered rows

async def test_keyboard_navigation():
    """Test keyboard shortcuts."""
    async with GengoWatcherApp().run_test() as pilot:
        await pilot.press("f3")
        assert not pilot.app.query_one("SideBar").display
        await pilot.press("f3")
        assert pilot.app.query_one("SideBar").display
```

### Test Coverage Goals

| Component | Target Coverage | Priority |
|-----------|----------------|----------|
| `RuntimeStatusPanel` | 80% | High |
| `JobsTable` | 85% | High |
| `CommandInput` | 75% | Medium |
| `JobsChart` | 60% | Low |
| Keyboard Bindings | 90% | High |
| Color/CSS | Visual only | Low |

---

## Appendix: Dependencies

### New Dependencies

```toml
# pyproject.toml additions
[project.optional-dependencies]
ui = [
    "textual-plotext>=1.0.0",
    "textual-autocomplete>=3.0.0",
]
```

### Existing Dependencies (verify versions)

- `textual>=0.50.0`
- `rich>=13.0.0`

---

## Next Steps

1. **Review & Approve** this design spec
2. **Create feature branch** `feat/ui-revamp`
3. **Phase 1**: Swap color palette (quick win, immediate visual improvement)
4. **Iterate** through phases with commits after each

---

*Document created: 2026-01-23*  
*Last updated: 2026-01-23*
