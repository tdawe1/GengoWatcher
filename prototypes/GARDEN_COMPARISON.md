# Garden framework comparison

This comparison began with one information design implemented in two terminal UI
frameworks. Both versions retain the same six workspaces:
Overview, Available Jobs, Active Work, History, Analytics, and System. Neither
preview renderer needs a production GengoWatcher connection. The Ratatui version
is now also the live application client.

## Run the prototypes

Textual:

```bash
PYTHONPATH=src python3 prototypes/garden_textual.py
PYTHONPATH=src python3 prototypes/garden_textual.py --view analytics
```

Ratatui:

```bash
cargo run --manifest-path prototypes/garden-ratatui/Cargo.toml -- --demo
cargo run --manifest-path prototypes/garden-ratatui/Cargo.toml -- --demo --view analytics
```

In either version, keys `1` through `6` switch workspaces and `q` exits. Ratatui
also provides authenticated live actions with confirmation for acceptance and
cancellation.

## Render previews

Textual renders all six views at 150 x 44 cells:

```bash
PYTHONPATH=src python3 prototypes/garden_textual.py \
  --render prototypes/garden-previews
```

Ratatui uses its deterministic test backend to render the same views and size:

```bash
cargo run --manifest-path prototypes/garden-ratatui/Cargo.toml -- \
  --render prototypes/garden-ratatui-previews
```

## Workspace previews

| Workspace | Textual | Ratatui |
| --- | --- | --- |
| Overview | [Open Textual preview](garden-previews/garden-textual-overview.svg) | [Open Ratatui preview](garden-ratatui-previews/garden-ratatui-overview.svg) |
| Available Jobs | [Open Textual preview](garden-previews/garden-textual-jobs.svg) | [Open Ratatui preview](garden-ratatui-previews/garden-ratatui-jobs.svg) |
| Active Work | [Open Textual preview](garden-previews/garden-textual-work.svg) | [Open Ratatui preview](garden-ratatui-previews/garden-ratatui-work.svg) |
| History | [Open Textual preview](garden-previews/garden-textual-history.svg) | [Open Ratatui preview](garden-ratatui-previews/garden-ratatui-history.svg) |
| Analytics | [Open Textual preview](garden-previews/garden-textual-analytics.svg) | [Open Ratatui preview](garden-ratatui-previews/garden-ratatui-analytics.svg) |
| System | [Open Textual preview](garden-previews/garden-textual-system.svg) | [Open Ratatui preview](garden-ratatui-previews/garden-ratatui-system.svg) |

The Overview is the primary comparison screen. It exposes the current alert,
available queue, active workflow, session metrics, system health, and recent
activity at the same time. The other workspaces expand those areas without
changing the information hierarchy.

## Framework tradeoffs

| Area | Python / Textual | Rust / Ratatui and Crossterm |
| --- | --- | --- |
| Visual fidelity | CSS, higher-level widgets, and built-in SVG capture make spacing, panel styling, and stateful controls quick to refine. Textual's widget defaults can remain visible unless deliberately overridden. | Cell-level rendering gives precise control over every region and style. Matching complex controls requires more explicit layout and rendering code, but the result has fewer framework-specific visual assumptions. |
| Performance | More than sufficient for a monitoring dashboard at ordinary refresh rates. Python and Textual add runtime and widget-tree overhead, which matters mainly in very hot update paths or on constrained systems. | Low overhead, predictable redraws, and a small runtime profile suit frequent event updates and large terminal tables. Application code must still avoid unnecessary full-data work between frames. |
| Keyboard input | Declarative bindings and focus management reduce implementation work. Tables and buttons provide familiar behavior with little custom code. | Crossterm events are direct and fast, but focus, selection, shortcuts, and conflict handling are application responsibilities. This provides control at the cost of more state-machine code. |
| Mouse input | Clickable widgets, hover states, scrolling, and focus behavior are largely provided by the framework. | Mouse regions, hit testing, scroll handling, and selection changes are explicit. This is straightforward for fixed navigation and tables, but grows with richer interactions. |
| Implementation complexity | The existing application is Python and already uses Textual, so shared models and callbacks can remain in-process. Layout and styling are compact, though framework lifecycle behavior must be tested. | Strong types make view state and event transitions explicit. The renderer is deterministic and easy to exercise with a test backend, but equivalent widgets and application integration require more code. |
| Distribution | Fits the current Python package and dependency workflow. Users still need the Python environment and native or browser dependencies already required by GengoWatcher. | Can ship as a standalone native binary with no Python interpreter. Cross-platform releases require Rust build targets, artifact signing, and a strategy for coordinating with the existing Python process. |
| GengoWatcher integration | Lowest-friction path: import existing configuration, watcher state, and services directly while preserving current thread and async boundaries. Coupling the UI to mutable application objects remains a design risk. | Best treated as a separate presentation process consuming a stable local API or event protocol. That boundary improves isolation, but introduces protocol versioning, lifecycle coordination, authentication, and packaging work. |

## Current boundary

The SVG previews still use deterministic sample values so visual changes remain
comparable. In normal operation, Ratatui consumes the existing authenticated
loopback API for status, jobs, events, statistics, and commands. Watcher and
browser automation logic remain in Python; presentation state and terminal
interaction remain in Rust.
