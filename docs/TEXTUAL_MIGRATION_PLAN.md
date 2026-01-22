# GengoWatcher TUI Migration Plan: Rich → Textual

## Executive Summary

Migrate from Rich `Live` display to Textual framework for proper scrolling, mouse support, and modern widget system. This is a **UI-only change** - all business logic in `watcher.py`, `state.py`, and monitors remains untouched.

---

## Current Architecture Analysis

### Current ui.py Structure (831 lines)

```
CommandLineInterface
├── __init__          - Setup console, log_queue, commands, signal handler
├── _init_commands    - Register 25+ commands with aliases
├── _build_layout     - Rich Layout with header/main/footer/input
├── run               - Main loop with Live display + keyboard polling
├── _process_char     - Raw keyboard input handling (cbreak mode)
├── _get_*_panel      - 5 panel builders (header, runtime_status, recent_activity, output, status_bar)
├── handle_command    - Command dispatch
├── print_help        - Help panel generator
└── _handle_*         - 25+ command handlers
```

### Current Pain Points

1. **No scrolling** - `_recent_activity` truncates to last 25 items
2. **No mouse support** - Can't click, scroll wheel doesn't work
3. **Polling-based input** - `select()` with 0.5s timeout, cbreak mode hacks
4. **Manual refresh** - `live.refresh()` in loop
5. **Platform-specific code** - msvcrt vs termios branches

### Data Flow (Must Preserve)

```
watcher.py threads → log_queue (deque) → UI displays
                   ↘ state.py         → UI reads
                   ↘ config.py        → UI reads/writes
```

---

## Target Architecture

### New ui_textual.py Structure

```
GengoWatcherApp(App)
├── CSS               - Embedded stylesheet
├── BINDINGS          - Keyboard shortcuts
├── compose()         - Widget tree
├── on_mount()        - Initialize data, start refresh worker
├── Reactive attrs    - status, ws_status, rss_status, etc.
├── watch_*()         - Auto-update widgets when attrs change
├── action_*()        - Keyboard shortcut handlers
├── on_input_submitted() - Command handling
└── refresh_worker()  - Background thread for data polling
```

### Widget Mapping

| Current Rich | Textual Widget | Notes |
|--------------|----------------|-------|
| `Layout["header"]` | `Static` in `Vertical` | Config display |
| `Layout["runtime_status"]` | `Static` with reactive updates | Stats grid |
| `Layout["recent_activity"]` | `Log(auto_scroll=True)` | **Scrollable!** |
| `Layout["output"]` | `Log(auto_scroll=True)` | **Scrollable!** |
| `Layout["footer"]` | `Static` | Status bar |
| `Layout["input"]` | `Input` widget | Native input handling |
| `Text.assemble()` | `Text.assemble()` | Rich integration |
| `Table.grid()` | `DataTable` or `Static` | Layout tables |

---

## Implementation Plan

### Phase 1: Scaffold (New File)

Create `src/gengowatcher/ui_textual.py` alongside existing `ui.py`.

```python
# Minimal structure - NO business logic changes
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Log, Input
from textual.reactive import reactive
from textual import work

class GengoWatcherApp(App):
    CSS = """..."""  # See Phase 2
    BINDINGS = [...]  # See Phase 3
    
    def __init__(self, watcher, config, state, log_queue):
        super().__init__()
        self.watcher = watcher
        self.config = config
        self.state = state
        self.log_queue = log_queue
        self._log_queue_lock = threading.Lock()
    
    def compose(self) -> ComposeResult:
        yield Header()
        # ... widgets
        yield Footer()
```

### Phase 2: Layout & CSS

```css
Screen {
    layout: vertical;
}

#main-container {
    layout: horizontal;
    height: 1fr;
}

#left-panel {
    width: 60%;
    layout: vertical;
}

#right-panel {
    width: 40%;
}

#header-panel {
    height: 8;
    border: solid $accent;
}

#runtime-status {
    height: 12;
    border: solid $accent;
}

#activity-log {
    height: 1fr;
    border: solid $success;
}

#output-log {
    height: 100%;
    border: solid $primary;
}

#status-bar {
    height: 3;
    background: $surface;
}

Input {
    dock: bottom;
}
```

