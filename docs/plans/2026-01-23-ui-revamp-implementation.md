# GengoWatcher UI Revamp Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform GengoWatcher's Textual TUI into a polished command-center interface using Kanagawa Wave colors and tabbed navigation (replacing the sidebar concept).

**Architecture:** Incremental refactor in 6 phases. Phase 1 swaps colors (pure CSS). Phase 2 restructures to main tabbed layout. Phases 3-6 add features. Each phase is independently deployable.

**Tech Stack:** Python 3.10+, Textual 0.50+, textual-plotext (charts), textual-autocomplete (command input)

---

## Phase 1: Kanagawa Wave Color Palette

**Effort:** 30-45 min | **Risk:** Low | **Files:** 1

Swap Tokyo Night → Kanagawa Wave CSS variables. Pure styling change, no logic.

### Task 1.1: Replace CSS Color Variables

**Files:**
- Modify: `src/gengowatcher/gengo_watcher.tcss:1-16`

**Step 1: Backup current theme (optional reference)**

No action needed - git tracks history.

**Step 2: Replace color variable block**

Replace lines 1-16 in `gengo_watcher.tcss` with:

```css
/* ══════════════════════════════════════════════════════════════════════════
   KANAGAWA WAVE COLOR PALETTE
   Source: https://github.com/rebelot/kanagawa.nvim
   ══════════════════════════════════════════════════════════════════════════ */

/* ── Background Shades ─────────────────────────────────────────────────── */
$surface: #1F1F28;              /* sumiInk3 - primary surface */
$surface-darken-1: #16161D;     /* sumiInk0 - deepest background */
$surface-lighten-1: #2A2A37;    /* sumiInk4 - elevated surfaces */
$surface-lighten-2: #363646;    /* sumiInk5 - borders, separators */

/* ── Panel & Accent ────────────────────────────────────────────────────── */
$panel-bg: #2A2A37;             /* sumiInk4 - panel background */
$primary: #7E9CD8;              /* crystalBlue - main accent */
$primary-darken-2: #5D7BC0;     /* darker crystal blue */
$secondary: #957FB8;            /* oniViolet - secondary accent */
$accent: #7AA89F;               /* waveAqua2 - accent/cyan */

/* ── Semantic Colors ───────────────────────────────────────────────────── */
$success: #98BB6C;              /* springGreen */
$warning: #DCA561;              /* autumnYellow */
$error: #C34043;                /* autumnRed */

/* ── Text Colors ───────────────────────────────────────────────────────── */
$text: #DCD7BA;                 /* fujiWhite - primary text */
$text-muted: #727169;           /* fujiGray - muted text */
```

**Step 3: Run application to verify visual appearance**

Run: `python -m gengowatcher.main`

Expected: App launches with warmer, earth-toned colors (cream text, deep blue accents).

**Step 4: Commit**

```bash
git add src/gengowatcher/gengo_watcher.tcss
git commit -m "style: swap Tokyo Night for Kanagawa Wave color palette"
```

---

## Phase 2: Tabbed Main Layout

**Effort:** 1-2 hours | **Risk:** Medium | **Files:** 2

Replace the current layout with a main `TabbedContent` for Dashboard/Jobs/Logs/Charts navigation. The header bar stays at top, status bar + input at bottom.

### Target Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ [Header] GengoWatcher v2.0                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ [Dashboard] [Jobs] [Activity] [Output] [Charts]     ← Main Tab Navigation   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Tab Content Area (changes based on selected tab)                           │
│                                                                             │
│  Dashboard Tab: RuntimeStatusPanel + HeaderPanel (config)                   │
│  Jobs Tab: JobsTable (full width)                                           │
│  Activity Tab: RichLog (activity-log)                                       │
│  Output Tab: RichLog (output-log)                                           │
│  Charts Tab: JobsChart (placeholder for Phase 4)                            │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ [StatusBar] Status: Running │ WS: Live │ RSS: Checking │ Found: 12          │
├─────────────────────────────────────────────────────────────────────────────┤
│ [Input] > help                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ [Footer] q:Quit  c:Check  p:Pause  r:Resume  ?:Help                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Task 2.1: Update compose() for Tabbed Layout

**Files:**
- Modify: `src/gengowatcher/ui_textual.py:681-733`

**Step 1: Write failing test for tab structure**

**Files:**
- Create: `tests/test_ui_tabs.py`

