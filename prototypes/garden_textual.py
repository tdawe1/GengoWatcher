"""Comprehensive Garden-direction prototype implemented with Textual.

This is isolated sample-data UI work. It does not import or modify GengoWatcher.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Grid, Horizontal, Vertical
from textual.widgets import Button, ContentSwitcher, DataTable, Footer, Static

JOBS = [
    ("481516", "JA → EN", "$18.40", "WebSocket", "Available", "04:03"),
    ("481517", "DE → EN", "$12.75", "Email", "Details", "08:32"),
    ("481518", "FR → EN", "$8.20", "RSS", "Accepted", "50:10"),
    ("481519", "EN → JA", "$31.00", "Website", "Available", "01:30"),
    ("481520", "JA → DE", "$22.10", "WebSocket", "Expired", "00:00"),
]


class GardenApp(App[None]):
    TITLE = "GengoWatcher · Garden · Textual"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "show('overview')", "Overview", show=False),
        Binding("2", "show('jobs')", "Jobs", show=False),
        Binding("3", "show('work')", "Active Work", show=False),
        Binding("4", "show('history')", "History", show=False),
        Binding("5", "show('analytics')", "Analytics", show=False),
        Binding("6", "show('system')", "System", show=False),
    ]
    CSS = """
    $ink: #294438;
    $muted: #6c806f;
    $ground: #eaf0e5;
    $paper: #f7f8f2;
    $canopy: #d6e4d0;
    $line: #adbea8;
    $leaf: #557b58;
    $orange: #d9874f;
    $red: #b45b4b;

    Screen { background: $ground; color: $ink; }
    #header { height: 5; padding: 1 2; background: $canopy; border-bottom: solid $line; }
    #brand { width: 1fr; color: $ink; text-style: bold; }
    #header-health { width: 42; text-align: right; color: $muted; }
    #body { height: 1fr; }
    #nav { width: 22; padding: 1; background: #e0e9da; border-right: solid $line; }
    #nav-title { height: 2; color: $muted; text-style: bold; }
    #nav Button { width: 100%; height: 3; border: none; background: transparent; color: $ink; text-align: left; }
    #nav Button:hover { background: #ccdcca; }
    #nav Button.selected { background: $leaf; color: #ffffff; text-style: bold; }
    #nav-spacer { height: 1fr; }
    #nav-summary { height: 7; padding: 1; border: round $line; background: $paper; color: $muted; }
    ContentSwitcher { width: 1fr; height: 100%; }
    .workspace { height: 100%; padding: 1 2; }
    .workspace-title { height: 2; color: $leaf; text-style: bold; }
    .panel-title { height: 2; color: $muted; text-style: bold; border-bottom: solid $line; }
    .panel { background: $paper; border: round $line; padding: 1; }
    .metric { background: $paper; border: round $line; padding: 1; height: 5; }
    .metric-value { color: $ink; text-style: bold; }
    .metric-label { color: $muted; }
    #statusbar { height: 3; padding: 1 2; background: $canopy; border-top: solid $line; color: $muted; }
    Footer { height: 1; background: $ground; color: $muted; }
    FooterKey > .footer-key--key { color: $leaf; }

    /* Overview: every major capability is visible without navigation. */
    #alert-strip { height: 7; padding: 1 2; background: #f4e1cd; border: round $orange; }
    #alert-copy { width: 1fr; }
    #alert-label { height: 1; color: #98512d; text-style: bold; }
    #alert-main { height: 2; color: #6d3e27; text-style: bold; }
    #alert-meta { color: #8b664d; }
    #alert-actions { width: 36; align: right middle; }
    #alert-actions Button { width: 1fr; height: 3; border: none; background: $orange; color: #ffffff; text-style: bold; }
    #alert-actions .secondary { background: transparent; color: #98512d; border: round $orange; }
    #overview-grid { height: 1fr; grid-size: 2 2; grid-columns: 3fr 2fr; grid-rows: 1fr 1fr; grid-gutter: 1 2; margin-top: 1; }
    #overview-jobs, #overview-work, #overview-metrics, #overview-system { height: 1fr; }
    .job-line { height: 2; padding: 0 1; }
    .work-stage { height: 3; padding: 1; margin-bottom: 1; background: #e5ede0; }
    #overview-chart { color: $leaf; }
    #overview-log { color: $muted; }

    /* Available Jobs: queue + decision inspector. */
    #jobs-layout { height: 1fr; }
    #jobs-list { width: 1fr; margin-right: 2; }
    #jobs-inspector { width: 36; }
    #jobs-table, #history-table { height: 1fr; background: $paper; border: none; color: $ink; }
    DataTable > .datatable--header { background: $leaf; color: #ffffff; text-style: bold; }
    DataTable > .datatable--cursor { background: #d9e6d4; color: $ink; }
    #job-detail { height: 1fr; padding: 2; }
    #job-buttons { height: 4; }
    #job-buttons Button { width: 1fr; height: 3; border: none; background: $leaf; color: #ffffff; }
    #job-buttons .reject { background: transparent; color: $red; border: round $red; }

    /* Active work: explicit stages and deadlines. */
    #work-board { height: 1fr; grid-size: 3 1; grid-columns: 1fr 1fr 1fr; grid-gutter: 2; }
    .work-column { height: 1fr; background: $paper; border: round $line; padding: 1; }
    .work-column-title { height: 2; color: $leaf; text-style: bold; }
    .work-card { height: 7; margin-top: 1; padding: 1; background: #e4ecdf; border-left: thick $leaf; }
    .urgent { background: #f3dfcf; border-left: thick $orange; }

    /* History: data-first but still visually part of Garden. */
    #history-toolbar { height: 4; padding: 1; background: $paper; border: round $line; }
    #history-filter { width: 1fr; color: $muted; }
    #history-summary { width: 44; text-align: right; color: $leaf; text-style: bold; }
    #history-table { margin-top: 1; }

    /* Analytics: metrics and terminal-native charts. */
    #metric-row { height: 6; grid-size: 4 1; grid-columns: 1fr 1fr 1fr 1fr; grid-gutter: 1; }
    #analytics-grid { height: 1fr; grid-size: 2 2; grid-columns: 1fr 1fr; grid-rows: 1fr 1fr; grid-gutter: 1 2; margin-top: 1; }
    .chart { height: 1fr; background: $paper; border: round $line; padding: 1; color: $leaf; }

    /* System: services, browser, configuration and logs. */
    #system-grid { height: 1fr; grid-size: 2 2; grid-columns: 1fr 1fr; grid-rows: 1fr 1fr; grid-gutter: 1 2; }
    .system-panel { height: 1fr; background: $paper; border: round $line; padding: 1; }
    .healthy { color: $leaf; }
    .warning { color: $orange; }
    .log { color: $muted; }
    """

    VIEWS = ("overview", "jobs", "work", "history", "analytics", "system")

    def __init__(self, initial: str = "overview") -> None:
        super().__init__()
        self.initial = initial if initial in self.VIEWS else "overview"

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static(
                "GENGOWATCHER\n[dim]translation operations[/dim]",
                id="brand",
            )
            yield Static(
                "● all monitors operational\nlast event 4s ago · next check 00:18",
                id="header-health",
            )
        with Horizontal(id="body"):
            with Vertical(id="nav"):
                yield Static("WORKSPACES", id="nav-title")
                for index, (view, label) in enumerate(
                    (
                        ("overview", "Overview"),
                        ("jobs", "Available Jobs"),
                        ("work", "Active Work"),
                        ("history", "History"),
                        ("analytics", "Analytics"),
                        ("system", "System"),
                    ),
                    1,
                ):
                    yield Button(f"{index}  {label}", id=f"nav-{view}", flat=True)
                yield Static(id="nav-spacer")
                yield Static(
                    "SESSION\n[b]14[/b] detected\n[b]3[/b] accepted\n[b]$71.45[/b] value",
                    id="nav-summary",
                )
            with ContentSwitcher(initial=self.initial, id="switcher"):
                yield from self._overview()
                yield from self._jobs()
                yield from self._work()
                yield from self._history()
                yield from self._analytics()
                yield from self._system()
        yield Static(
            "c check now   p pause   / command   ↑↓ select   enter open",
            id="statusbar",
        )
        yield Footer()

    def _overview(self) -> ComposeResult:
        with Container(id="overview", classes="workspace"):
            yield Static("OVERVIEW", classes="workspace-title")
            with Horizontal(id="alert-strip"):
                with Vertical(id="alert-copy"):
                    yield Static("NEW JOB AVAILABLE", id="alert-label")
                    yield Static("$18.40  ·  Japanese → English", id="alert-main")
                    yield Static(
                        "Order 481516  ·  WebSocket  ·  04:03 remaining",
                        id="alert-meta",
                    )
                with Horizontal(id="alert-actions"):
                    yield Button("OPEN", id="open-alert")
                    yield Button("DISMISS", classes="secondary")
            with Grid(id="overview-grid"):
                with Vertical(id="overview-jobs", classes="panel"):
                    yield Static("AVAILABLE JOBS · 4", classes="panel-title")
                    yield Static(
                        "$18.40  JA → EN   04:03   WebSocket", classes="job-line"
                    )
                    yield Static(
                        "$31.00  EN → JA   01:30   Website", classes="job-line"
                    )
                    yield Static("$12.75  DE → EN   08:32   Email", classes="job-line")
                    yield Static("$8.20   FR → EN   accepted RSS", classes="job-line")
                with Vertical(id="overview-work", classes="panel"):
                    yield Static("ACTIVE WORK · 3", classes="panel-title")
                    yield Static("READY TO START    1", classes="work-stage")
                    yield Static("IN PROGRESS       1", classes="work-stage")
                    yield Static("REVIEW REQUIRED   1", classes="work-stage")
                with Vertical(id="overview-metrics", classes="panel"):
                    yield Static("SESSION ANALYTICS", classes="panel-title")
                    yield Static(
                        "VALUE   [b]$71.45[/b]     ACCEPT RATE   [b]21.4%[/b]\n"
                        "PACE    [b]8.4/h[/b]      AVG VALUE     [b]$17.86[/b]\n\n"
                        "08 ▂  10 ▅  12 ▇  14 ▃  16 ▆  18 ▂",
                        id="overview-chart",
                    )
                with Vertical(id="overview-system", classes="panel"):
                    yield Static("SYSTEM & ACTIVITY", classes="panel-title")
                    yield Static(
                        "[green]●[/green] WebSocket  Live       [green]●[/green] Browser  Synced\n"
                        "[green]●[/green] RSS        Watching   [green]●[/green] Email    Connected\n\n"
                        "22:41:08  job.visible     481516\n"
                        "22:40:52  browser.synced\n"
                        "22:40:31  rss.checked     0 new",
                        id="overview-log",
                    )

    def _jobs(self) -> ComposeResult:
        with Container(id="jobs", classes="workspace"):
            yield Static("AVAILABLE JOBS", classes="workspace-title")
            with Horizontal(id="jobs-layout"):
                with Vertical(id="jobs-list"):
                    yield DataTable(id="jobs-table")
                with Vertical(id="jobs-inspector", classes="panel"):
                    yield Static("SELECTED JOB", classes="panel-title")
                    yield Static(
                        "[b]$18.40[/b]\nJapanese → English\n\n"
                        "Order       481516\n"
                        "Source      WebSocket\n"
                        "Status      Available\n"
                        "Time left   04:03\n"
                        "Units       263 words\n\n"
                        "Product localization · Standard",
                        id="job-detail",
                    )
                    with Horizontal(id="job-buttons"):
                        yield Button("OPEN")
                        yield Button("IGNORE", classes="reject")

    def _work(self) -> ComposeResult:
        with Container(id="work", classes="workspace"):
            yield Static("ACTIVE WORK", classes="workspace-title")
            with Grid(id="work-board"):
                with Vertical(classes="work-column"):
                    yield Static("READY TO START · 1", classes="work-column-title")
                    yield Static(
                        "[b]Order 481518[/b]\nFR → EN · $8.20\n"
                        "Source file ready\nDeadline 50:10",
                        classes="work-card",
                    )
                with Vertical(classes="work-column"):
                    yield Static("IN PROGRESS · 1", classes="work-column-title")
                    yield Static(
                        "[b]Order 481501[/b]\nJA → EN · $42.00\n"
                        "18 / 32 segments\nDeadline 27:44",
                        classes="work-card urgent",
                    )
                with Vertical(classes="work-column"):
                    yield Static("REVIEW REQUIRED · 1", classes="work-column-title")
                    yield Static(
                        "[b]Order 481477[/b]\nDE → EN · $16.80\n"
                        "QA checks complete\n2 issues to review",
                        classes="work-card",
                    )

    def _history(self) -> ComposeResult:
        with Container(id="history", classes="workspace"):
            yield Static("HISTORY", classes="workspace-title")
            with Horizontal(id="history-toolbar"):
                yield Static(
                    "FILTER  all sources  ·  all languages  ·  last 30 days",
                    id="history-filter",
                )
                yield Static(
                    "1,284 jobs  ·  $9,412.60 total",
                    id="history-summary",
                )
            yield DataTable(id="history-table")

    def _analytics(self) -> ComposeResult:
        with Container(id="analytics", classes="workspace"):
            yield Static("ANALYTICS", classes="workspace-title")
            with Grid(id="metric-row"):
                yield Static("[b]1,284[/b]\n[dim]JOBS DETECTED[/dim]", classes="metric")
                yield Static("[b]22.7%[/b]\n[dim]ACCEPT RATE[/dim]", classes="metric")
                yield Static("[b]$17.86[/b]\n[dim]AVG VALUE[/dim]", classes="metric")
                yield Static("[b]84ms[/b]\n[dim]EVENT LATENCY[/dim]", classes="metric")
            with Grid(id="analytics-grid"):
                yield Static(
                    "[b]JOBS BY HOUR[/b]\n\n"
                    "08  ███  12\n10  ██████  26\n12  █████████  41\n"
                    "14  █████  22\n16  ███████  33\n18  ████  18",
                    classes="chart",
                )
                yield Static(
                    "[b]SOURCE PERFORMANCE[/b]\n\n"
                    "WebSocket  ████████████  52%\nEmail      ██████        24%\n"
                    "RSS        ████          16%\nWebsite    ██             8%",
                    classes="chart",
                )
                yield Static(
                    "[b]VALUE TREND · 7 DAYS[/b]\n\n"
                    "$240 ┤             ╭╮\n$180 ┤      ╭╮    ╭╯╰╮\n"
                    "$120 ┤╭─────╯╰────╯  ╰─\n $60 ┼╯",
                    classes="chart",
                )
                yield Static(
                    "[b]LANGUAGE PAIRS[/b]\n\n"
                    "JA → EN   486   $4,840\nDE → EN   241   $1,920\n"
                    "FR → EN   198   $1,486\nEN → JA   142   $1,166",
                    classes="chart",
                )

    def _system(self) -> ComposeResult:
        with Container(id="system", classes="workspace"):
            yield Static("SYSTEM", classes="workspace-title")
            with Grid(id="system-grid"):
                yield Static(
                    "[b]MONITORS[/b]\n\n"
                    "[green]●[/green] WebSocket   Live       84ms\n"
                    "[green]●[/green] RSS         Watching   18s\n"
                    "[green]●[/green] Email       Connected  31s\n"
                    "[green]●[/green] Website     Active     44s",
                    classes="system-panel",
                )
                yield Static(
                    "[b]BROWSER WORKER[/b]\n\n"
                    "State          Connected\nProfile        default\n"
                    "Open tabs      3\nLast sync      4s ago\n"
                    "Session age    01:42:18",
                    classes="system-panel",
                )
                yield Static(
                    "[b]RUNTIME CONFIGURATION[/b]\n\n"
                    "Check interval       30s\nMinimum reward      $8.00\n"
                    "Auto accept          Off\nNotifications        On\n"
                    "Web API              127.0.0.1:8000",
                    classes="system-panel",
                )
                yield Static(
                    "[b]RECENT LOGS[/b]\n\n"
                    "22:41:08 INFO  Job 481516 detected\n"
                    "22:40:52 INFO  Browser session synchronized\n"
                    "22:40:31 DEBUG RSS check complete\n"
                    "22:39:58 INFO  WebSocket authenticated\n"
                    "22:39:42 WARN  Email check took 1.8s",
                    classes="system-panel log",
                )

    def on_mount(self) -> None:
        self._setup_table("#jobs-table", JOBS[:4])
        self._setup_table("#history-table", JOBS)
        self.show_view(self.initial)

    def _setup_table(self, selector: str, rows: list[tuple]) -> None:
        table = self.query_one(selector, DataTable)
        table.add_columns("ORDER", "LANGUAGE", "VALUE", "SOURCE", "STATUS", "TIME")
        for row in rows:
            table.add_row(*row)
        table.cursor_type = "row"
        table.zebra_stripes = True

    @on(Button.Pressed)
    def handle_nav(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("nav-"):
            self.show_view(button_id.removeprefix("nav-"))

    def action_show(self, view: str) -> None:
        self.show_view(view)

    def show_view(self, view: str) -> None:
        if view not in self.VIEWS:
            return
        self.query_one("#switcher", ContentSwitcher).current = view
        for name in self.VIEWS:
            self.query_one(f"#nav-{name}", Button).set_class(name == view, "selected")


async def render_views(output_dir: Path) -> None:
    os.environ.pop("NO_COLOR", None)
    output_dir.mkdir(parents=True, exist_ok=True)
    for view in GardenApp.VIEWS:
        app = GardenApp(initial=view)
        async with app.run_test(size=(150, 44)) as pilot:
            await pilot.pause(0.2)
            app.save_screenshot(
                path=str(output_dir),
                filename=f"garden-textual-{view}.svg",
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=GardenApp.VIEWS, default="overview")
    parser.add_argument("--render", type=Path)
    args = parser.parse_args()
    if args.render:
        asyncio.run(render_views(args.render))
    else:
        GardenApp(initial=args.view).run()


if __name__ == "__main__":
    main()