### Phase 3: Keyboard Bindings

```python
BINDINGS = [
    ("q", "quit", "Quit"),
    ("escape", "quit", "Quit"),
    ("c", "check", "Check Now"),
    ("p", "pause", "Pause"),
    ("r", "resume", "Resume"),
    ("h", "help", "Help"),
    ("ctrl+l", "clear", "Clear"),
]
```

### Phase 4: Reactive Data

```python
class GengoWatcherApp(App):
    # Reactive attributes auto-trigger watch_* methods
    ws_status = reactive("Disabled")
    rss_status = reactive("Idle")
    app_status = reactive("Running")
    jobs_session = reactive(0)
    jobs_total = reactive(0)
    
    def watch_ws_status(self, old: str, new: str) -> None:
        self.query_one("#ws-indicator", Static).update(
            self._format_ws_status(new)
        )
```

### Phase 5: Background Refresh Worker

```python
@work(thread=True)
def refresh_data(self) -> None:
    """Poll watcher state and update UI every 500ms."""
    while not self.watcher.shutdown_event.is_set():
        # Update reactive attributes (triggers watch_* methods)
        self.call_from_thread(self._sync_state)
        
        # Drain log queue to Log widget
        self.call_from_thread(self._drain_log_queue)
        
        time.sleep(0.5)

def _sync_state(self) -> None:
    """Sync watcher state to reactive attributes."""
    self.ws_status = self.watcher.websocket_status
    self.rss_status = self.watcher.rss_action
    self.jobs_session = self.watcher.session_new_entries
    self.jobs_total = self.state.total_new_entries_found
    # ... etc

def _drain_log_queue(self) -> None:
    """Move items from log_queue to Log widget."""
    log_widget = self.query_one("#activity-log", Log)
    with self._log_queue_lock:
        while self.log_queue:
            item = self.log_queue.popleft()
            log_widget.write_line(str(item))
```

### Phase 6: Command Handling

```python
def on_input_submitted(self, event: Input.Submitted) -> None:
    """Handle command input."""
    command_str = event.value.strip()
    event.input.clear()
    
    if not command_str:
        return
    
    # Reuse existing command dispatch logic
    self._execute_command(command_str)

def _execute_command(self, command_str: str) -> None:
    """Execute command - port from current handle_command()."""
    parts = command_str.lower().split()
    cmd_alias, args = parts[0], parts[1:]
    command = self.alias_map.get(cmd_alias)
    
    if not command:
        self.notify(f"Unknown command: {cmd_alias}", severity="error")
        return
    
    handler = self.commands[command]["handler"]
    # ... existing logic
```

### Phase 7: Command Handlers

Port all `_handle_*` methods. Most are simple config toggles that need minimal changes:

```python
# Before (Rich)
def _handle_toggle_sound(self, args=None):
    current_state = self.config.get("Watcher", "enable_sound")
    self.config.set("Watcher", "enable_sound", not current_state)
    self.config.save_config()
    self.watcher.logger.info(f"Sound {'enabled' if not current_state else 'disabled'}.")

# After (Textual) - identical, just add notify
def _handle_toggle_sound(self, args=None):
    current_state = self.config.get("Watcher", "enable_sound")
    self.config.set("Watcher", "enable_sound", not current_state)
    self.config.save_config()
    status = "enabled" if not current_state else "disabled"
    self.watcher.logger.info(f"Sound {status}.")
    self.notify(f"Sound {status}")
```

### Phase 8: Entry Point

Update `main.py` to use new UI:

```python
# In main.py
def main():
    # ... existing setup ...
    
    # Option A: Replace entirely
    from .ui_textual import GengoWatcherApp
    app = GengoWatcherApp(watcher, config, state, log_queue)
    app.run()
    
    # Option B: Feature flag
    if config.get("UI", "use_textual"):
        from .ui_textual import GengoWatcherApp
        app = GengoWatcherApp(watcher, config, state, log_queue)
        app.run()
    else:
        from .ui import CommandLineInterface
        cli = CommandLineInterface(watcher, config, state, console, log_queue)
        cli.run()
```

---