```python
"""Tests for tabbed UI layout."""
import pytest


@pytest.mark.asyncio
async def test_main_tabs_exist():
    """Verify main navigation tabs are present."""
    # Import here to avoid issues if UI not fully configured
    from gengowatcher.ui_textual import GengoWatcherApp
    from unittest.mock import MagicMock, patch
    from collections import deque
    
    # Mock dependencies
    mock_watcher = MagicMock()
    mock_watcher.start_time = 0
    mock_watcher.session_new_entries = 0
    mock_watcher.session_total_value = 0
    mock_watcher.websocket_status = "Offline"
    mock_watcher.rss_action = "Idle"
    mock_watcher.next_check_time = 0
    mock_watcher.shutdown_event = MagicMock()
    mock_watcher.shutdown_event.is_set.return_value = True
    mock_watcher.PAUSE_FILE = "/tmp/gw_pause"
    
    mock_config = MagicMock()
    mock_config.get.return_value = ""
    mock_config.getboolean.return_value = False
    
    mock_state = MagicMock()
    mock_state.total_new_entries_found = 0
    mock_state.sparkline_data = []
    mock_state.get_job_count.return_value = 0
    
    app = GengoWatcherApp(
        watcher=mock_watcher,
        config=mock_config,
        state=mock_state,
        log_queue=deque(),
    )
    
    async with app.run_test() as pilot:
        # Check that TabbedContent exists with expected tabs
        tabbed = pilot.app.query_one("TabbedContent")
        assert tabbed is not None
        
        # Check tab panes exist
        tab_ids = [pane.id for pane in pilot.app.query("TabPane")]
        assert "dashboard" in tab_ids
        assert "jobs" in tab_ids
        assert "activity" in tab_ids
        assert "output" in tab_ids
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ui_tabs.py::test_main_tabs_exist -v`

Expected: FAIL - "dashboard" not in tab_ids (current tabs are "activity", "jobs", "output")

**Step 3: Update compose() method**

Replace `compose()` method (lines 681-733) in `src/gengowatcher/ui_textual.py`:

```python
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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_ui_tabs.py::test_main_tabs_exist -v`

Expected: PASS

**Step 5: Add CSS for dashboard content layout**

**Files:**
- Modify: `src/gengowatcher/gengo_watcher.tcss` (append at end)

```css
/* Dashboard tab content layout */
#dashboard-content {
    layout: vertical;
    height: 1fr;
    padding: 0;
}

#dashboard-content #runtime-panel {
    height: auto;
}

#dashboard-content #header-panel {
    height: auto;
}

/* Charts placeholder */
#charts-placeholder {
    width: 100%;
    height: 100%;
    content-align: center middle;
    color: $text-muted;
}

/* Ensure main-tabs fills space */
#main-tabs {
    height: 1fr;
}
```

**Step 6: Run application to verify layout**

Run: `python -m gengowatcher.main`

Expected: App shows tabs at top of content area: Dashboard, Jobs, Activity, Output, Charts

**Step 7: Commit**

```bash
git add src/gengowatcher/ui_textual.py src/gengowatcher/gengo_watcher.tcss tests/test_ui_tabs.py
git commit -m "feat: restructure UI with main tabbed navigation"
```

---

### Task 2.2: Update action_toggle_runtime for new structure

**Files:**
- Modify: `src/gengowatcher/ui_textual.py:879-886`

**Step 1: Update toggle to switch to dashboard tab instead of hide/show**

Replace `action_toggle_runtime()` method:

```python
    def action_toggle_runtime(self) -> None:
        """Toggle to dashboard tab to view runtime stats."""
        try:
            tabbed = self.query_one("#main-tabs", TabbedContent)
            tabbed.active = "dashboard"
        except Exception:
            pass
```

**Step 2: Verify toggle works**

Run app, press `t` - should switch to Dashboard tab.

**Step 3: Commit**

```bash
git add src/gengowatcher/ui_textual.py
git commit -m "fix: update toggle runtime to switch tabs"
```

---

### Task 2.3: Add Tab Keyboard Shortcuts

**Files:**
- Modify: `src/gengowatcher/ui_textual.py:512-523` (BINDINGS)

**Step 1: Add number key bindings for tab switching**

Update BINDINGS list to add:

```python
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
```

**Step 2: Add action handlers for tab switching**

Add after `action_toggle_runtime()`:

```python
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
```

**Step 3: Test keyboard shortcuts**

Run app, press 1-5 to switch tabs.

**Step 4: Commit**

