"""Standalone visual prototypes for choosing a future GengoWatcher TUI direction.

These apps intentionally contain sample data and no production integration.
Run one with:

    PYTHONPATH=src python prototypes/tui_design_gallery.py beacon

Render all concepts to SVG with:

    PYTHONPATH=src python prototypes/tui_design_gallery.py --render assets/tui-concepts
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Grid, Horizontal, Vertical
from textual.widgets import Button, DataTable, Footer, Static

JOBS = [
    ("481516", "JA → EN", 18.40, "WebSocket", "AVAILABLE", "04:03"),
    ("481517", "DE → EN", 12.75, "Email", "DETAILS", "08:32"),
    ("481518", "FR → EN", 8.20, "RSS", "ACCEPTED", "50:10"),
    ("481519", "EN → JA", 31.00, "Website", "AVAILABLE", "01:30"),
]


class PrototypeApp(App[None]):
    BINDINGS = [("q", "quit", "Quit")]


class Beacon(PrototypeApp):
    """One signal, enormous hierarchy, almost no interface."""

    TITLE = "Concept 01 · Beacon · Textual"
    CSS = """
    Screen { background: #050606; color: #f4efe5; }
    #top { height: 3; padding: 1 2 0 2; border-bottom: solid #25211d; }
    #mark { width: 1fr; color: #ff9d2e; text-style: bold; }
    #live { width: 20; text-align: center; color: #83e6a7; text-style: bold; }
    #keys { width: 34; text-align: right; color: #635d55; }
    #stage { height: 1fr; content-align: center middle; padding: 2 8; }
    #kicker { height: 2; text-align: center; color: #ff9d2e; text-style: bold; }
    #value { height: 8; content-align: center middle; text-align: center; color: #fff8ed; text-style: bold; }
    #language { height: 3; text-align: center; text-style: bold; }
    #meta { height: 2; text-align: center; color: #ffb85e; }
    #identity { height: 2; text-align: center; color: #635d55; }
    #counters { height: 5; width: 76; align-horizontal: center; border-top: solid #25211d; border-bottom: solid #25211d; }
    .counter { width: 1fr; text-align: center; content-align: center middle; }
    #ticker { height: 3; padding: 1 2; text-align: center; color: #8a8177; }
    #actions { height: 3; padding: 0 2; background: #0c0d0d; border-top: solid #25211d; }
    #actions Button { width: 1fr; height: 3; border: none; background: transparent; color: #ff9d2e; text-style: bold; }
    #actions Button:hover { background: #ff9d2e; color: #050606; }
    Footer { height: 1; background: #050606; color: #635d55; }
    FooterKey > .footer-key--key { color: #ff9d2e; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield Static("GW / BEACON", id="mark")
            yield Static("● LIVE", id="live")
            yield Static("C  CHECK     P  PAUSE     Q  QUIT", id="keys")
        with Container(id="stage"):
            yield Static("NEXT VIABLE JOB", id="kicker")
            yield Static("$18.40", id="value")
            yield Static("JAPANESE → ENGLISH", id="language")
            yield Static("AVAILABLE    04:03    VIA WEBSOCKET", id="meta")
            yield Static("#481516  Product localization · Standard", id="identity")
        with Horizontal(id="counters"):
            yield Static("[b]14[/b]\n[dim]FOUND[/dim]", classes="counter")
            yield Static("[b]3[/b]\n[dim]TAKEN[/dim]", classes="counter")
            yield Static("[b]8.4/H[/b]\n[dim]PACE[/dim]", classes="counter")
            yield Static("[b]1H 40M[/b]\n[dim]UPTIME[/dim]", classes="counter")
        yield Static("22:41:08   JOB.VISIBLE   #481516", id="ticker")
        with Horizontal(id="actions"):
            yield Button("CHECK NOW", flat=True)
            yield Button("PAUSE", flat=True)
            yield Button("NOTIFY TEST", flat=True)
        yield Footer()


class Ledger(PrototypeApp):
    """A newspaper-like comparison surface with a deliberate light theme."""

    TITLE = "Concept 02 · Ledger · Textual"
    CSS = """
    Screen { background: #eee8dc; color: #11253d; }
    #masthead { height: 5; padding: 1 3 0 3; border-bottom: double #11253d; }
    #titleblock { width: 1fr; }
    #title { height: 2; color: #11253d; text-style: bold; }
    #deck { height: 1; color: #b24b32; text-style: bold; }
    #issue { width: 25; text-align: right; color: #675f54; }
    #rules { height: 3; padding: 1 3 0 3; background: #d9d1c2; }
    #session { width: 1fr; text-style: bold; }
    #velocity { width: 34; text-align: right; color: #b24b32; }
    #workspace { height: 1fr; padding: 1 3; }
    #listcol { width: 1fr; margin-right: 2; }
    #inspect { width: 30; padding-left: 2; border-left: solid #aa9f8d; }
    .heading { height: 2; color: #b24b32; text-style: bold; border-bottom: solid #aa9f8d; }
    #table { height: 1fr; background: #eee8dc; color: #11253d; border: none; }
    #table > .datatable--header { background: #11253d; color: #f5efe4; text-style: bold; }
    #table > .datatable--cursor { background: #d1b99d; color: #11253d; }
    #pick { height: 12; padding: 1 0; }
    #wire { height: 1fr; padding-top: 1; }
    #commands { height: 4; padding: 0 3; background: #11253d; }
    #commands Button { width: 1fr; height: 3; border: none; background: #11253d; color: #f5efe4; }
    #commands Button:hover { background: #b24b32; }
    Footer { height: 1; background: #eee8dc; color: #675f54; }
    FooterKey > .footer-key--key { color: #b24b32; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="masthead"):
            with Vertical(id="titleblock"):
                yield Static("THE GENGO LEDGER", id="title")
                yield Static("INDEPENDENT JOB INTELLIGENCE", id="deck")
            yield Static("MARKET LIVE\nISSUE 02 · EVENING", id="issue")
        with Horizontal(id="rules"):
            yield Static("SESSION  14 SEEN  /  3 TAKEN  /  $71.45 VALUE", id="session")
            yield Static("VELOCITY  8.4 JOBS PER HOUR", id="velocity")
        with Horizontal(id="workspace"):
            with Vertical(id="listcol"):
                yield Static("OPEN OPPORTUNITIES", classes="heading")
                yield DataTable(id="table")
            with Vertical(id="inspect"):
                yield Static("EDITOR'S PICK", classes="heading")
                yield Static(id="pick")
                yield Static("CHANNEL WIRE", classes="heading")
                yield Static(id="wire")
        with Horizontal(id="commands"):
            yield Button("CHECK NOW")
            yield Button("PAUSE")
            yield Button("RESUME")
            yield Button("OPEN SELECTED")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.add_columns("ORDER", "LANGUAGE", "VALUE", "CHANNEL", "STATUS", "DEADLINE")
        for row in JOBS:
            table.add_row(row[0], row[1], f"${row[2]:.2f}", *row[3:])
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.focus()
        pick = Text()
        pick.append("$31.00\n", style="#11253d bold")
        pick.append("ENGLISH → JAPANESE\n", style="#b24b32 bold")
        pick.append("AVAILABLE · 01:30\n", style="#11253d")
        pick.append("Filed via Website\nOrder 481519", style="#675f54")
        self.query_one("#pick", Static).update(pick)
        self.query_one("#wire", Static).update(
            "[b]WebSocket[/b]   Live\n[b]Browser[/b]     Visible\n"
            "[b]RSS[/b]         Watching\n[b]Email[/b]       Connected"
        )


class Scope(PrototypeApp):
    """A diagnostic instrument, organized around signals rather than cards."""

    TITLE = "Concept 03 · Scope · Recommended: Ratatui"
    CSS = """
    Screen { background: #02090c; color: #7ce7e1; }
    #scopehead { height: 3; padding: 1 2 0 2; background: #041318; border-bottom: solid #12545b; }
    #scopemark { width: 1fr; text-style: bold; color: #b5fff7; }
    #clock { width: 26; text-align: right; color: #30aeb4; }
    #scopebody { height: 1fr; padding: 1 2; }
    #lanes { width: 26; margin-right: 2; border-right: solid #12545b; }
    #tracecol { width: 1fr; }
    .label { height: 2; color: #30aeb4; text-style: bold; }
    #sources { height: 13; padding: 1; background: #031014; }
    #health { height: 1fr; padding: 1; color: #5a9ca0; }
    #trace { height: 11; padding: 1 2; background: #031014; color: #5ff4e7; }
    #contacts { height: 1fr; layout: grid; grid-size: 2 2; grid-gutter: 1; }
    .contact { height: 1fr; padding: 1 2; border: tall #12545b; background: #020c10; }
    .hot { border: tall #f6c85f; color: #f6c85f; }
    #scopeline { height: 3; padding: 1 2; border-top: solid #12545b; color: #30aeb4; }
    Footer { height: 1; background: #02090c; color: #286a70; }
    FooterKey > .footer-key--key { color: #7ce7e1; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="scopehead"):
            yield Static("◉ GENGO SCOPE / MULTI-CHANNEL ACQUISITION", id="scopemark")
            yield Static("22:41:08  Δ  84ms", id="clock")
        with Horizontal(id="scopebody"):
            with Vertical(id="lanes"):
                yield Static("INPUT LANES", classes="label")
                yield Static(
                    "WS       ████████████ 14\n"
                    "EMAIL    ███░░░░░░░░░  3\n"
                    "RSS      █████░░░░░░░  5\n"
                    "WEBSITE  ██░░░░░░░░░░  2",
                    id="sources",
                )
                yield Static("SYSTEM HEALTH", classes="label")
                yield Static(
                    "● SOCKET   LOCKED\n● BROWSER  SYNCED\n"
                    "● WATCHER  ACTIVE\n○ CAPTCHA  STANDBY",
                    id="health",
                )
            with Vertical(id="tracecol"):
                yield Static("EVENT TRACE / LAST 90 SECONDS", classes="label")
                yield Static(
                    "  18 ┤          ╭╮                         ╭──╮\n"
                    "  12 ┤    ╭╮   ╭╯╰╮          ╭╮         ╭╯  ╰╮\n"
                    "   6 ┤╭───╯╰───╯  ╰──────╮  ╭╯╰─────────╯    ╰─\n"
                    "   0 ┼╯                  ╰──╯\n"
                    "     └─90s─────────60s─────────30s──────────NOW",
                    id="trace",
                )
                yield Static("LIVE CONTACTS", classes="label")
                with Grid(id="contacts"):
                    yield Static(
                        "01  $18.40\nJA → EN\nT−04:03  WS", classes="contact hot"
                    )
                    yield Static(
                        "02  $12.75\nDE → EN\nT−08:32  EMAIL", classes="contact"
                    )
                    yield Static("03  $8.20\nFR → EN\nACCEPTED  RSS", classes="contact")
                    yield Static(
                        "04  $31.00\nEN → JA\nT−01:30  WEB", classes="contact hot"
                    )
        yield Static(
            "[C] PULSE NOW   [F] FREEZE TRACE   [ENTER] INSPECT CONTACT", id="scopeline"
        )
        yield Footer()


class Garden(PrototypeApp):
    """A calm spatial metaphor: opportunities grow through a pipeline."""

    TITLE = "Concept 04 · Garden · Recommended: Bubble Tea"
    CSS = """
    Screen { background: #e8efe3; color: #264435; }
    #gardenhead { height: 5; padding: 1 3; background: #d9e7d2; }
    #gardenbrand { width: 1fr; color: #264435; text-style: bold; }
    #weather { width: 36; text-align: right; color: #6d846a; }
    #gardenbody { height: 1fr; padding: 1 3; }
    #today { width: 24; margin-right: 2; padding: 1; background: #f5f7ef; border: round #a9bda2; }
    #beds { width: 1fr; }
    .gardenlabel { height: 2; color: #6b805b; text-style: bold; }
    #hero { height: 10; padding: 1 2; background: #f5f7ef; border: round #d1945d; color: #264435; }
    #rhythm { height: 1fr; padding: 1; color: #6d846a; }
    #pipeline { height: 1fr; grid-size: 3 1; grid-columns: 1fr 1fr 1fr; grid-gutter: 1; }
    .bed { height: 1fr; padding: 1; background: #f5f7ef; border: round #a9bda2; }
    .bedtitle { color: #6b805b; text-style: bold; }
    .seed { margin-top: 1; padding: 1; background: #e2eadb; color: #264435; }
    .ripe { background: #f2dfc7; color: #7a4a2c; }
    #gardenfooter { height: 4; padding: 1 3; background: #d9e7d2; color: #526b55; }
    Footer { height: 1; background: #e8efe3; color: #6d846a; }
    FooterKey > .footer-key--key { color: #507c5a; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="gardenhead"):
            yield Static(
                "GENGO GARDEN\n[dim]opportunities, tended quietly[/dim]",
                id="gardenbrand",
            )
            yield Static("● all channels healthy\nnext watering in 00:18", id="weather")
        with Horizontal(id="gardenbody"):
            with Vertical(id="today"):
                yield Static("TODAY'S HARVEST", classes="gardenlabel")
                yield Static(
                    "[b]3[/b] jobs accepted\n[b]$71.45[/b] gathered", id="hero"
                )
                yield Static("RHYTHM", classes="gardenlabel")
                yield Static(
                    "08  ▂\n10  ▅\n12  ▇\n14  ▃\n16  ▆\n18  ▂\n\n"
                    "Best: JA → EN\nAverage: $17.86",
                    id="rhythm",
                )
            with Vertical(id="beds"):
                yield Static("THE WORKFLOW", classes="gardenlabel")
                with Grid(id="pipeline"):
                    with Vertical(classes="bed"):
                        yield Static("① NEW SEEDS · 2", classes="bedtitle")
                        yield Static(
                            "$18.40  JA → EN\n04:03 · WebSocket", classes="seed ripe"
                        )
                        yield Static("$12.75  DE → EN\n08:32 · Email", classes="seed")
                    with Vertical(classes="bed"):
                        yield Static("② TAKING ROOT · 1", classes="bedtitle")
                        yield Static("$8.20  FR → EN\nAccepted · RSS", classes="seed")
                    with Vertical(classes="bed"):
                        yield Static("③ READY TO PICK · 1", classes="bedtitle")
                        yield Static(
                            "$31.00  EN → JA\n01:30 · Website", classes="seed ripe"
                        )
        yield Static(
            "[space] water now     [enter] tend selected     [p] rest watcher",
            id="gardenfooter",
        )
        yield Footer()


class Arcade(PrototypeApp):
    """A fast, saturated reward board with score and urgency."""

    TITLE = "Concept 05 · Arcade · Recommended: Bubble Tea"
    CSS = """
    Screen { background: #08051a; color: #f7f4ff; }
    #arcadehead { height: 5; padding: 1 2; background: #120a32; border-bottom: heavy #ff3ea5; }
    #arcademark { width: 1fr; color: #49eaff; text-style: bold; }
    #score { width: 35; text-align: right; color: #ffe45e; text-style: bold; }
    #mission { height: 4; padding: 1 2; color: #ff3ea5; text-style: bold; }
    #board { height: 1fr; padding: 0 2 1 2; grid-size: 2 2; grid-columns: 1fr 1fr; grid-rows: 1fr 1fr; grid-gutter: 1 2; }
    .quest { height: 1fr; padding: 1 2; border: heavy #5b3fc4; background: #100b2a; }
    .quest:hover { border: heavy #49eaff; background: #18103d; }
    .boss { border: heavy #ff3ea5; }
    .questno { color: #9181d9; }
    .reward { color: #ffe45e; text-style: bold; }
    .timer { color: #49eaff; }
    #combo { height: 4; padding: 1 2; background: #120a32; border-top: solid #5b3fc4; }
    #comboinfo { width: 1fr; color: #9181d9; }
    #arcadebuttons { width: 45; height: 3; background: #ff3ea5; color: #08051a; text-align: center; content-align: center middle; }
    #arcadebuttons Button { width: 1fr; height: 3; border: none; background: #ff3ea5; color: #08051a; text-style: bold; }
    #arcadebuttons Button:hover { background: #49eaff; }
    Footer { height: 1; background: #08051a; color: #5b4e91; }
    FooterKey > .footer-key--key { color: #49eaff; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="arcadehead"):
            yield Static(
                "GENGO//QUEST\n[dim]TRANSLATION ARCADE NETWORK[/dim]", id="arcademark"
            )
            yield Static("SCORE  007145\nCOMBO  ×3", id="score")
        yield Static("SELECT NEXT MISSION  //  4 SIGNALS IN RANGE", id="mission")
        with Grid(id="board"):
            yield self._quest(
                "01", "$18.40", "JA → EN", "WEBSOCKET", "04:03", boss=True
            )
            yield self._quest("02", "$12.75", "DE → EN", "EMAIL", "08:32")
            yield self._quest("03", "$8.20", "FR → EN", "RSS · ACCEPTED", "50:10")
            yield self._quest("04", "$31.00", "EN → JA", "WEBSITE", "01:30", boss=True)
        with Horizontal(id="combo"):
            yield Static(
                "STREAK BONUS +18%  ·  SESSION RANK A  ·  LATENCY 84ms", id="comboinfo"
            )
            yield Static("[b]ACCEPT[/b]    SCAN    PAUSE", id="arcadebuttons")
        yield Footer()

    @staticmethod
    def _quest(
        number: str,
        reward: str,
        language: str,
        source: str,
        timer: str,
        *,
        boss: bool = False,
    ) -> Static:
        text = (
            f"[dim]MISSION {number}[/dim]\n\n"
            f"[b]{reward}[/b]  //  {language}\n\n"
            f"{source}\n"
            f"T−{timer}"
        )
        return Static(text, classes="quest boss" if boss else "quest")


APPS = {
    "beacon": Beacon,
    "ledger": Ledger,
    "scope": Scope,
    "garden": Garden,
    "arcade": Arcade,
}


async def render_gallery(output_dir: Path) -> None:
    os.environ.pop("NO_COLOR", None)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, app_class in APPS.items():
        app = app_class()
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.pause(0.2)
            app.save_screenshot(path=str(output_dir), filename=f"{name}.svg")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", nargs="?", choices=APPS, default="beacon")
    parser.add_argument("--render", type=Path)
    args = parser.parse_args()
    if args.render:
        asyncio.run(render_gallery(args.render))
    else:
        APPS[args.design]().run()


if __name__ == "__main__":
    main()
