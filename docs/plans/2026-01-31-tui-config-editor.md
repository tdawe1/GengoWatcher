# TUI Config Editor Implementation Plan


**Goal:** Add a Textual TUI editor so all `config.ini` settings can be edited in-app without restarting.

**Architecture:** Add a `ConfigEditorScreen` that lists sections/options, edits values, and saves via `GengoWatcher.set_config_value`. Track a restart-required flag in the app and surface it in the UI. Use config defaults to coerce input into the correct type (bool/int/float/list/str), falling back to string for unknown sections.

**Tech Stack:** Python, Textual, pytest

---

### Task 1: Add config value coercion helper

**Files:**
- Modify: `src/gengowatcher/config.py`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

Add tests that verify parsing for bool/int/float/list/str based on defaults.

```python
def test_coerce_value_uses_defaults():
    config = AppConfig()
    assert config.coerce_value("Watcher", "enable_notifications", "false") is False
    assert config.coerce_value("Watcher", "check_interval", "45") == 45
    assert config.coerce_value("Watcher", "min_reward", "3.5") == 3.5
    assert config.coerce_value("WebServer", "cors_origins", '["http://a"]') == ["http://a"]
    assert config.coerce_value("Custom", "note", "hello") == "hello"
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py::test_coerce_value_uses_defaults -v`

Expected: FAIL with `AttributeError: 'AppConfig' object has no attribute 'coerce_value'`

**Step 3: Write minimal implementation**

Add to `AppConfig`:

```python
def coerce_value(self, section: str, key: str, raw: str):
    defaults = self.DEFAULT_CONFIG.get(section, {})
    default = defaults.get(key)
    if isinstance(default, bool):
        return self.getboolean(section, key, fallback=default) if raw is None else str(raw).strip().lower() in ("true", "1", "yes", "on", "enabled")
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, list):
        return json.loads(raw) if raw else []
    return raw
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_config.py::test_coerce_value_uses_defaults -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/gengowatcher/config.py tests/test_config.py
git commit -m "feat: add config value coercion helper"
```

---

### Task 2: Add ConfigEditorScreen UI

**Files:**
- Modify: `src/gengowatcher/ui_textual.py`
- Modify: `src/gengowatcher/gengo_watcher.tcss`
- Test: `tests/test_ui_textual_components.py`

**Step 1: Write the failing test**

Add a Textual test app that opens the screen and saves a value.

```python
@pytest.mark.asyncio
async def test_config_editor_saves_value(mock_config, mock_watcher):
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield ConfigPreview(config=mock_config)

        def on_mount(self):
            self.push_screen(ConfigEditorScreen(config=mock_config, watcher=mock_watcher))

    app = TestApp()
    async with app.run_test() as pilot:
        editor = app.query_one(ConfigEditorScreen)
        editor._select_section("Watcher")
        editor._select_option("check_interval")
        editor.value_input.value = "99"
        await editor._save_value()
        mock_watcher.set_config_value.assert_called_with("Watcher", "check_interval", 99)
        assert app.restart_required is True
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_ui_textual_components.py::test_config_editor_saves_value -v`

Expected: FAIL with `NameError: ConfigEditorScreen is not defined`

**Step 3: Write minimal implementation**

Add in `ui_textual.py`:

```python
class ConfigEditorScreen(ModalScreen):
    def __init__(self, config: AppConfig, watcher: "GengoWatcher", **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.watcher = watcher
        self.section_list = ListView(id="config-sections")
        self.option_list = ListView(id="config-options")
        self.value_input = Input(id="config-value")

    def compose(self):
        yield Static("Edit configuration (all changes require restart)", id="config-editor-banner")
        with Horizontal(id="config-editor-panels"):
            yield self.section_list
            yield self.option_list
        yield self.value_input
        with Horizontal(id="config-editor-actions"):
            yield Button("Save", id="config-save")
            yield Button("Cancel", id="config-cancel")

    def on_mount(self):
        self._load_sections()

    def _load_sections(self):
        sections = list(self.config.list_all().keys())
        for section in sections:
            self.section_list.append(ListItem(Label(section), name=section))

    def _select_section(self, section: str):
        self.option_list.clear()
        for key in self.config.list_all()[section].keys():
            self.option_list.append(ListItem(Label(key), name=key))

    def _select_option(self, option: str):
        section = self._current_section
        value = self.config.get(section, option)
        self.value_input.value = json.dumps(value) if isinstance(value, list) else str(value)

    async def _save_value(self):
        section = self._current_section
        option = self._current_option
        new_value = self.config.coerce_value(section, option, self.value_input.value)
        self.watcher.set_config_value(section, option, new_value)
        self.app.restart_required = True
        self.dismiss()
```

Also add a simple style block in `gengo_watcher.tcss` for the editor layout and banner.

**Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_ui_textual_components.py::test_config_editor_saves_value -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/gengowatcher/ui_textual.py src/gengowatcher/gengo_watcher.tcss tests/test_ui_textual_components.py
git commit -m "feat: add config editor screen"
```

---

### Task 3: Wire editor to app bindings and UI refresh

**Files:**
- Modify: `src/gengowatcher/ui_textual.py`
- Test: `tests/test_ui_textual_components.py`

**Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_edit_binding_opens_editor(mock_config, mock_state, mock_watcher, mock_stats):
    app = GengoWatcherApp(mock_config, mock_state, mock_watcher, mock_stats)
    async with app.run_test() as pilot:
        await pilot.press("e")
        assert app.query_one(ConfigEditorScreen) is not None
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_ui_textual_components.py::test_edit_binding_opens_editor -v`

Expected: FAIL with no screen opened

**Step 3: Write minimal implementation**

Add to `GengoWatcherApp`:

```python
BINDINGS = [
    ("q", "quit", "Quit"),
    ("c", "check", "Check"),
    ("p", "pause", "Pause"),
    ("e", "edit_config", "Edit Config"),
    ("?", "help", "Help"),
]

def action_edit_config(self):
    self.push_screen(ConfigEditorScreen(config=self.config, watcher=self.watcher))
```

Add a `restart_required` flag on the app, and update `TitleBar` with a method to refresh its config info and display a restart warning when the flag is set. After saving, refresh `ConfigPreview` and `TitleBar`.

**Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_ui_textual_components.py::test_edit_binding_opens_editor -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/gengowatcher/ui_textual.py tests/test_ui_textual_components.py
git commit -m "feat: wire config editor to app bindings"
```

---

### Task 4: Smoke tests (targeted)

**Step 1: Run targeted tests**

Run:

```bash
.venv/bin/pytest tests/test_config.py::test_coerce_value_uses_defaults -v
.venv/bin/pytest tests/test_ui_textual_components.py::test_config_editor_saves_value -v
.venv/bin/pytest tests/test_ui_textual_components.py::test_edit_binding_opens_editor -v
```

Expected: PASS

**Step 2: Commit (if needed)**

```bash
git status --short
```

If clean, no commit needed.

---

## Notes

- Baseline `pytest` currently fails in this repo due to missing modules in `scripts/` tests and missing `httpx` dependency. Use targeted tests above for this change set.
- All config edits must set `restart_required = True` and show the warning; this is intentional per requirement ("all of it").