```bash
git add src/gengowatcher/ui_textual.py
git commit -m "feat: add number key shortcuts for tab navigation (1-5)"
```

---

## Phase 3: Enhanced Keyboard Shortcuts

**Effort:** 30-45 min | **Risk:** Low | **Files:** 1-2

Add comprehensive keyboard shortcuts with help overlay.

### Task 3.1: Add Help Overlay Showing Shortcuts

**Files:**
- Modify: `src/gengowatcher/ui_textual.py` (HelpScreen class)

**Step 1: Enhance HelpScreen to show keyboard shortcuts**

Update `HelpScreen.on_mount()` to include shortcuts table:

```python
    def on_mount(self) -> None:
        """Build help content with commands and shortcuts."""
        from rich.table import Table
        from rich.console import Group
        
        # Commands table
        cmd_table = Table(title="Commands", show_header=True, header_style="bold")
        cmd_table.add_column("Command", style="cyan")
        cmd_table.add_column("Aliases", style="dim")
        cmd_table.add_column("Description")

        if hasattr(self.app, "commands"):
            for cmd, info in self.app.commands.items():
                aliases = ", ".join(info.get("aliases", []))
                cmd_table.add_row(cmd, aliases, info["help"])

        # Shortcuts table
        shortcut_table = Table(title="Keyboard Shortcuts", show_header=True, header_style="bold")
        shortcut_table.add_column("Key", style="cyan", width=10)
        shortcut_table.add_column("Action")
        
        shortcuts = [
            ("1-5", "Switch tabs (Dashboard/Jobs/Activity/Output/Charts)"),
            ("q/Esc", "Quit application"),
            ("c", "Trigger immediate check"),
            ("p", "Pause watcher"),
            ("r", "Resume watcher"),
            ("t", "Go to Dashboard"),
            ("?", "Show this help"),
            ("Ctrl+P", "Command palette"),
            ("Ctrl+L", "Clear activity log"),
            ("↑/↓", "Command history (in input)"),
        ]
        for key, action in shortcuts:
            shortcut_table.add_row(key, action)

        self.query_one("#help-list", Static).update(Group(shortcut_table, cmd_table))
```

**Step 2: Test help modal**

Run app, press `?` - should show shortcuts + commands.

**Step 3: Commit**

```bash
git add src/gengowatcher/ui_textual.py
git commit -m "feat: enhance help modal with keyboard shortcuts table"
```

---

## Phase 4: Charts Integration (textual-plotext)

**Effort:** 1-2 hours | **Risk:** Medium | **Files:** 2-3

Add real-time charts showing jobs over time.

### Task 4.1: Add textual-plotext Dependency

**Files:**
- Modify: `pyproject.toml` or `requirements.txt`

**Step 1: Add dependency**

If using pyproject.toml, add to dependencies or optional:
```toml
[project.optional-dependencies]
ui = [
    "textual-plotext>=1.0.0",
]
```

Or add to requirements.txt:
```
textual-plotext>=1.0.0
```

**Step 2: Install dependency**

Run: `pip install textual-plotext`

**Step 3: Commit**

```bash
git add pyproject.toml  # or requirements.txt
git commit -m "chore: add textual-plotext dependency for charts"
```

---

### Task 4.2: Create JobsChart Widget

**Files:**
- Modify: `src/gengowatcher/ui_textual.py`

**Step 1: Add imports at top of file**

Add after existing imports (around line 30):

```python
try:
    from textual_plotext import PlotextPlot
    PLOTEXT_AVAILABLE = True
except ImportError:
    PLOTEXT_AVAILABLE = False
```

**Step 2: Create JobsChart class**

Add after `StatsSparkline` class (around line 98):

```python
class JobsChart(Static):
    """Real-time chart showing jobs found over time."""

    def __init__(self, state: "AppState", **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self._chart = None

    def compose(self) -> ComposeResult:
        if PLOTEXT_AVAILABLE:
            self._chart = PlotextPlot()
            yield self._chart
        else:
            yield Static(
                "[dim]Install textual-plotext for charts:\n"
                "pip install textual-plotext[/]",
                id="charts-unavailable",
            )

    def on_mount(self) -> None:
        if self._chart:
            self.update_chart()
            self.set_interval(60, self.update_chart)

    def update_chart(self) -> None:
        """Update chart with latest sparkline data."""
        if not self._chart or not PLOTEXT_AVAILABLE:
            return

        data = self.state.sparkline_data or []
        if not data:
            data = [0]

        try:
            plt = self._chart.plt
            plt.clear_data()
            plt.clear_figure()
            
            # Create x-axis (minutes ago)
            x = list(range(len(data)))
            
            plt.plot(x, data, marker="braille")
            plt.title("Jobs/Hour (Recent)")
            plt.xlabel("Samples")
            plt.ylabel("Jobs/Hour")
            
            self._chart.refresh()
        except Exception:
            pass
```

