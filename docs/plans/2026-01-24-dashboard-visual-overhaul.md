# Dashboard Visual Overhaul Design

**Date:** 2026-01-24
**Status:** Approved
**Branch:** `feat/ui-revamp` (continuation)

---

## Overview

Transform the GengoWatcher TUI into a polished command-center interface with improved information density, visual hierarchy, panel styling, and color usage.

## Layout Structure

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ◆ GENGOWATCHER v2.0                    Session: 0h 32m  │  14:32:15 JST  │  ← Title Bar (3 lines)
├─────────────────────────────────────────────────────────────────────────────┤
│  [Dashboard]  [Jobs]  [Activity]  [Output]  [Charts]  [Stats]               │  ← Tab Bar (6 tabs)
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ ▲ 12     │ │ ✓ 3      │ │ $ 45.50  │ │ ~4.2/hr  │ │ ≥$0.05   │           │  ← Metrics Cards (5)
│  │ Found    │ │ Accepted │ │ Value    │ │ Rate     │ │ Min/Word │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│  ● WS ∿∿∿ Live   ◉ Email ↻ 45s   ◎ Web ○ Idle   ⧗ Captcha   ⇄ Workflow     │  ← Status Row
├───────────────────────────────────┬─────────────────────────────────────────┤
│  ┌─ Recent Activity ────────────┐ │ ┌─ Jobs/Hour ─────────────────────────┐ │
│  │ 14:32 Job detected #1234     │ │ │     ╭─╮                             │ │
│  │ 14:31 Email checked (0)      │ │ │   ╭─╯ ╰╮    ╭╮                      │ │  ← Four Quadrants
│  │ 14:30 WebSocket connected    │ │ │ ╭─╯    ╰────╯╰─                     │ │
│  └──────────────────────────────┘ │ └─────────────────────────────────────┘ │
│  ┌─ Jobs Preview ───────────────┐ │ ┌─ Configuration ─────────────────────┐ │
│  │ #1234  JA→EN  420w   $12.60  │ │ │ Languages: JA↔EN                    │ │
│  │ #1231  EN→JA  180w    $5.40  │ │ │ Check Interval: 60s                 │ │
│  └──────────────────────────────┘ │ └─────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│  > help_                                                                    │  ← Command Input
├─────────────────────────────────────────────────────────────────────────────┤
│  q:Quit  c:Check  p:Pause  ?:Help                                          │  ← Footer
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Kanagawa Color Application

### Visual Hierarchy (3 depth levels)

| Element | Variable | Hex | Purpose |
|---------|----------|-----|---------|
| Deepest BG | `$surface-darken-1` | `#16161D` | Screen background |
| Main Surface | `$surface` | `#1F1F28` | Tab pane backgrounds |
| Elevated | `$surface-lighten-1` | `#2A2A37` | Cards, panels |
| Borders | `$surface-lighten-2` | `#363646` | Panel borders |
| Title Bar BG | `$primary` | `#7E9CD8` | Header emphasis |
| Active Tab | `$accent` | `#7AA89F` | Tab highlight |
| Primary Text | `$text` | `#DCD7BA` | Main content |
| Muted Text | `$text-muted` | `#727169` | Labels, secondary |

### Status Indicator Colors

| Status | Color | Hex |
|--------|-------|-----|
| Live/Good | `$success` | `#98BB6C` |
| Working/Polling | `$warning` | `#DCA561` |
| Error | `$error` | `#C34043` |
| Idle/Disabled | `$text-muted` | `#727169` |

### Metric Card Accent Colors (left border)

| Card | Color | Variable |
|------|-------|----------|
| Found | Blue | `$primary` |
| Accepted | Green | `$success` |
| Value | Yellow | `$warning` |
| Rate | Aqua | `$accent` |
| Min/Word | Violet | `$secondary` |

---

## Component Specifications