## File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `ui_textual.py` | **NEW** | New Textual-based UI (~600 lines) |
| `ui.py` | KEEP | Keep as fallback (optional) |
| `main.py` | MODIFY | Update to use new UI |
| `requirements.txt` | MODIFY | Add `textual>=0.47.0` |
| `watcher.py` | NONE | No changes |
| `state.py` | NONE | No changes |
| `config.py` | NONE | No changes |

---

## Migration Checklist

### Pre-Migration
- [ ] Install textual: `pip install textual`
- [ ] Test basic Textual app works in terminal
- [ ] Backup current ui.py

### Phase 1: Scaffold
- [ ] Create ui_textual.py with basic App class
- [ ] Import watcher, config, state, log_queue
- [ ] Verify app launches (empty)

### Phase 2: Layout
- [ ] Implement compose() with all containers
- [ ] Add CSS for layout sizing
- [ ] Verify layout matches current appearance

### Phase 3: Static Panels
- [ ] Port _get_header_panel → Static widget
- [ ] Port _get_runtime_status_panel → Static widget
- [ ] Port _get_status_bar → Static widget

### Phase 4: Scrollable Panels
- [ ] Replace _get_recent_activity_panel with Log widget
- [ ] Replace _get_output_panel with Log widget
- [ ] Verify auto-scroll works

### Phase 5: Data Binding
- [ ] Add reactive attributes for all dynamic data
- [ ] Implement watch_* methods
- [ ] Start refresh_data worker on mount
- [ ] Verify live updates work

### Phase 6: Input Handling
- [ ] Replace raw keyboard handling with Input widget
- [ ] Port command dispatch logic
- [ ] Add BINDINGS for shortcuts

### Phase 7: Commands
- [ ] Port all 25+ command handlers
- [ ] Test each command works
- [ ] Add notify() calls for feedback

### Phase 8: Polish
- [ ] Add mouse scroll support (automatic with Log)
- [ ] Add click handlers if needed
- [ ] Test on Windows (if applicable)
- [ ] Remove termios/msvcrt code

### Post-Migration
- [ ] Update requirements.txt
- [ ] Test full workflow
- [ ] Remove old ui.py (or keep as fallback)

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Textual API changes | Low | Medium | Pin version in requirements |
| Terminal compatibility | Low | High | Test on target terminals |
| Performance with high log volume | Medium | Medium | Use max_lines on Log widget |
| Windows compatibility | Medium | Medium | Test on Windows if needed |
| Learning curve | Low | Low | Textual is well-documented |

---

## Estimated Effort

| Phase | Estimated Time |
|-------|----------------|
| Phase 1-2: Scaffold & Layout | 1 hour |
| Phase 3: Static Panels | 1 hour |
| Phase 4: Scrollable Panels | 30 min |
| Phase 5: Data Binding | 1.5 hours |
| Phase 6: Input Handling | 1 hour |
| Phase 7: Commands | 2 hours |
| Phase 8: Polish | 1 hour |
| **Total** | **~8 hours** |

---

## Success Criteria

1. ✅ Activity log scrolls with mouse wheel and keyboard
2. ✅ Output panel scrolls with mouse wheel and keyboard
3. ✅ All 25+ commands work identically
4. ✅ Keyboard shortcuts work (q, p, r, c, etc.)
5. ✅ Live data updates every 500ms
6. ✅ No termios/msvcrt platform code
7. ✅ Clean shutdown on Ctrl+C / q

---

## Appendix: Widget Reference

### Log Widget (Most Important)

```python
# Create scrollable log
log = Log(auto_scroll=True, max_lines=1000, highlight=True, id="activity")

# Add lines from background thread
self.call_from_thread(log.write_line, "[green]Job found![/green]")

# Clear
log.clear()
```

### Input Widget

```python
# Create input with placeholder
input = Input(placeholder="Type command...", id="cmd-input")

# Handle submission
def on_input_submitted(self, event: Input.Submitted):
    command = event.value
    event.input.clear()
```

### Reactive Pattern

```python
class MyApp(App):
    counter = reactive(0)  # Define
    
    def watch_counter(self, old, new):  # React
        self.query_one("#display").update(f"Count: {new}")
    
    def increment(self):
        self.counter += 1  # Change triggers watch_counter
```