**Step 3: Update compose() to use JobsChart**

In `compose()` method, replace the Charts TabPane content:

```python
            # Charts tab - real-time charts
            with TabPane("Charts", id="charts"):
                yield JobsChart(self.state, id="jobs-chart")
```

**Step 4: Test charts tab**

Run app, switch to Charts tab (press 5). Should show chart or install message.

**Step 5: Commit**

```bash
git add src/gengowatcher/ui_textual.py
git commit -m "feat: add real-time jobs chart using textual-plotext"
```

---

## Phase 5: Command Autocomplete

**Effort:** 1 hour | **Risk:** Low | **Files:** 2

Add autocomplete dropdown to command input.

### Task 5.1: Add textual-autocomplete Dependency

**Files:**
- Modify: `pyproject.toml` or `requirements.txt`

**Step 1: Add dependency**

```
textual-autocomplete>=3.0.0
```

**Step 2: Install**

Run: `pip install textual-autocomplete`

**Step 3: Commit**

```bash
git add pyproject.toml  # or requirements.txt
git commit -m "chore: add textual-autocomplete dependency"
```

---

### Task 5.2: Integrate Autocomplete into HistoryInput

**Files:**
- Modify: `src/gengowatcher/ui_textual.py`

**Step 1: Add import**

```python
try:
    from textual_autocomplete import AutoComplete, Dropdown, DropdownItem
    AUTOCOMPLETE_AVAILABLE = True
except ImportError:
    AUTOCOMPLETE_AVAILABLE = False
```

**Step 2: Create AutocompleteInput class**

Add after `HistoryInput` class:

```python
class AutocompleteInput(HistoryInput):
    """Input with command autocomplete support."""

    def __init__(self, commands: dict, **kwargs):
        super().__init__(**kwargs)
        self._commands = commands

    def get_completions(self, value: str) -> list:
        """Generate completions for current input."""
        if not AUTOCOMPLETE_AVAILABLE:
            return []
        
        if not value:
            return []
        
        value_lower = value.lower()
        completions = []
        
        for cmd, info in self._commands.items():
            if value_lower in cmd.lower():
                completions.append(
                    DropdownItem(main=cmd, left_meta=info.get("help", "")[:40])
                )
            # Also match aliases
            for alias in info.get("aliases", []):
                if value_lower in alias.lower() and alias != cmd:
                    completions.append(
                        DropdownItem(main=alias, left_meta=f"→ {cmd}")
                    )
        
        return completions[:10]  # Limit results
```

**Step 3: Update compose() to use autocomplete**

This requires wrapping the input with AutoComplete. For now, keep HistoryInput but note autocomplete as future enhancement (textual-autocomplete API may need review).

**Step 4: Commit**

```bash
git add src/gengowatcher/ui_textual.py
git commit -m "feat: add autocomplete support structure (textual-autocomplete)"
```

---

## Phase 6: Polish and Tests

**Effort:** 1-2 hours | **Risk:** Low | **Files:** 3-5

Final polish, snapshot tests, documentation.

### Task 6.1: Add UI Snapshot Tests

**Files:**
- Create: `tests/test_ui_snapshots.py`

**Step 1: Create snapshot test file**