### Title Bar (3 lines)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ◆ GENGOWATCHER v2.0                                                        │  Line 1: Brand + version
│  ─────────────────────────────────────────────────────────────────────────  │  Line 2: Separator
│  Session: 0h 32m 15s              │              Fri Jan 24  14:32:15 JST  │  Line 3: Session + Clock
└─────────────────────────────────────────────────────────────────────────────┘
```

- Background: `$surface-lighten-1` with `$primary` left accent
- Brand: `$primary` bold
- Session/clock: `$text`

### Metrics Cards Row

- 5 cards: Found, Accepted, Value, Rate, Min/Word
- Each card: 12-14 chars wide, 3 lines tall
- Background: `$surface-lighten-1`
- Border: `round` with card-specific accent
- Value: `$text` bold
- Label: `$text-muted`
- 1-unit gaps between cards

### Status Row with Live Indicators

```
● WS ∿∿∿ Live   ◉ Email ↻ 45s   ◎ Web ○ Idle   ⧗ Captcha: Ready   ⇄ Workflow: Auto
```

**Icons (consistent Unicode):**

| Feature | Icon | States |
|---------|------|--------|
| WebSocket | `●` | `∿∿∿` Live, `◐◑◒◓` Connecting, `✗` Offline |
| Email | `◉` | `↻` Polling, `Next: 45s` Idle, `⚠` Error |
| Website | `◎` | `◐◑◒◓` Scraping, `○` Idle |
| Captcha | `⧗` | Ready, Solving..., Failed |
| Workflow | `⇄` | Auto, Manual, Review |

### Four-Quadrant Dashboard

**Left Column (50%):**

| Pane | Content | Border Color |
|------|---------|--------------|
| Recent Activity | Mini RichLog, 5-8 lines | `$success` |
| Jobs Preview | Mini DataTable, 3-5 rows | `$primary` |

**Right Column (50%):**

| Pane | Content | Border Color |
|------|---------|--------------|
| Jobs/Hour | Mini sparkline chart | `$accent` |
| Configuration | Key-value pairs, 4-6 items | `$secondary` |

---

## Stats Tab (New)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ┌─ Session ───────────────┐  ┌─ All-Time ─────────────────┐               │
│  │ Duration    0h 32m 15s  │  │ Total Jobs     1,247       │               │
│  │ Jobs Found       12     │  │ Total Value    $3,842.50   │               │
│  │ Jobs Accepted     3     │  │ Avg Job Value  $3.08       │               │
│  │ Value         $45.50    │  │ Best Day       $127.40     │               │
│  │ Rate          4.2/hr    │  │ Sessions       89          │               │
│  └─────────────────────────┘  └────────────────────────────┘               │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─ By Source ─────────────────────────────────────────────────────────────┐│
│  │ WebSocket   ████████████████████░░░░  842 jobs (68%)                    ││
│  │ Email       ██████████░░░░░░░░░░░░░░  312 jobs (25%)                    ││
│  │ Website     ███░░░░░░░░░░░░░░░░░░░░░   93 jobs (7%)                     ││
│  └─────────────────────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─ By Language ───────────────┐  ┌─ Best Times ───────────────────────────┐│
│  │ JA→EN   ████████████  (50%) │  │ Peak Hour     14:00-15:00  (6.2/hr)   ││
│  │ EN→JA   ████████░░░░  (33%) │  │ Peak Day      Wednesday    (48 avg)   ││
│  │ ZH→EN   ████░░░░░░░░  (11%) │  │ Slowest Hour  04:00-05:00  (0.3/hr)   ││
│  │ Other   ██░░░░░░░░░░   (6%) │  │ Slowest Day   Sunday       (12 avg)   ││
│  └─────────────────────────────┘  └────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─ Earnings (7 days) ─────────────────────────────────────────────────────┐│
│  │ Mon $42  ████████   Wed $51  ██████████   Fri $45  █████████            ││
│  │ Tue $38  ███████    Thu $29  ██████       Sat $22  ████                 ││
│  │                                           Sun $18  ████                 ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

**Sections:**
- Session stats (`$primary` border)
- All-Time totals (`$secondary` border)
- By Source - horizontal bar chart
- By Language - horizontal bar chart
- Best Times - peak/slowest hour and day (`$warning` border)
- Earnings - 7-day bars

---

## Implementation Notes

### New Widget Classes

```python
class TitleBar(Static)           # 3-line branded header
class MetricCard(Static)         # Individual metric box
class MetricsRow(Horizontal)     # Container for 5 cards
class StatusIndicator(Static)    # Single status with live animation
class StatusRow(Static)          # Container for all status indicators
class DashboardQuadrant(Static)  # Wrapper for each pane
class ActivityPreview(RichLog)   # Mini activity log
class JobsPreview(DataTable)     # Mini jobs table
class StatsPanel(Static)         # Stats tab content
```

### Files to Modify

| File | Changes |
|------|---------|
| `ui_textual.py` | New widgets, refactored `compose()`, Stats tab |
| `gengo_watcher.tcss` | All new styles, spacing, visual hierarchy |
| `state.py` or new `stats.py` | Historical stats persistence |

### Command Input Note

Command input panel requires commands configured in `GengoWatcherApp._init_commands()`. May need additional commands for Stats tab (e.g., `stats reset`, `stats export`).

### Data Persistence Note

Stats tab features require tracking:
- Job timestamps (time-of-day/day-of-week analysis)
- Source attribution (WebSocket/Email/Website)
- Historical totals (across sessions)

Needs enhancement to `state.json` or dedicated stats store.

---

*Design approved: 2026-01-24*
