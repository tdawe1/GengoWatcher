# TUI direction prototypes

The original gallery remains isolated visual work. The selected Ratatui Garden
implementation has since been promoted into the live GengoWatcher client while
retaining `--demo` and deterministic preview modes.

```bash
PYTHONPATH=src python prototypes/tui_design_gallery.py beacon
PYTHONPATH=src python prototypes/tui_design_gallery.py ledger
PYTHONPATH=src python prototypes/tui_design_gallery.py scope
PYTHONPATH=src python prototypes/tui_design_gallery.py garden
PYTHONPATH=src python prototypes/tui_design_gallery.py arcade
```

Render comparable 140×42 SVG previews:

```bash
env -u NO_COLOR PYTHONPATH=src python prototypes/tui_design_gallery.py \
  --render prototypes/tui-previews
```

Framework recommendations are labels, not implementation commitments:

| Concept | Production framework | Direction |
| --- | --- | --- |
| Beacon | Python / Textual | Alert-first minimalism |
| Ledger | Python / Textual | Light editorial comparison |
| Scope | Rust / Ratatui | Diagnostic instrument |
| Garden | Python / Textual and Rust / Ratatui | Comprehensive operations dashboard |
| Arcade | Go / Bubble Tea | Fast reward-driven board |

## Comprehensive Garden comparison

The selected Garden direction is also implemented as two isolated, interactive
prototypes. Both show alerting, the available queue, active work, history,
analytics, system health, and recent activity.

```bash
PYTHONPATH=src python3 prototypes/garden_textual.py
cargo run --manifest-path prototypes/garden-ratatui/Cargo.toml -- --demo
```

Use `1`–`6` to change workspace and `q` to exit. See
[GARDEN_COMPARISON.md](GARDEN_COMPARISON.md) for matching previews, rendering
commands, and framework tradeoffs.

The normal application launches Ratatui with real watcher data:

```bash
PYTHONPATH=src python3 -m gengowatcher.main
```