```python
"""Snapshot tests for GengoWatcher UI."""
import pytest
from unittest.mock import MagicMock
from collections import deque


def create_mock_app():
    """Create app with mocked dependencies for testing."""
    from gengowatcher.ui_textual import GengoWatcherApp
    
    mock_watcher = MagicMock()
    mock_watcher.start_time = 0
    mock_watcher.session_new_entries = 5
    mock_watcher.session_total_value = 25.50
    mock_watcher.websocket_status = "Live"
    mock_watcher.rss_action = "Checking"
    mock_watcher.next_check_time = 999999999
    mock_watcher.shutdown_event = MagicMock()
    mock_watcher.shutdown_event.is_set.return_value = True
    mock_watcher.PAUSE_FILE = "/tmp/gw_pause_test"
    mock_watcher.get_monitor_status.return_value = {
        "websocket": "alive",
        "rss": "alive",
        "email": "disabled",
        "website": "disabled",
    }
    
    mock_config = MagicMock()
    mock_config.get.return_value = "test_value"
    mock_config.getboolean.return_value = True
    
    mock_state = MagicMock()
    mock_state.total_new_entries_found = 42
    mock_state.sparkline_data = [1.0, 2.5, 3.0, 2.0, 4.5]
    mock_state.get_job_count.return_value = 0
    mock_state.get_recent_jobs.return_value = []
    
    return GengoWatcherApp(
        watcher=mock_watcher,
        config=mock_config,
        state=mock_state,
        log_queue=deque(),
    )


@pytest.mark.asyncio
async def test_dashboard_tab_renders(snap_compare):
    """Snapshot test for Dashboard tab."""
    app = create_mock_app()
    async with app.run_test() as pilot:
        # Dashboard is default tab
        assert snap_compare(pilot.app)


@pytest.mark.asyncio
async def test_jobs_tab_renders(snap_compare):
    """Snapshot test for Jobs tab."""
    app = create_mock_app()
    async with app.run_test() as pilot:
        await pilot.press("2")  # Switch to Jobs
        assert snap_compare(pilot.app)


@pytest.mark.asyncio
async def test_activity_tab_renders(snap_compare):
    """Snapshot test for Activity tab."""
    app = create_mock_app()
    async with app.run_test() as pilot:
        await pilot.press("3")  # Switch to Activity
        assert snap_compare(pilot.app)
```

**Step 2: Run snapshot tests**

Run: `pytest tests/test_ui_snapshots.py -v`

Note: First run creates snapshots. Subsequent runs compare.

**Step 3: Commit**

```bash
git add tests/test_ui_snapshots.py
git commit -m "test: add UI snapshot tests for tabbed layout"
```

---

### Task 6.2: Update Keyboard Shortcuts in Footer

**Files:**
- Modify: `src/gengowatcher/ui_textual.py:512-523`

**Step 1: Update BINDINGS to show tab hints**

Update key display for better footer:

```python
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("escape", "quit", "Quit", show=False),
        Binding("c", "check", "Check", show=True),
        Binding("p", "pause", "Pause", show=True),
        Binding("r", "resume", "Resume", show=True),
        Binding("question_mark", "show_help", "?:Help", show=True),
        Binding("ctrl+p", "command_palette", "Cmds", show=True),
        Binding("ctrl+l", "clear_log", "Clear", show=False),
        # Tab shortcuts (shown in help, not footer to avoid clutter)
        Binding("1", "tab_dashboard", "1:Dash", show=False),
        Binding("2", "tab_jobs", "2:Jobs", show=False),
        Binding("3", "tab_activity", "3:Log", show=False),
        Binding("4", "tab_output", "4:Out", show=False),
        Binding("5", "tab_charts", "5:Chart", show=False),
        Binding("t", "tab_dashboard", "t:Dash", show=False),
        Binding("h", "show_help", "Help", show=False),
    ]
```

**Step 2: Verify footer looks clean**

Run app, check footer shows essential shortcuts without clutter.

**Step 3: Commit**

```bash
git add src/gengowatcher/ui_textual.py
git commit -m "style: clean up footer keyboard shortcut display"
```

---

## Summary: Commit History

After completing all phases, commit history should look like:

1. `style: swap Tokyo Night for Kanagawa Wave color palette`
2. `feat: restructure UI with main tabbed navigation`
3. `fix: update toggle runtime to switch tabs`
4. `feat: add number key shortcuts for tab navigation (1-5)`
5. `feat: enhance help modal with keyboard shortcuts table`
6. `chore: add textual-plotext dependency for charts`
7. `feat: add real-time jobs chart using textual-plotext`
8. `chore: add textual-autocomplete dependency`
9. `feat: add autocomplete support structure (textual-autocomplete)`
10. `test: add UI snapshot tests for tabbed layout`
11. `style: clean up footer keyboard shortcut display`

---

## Rollback Points

Each phase is independently revertable:
- Phase 1: `git revert <commit1>` - reverts to Tokyo Night
- Phase 2: `git revert <commit2-4>` - reverts tab structure
- Phase 4: `git revert <commit6-7>` - removes charts
- Phase 5: `git revert <commit8-9>` - removes autocomplete

---

*Plan created: 2026-01-23*
