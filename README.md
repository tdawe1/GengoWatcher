# GengoWatcher

> **Latest release: v3.0.0** — see [CHANGELOG.md](CHANGELOG.md) for what changed.

A terminal-based monitor for Gengo translation jobs with real-time notifications,
browser-collected workbench observation, and an optional local web API for
handoff and integration.

## Features

- **Real-time monitoring** via WebSocket and RSS feed
- **Desktop notifications** with sound alerts
- **Auto-accept jobs** matching your criteria
- **Multiple sources** — WebSocket, RSS, email, native browser (Firefox RDP), and website scraping
- **Native browser workbench observation** — watches your real Firefox session via DevTools, projects order/text/time-left/segment counts into state, and fires countdown alerts at 50% / 1h / low-time
- **Webhook-backed API events** — signed inbound job discovery, signed outbound delivery with retry/backoff, JSONL audit log
- **CAPTCHA solving** integration (2Captcha, Anti-Captcha)
- **Native Ratatui TUI** with live jobs, workflow, history, analytics, health, and event views
- **Textual fallback** available with `--tui textual`
- **Local web API** with bearer auth for file transfer, status, and webhook ingest

## Installation

```bash
git clone https://github.com/tdawe1/GengoWatcher.git
cd GengoWatcher
git checkout v3.0.0  # or stay on main for the latest unreleased changes
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e .
```

That installs `gengowatcher` on your PATH, plus the release-friendly aliases
`gengo-watcher` and `gengowatcher-browser-worker`. This Python installation is
sufficient for the legacy Textual interface.

The native Ratatui client is optional. To use it, install Rust/Cargo and run:

```bash
cargo install --locked --path prototypes/garden-ratatui
```

That installs `gengowatcher-tui`. Automatic TUI selection requires this
binary (or `GENGOWATCHER_RATATUI_BIN` / a built
`prototypes/garden-ratatui/target/{release,debug}/gengowatcher-tui`).
`gengowatcher --tui ratatui` can still compile and run the client through
Cargo from a source checkout.

If you want a simpler repo-local launcher without relying on Python packaging, install the bundled script into `~/.local/bin`:

```bash
make install-user
```

That symlinks `bin/gengowatcher`,
`bin/gengo-watcher`, and
`bin/gengowatcher-browser-worker`
into `~/.local/bin/` and runs them through this repo's `venv` from any directory.

## Quick Start

```bash
gengowatcher
```

Alias:

```bash
gengo-watcher
```

Or directly:

```bash
./bin/gengowatcher
```

On the first run, you'll be guided through configuration setup.
The Ratatui interface is selected automatically when a `gengowatcher-tui`
binary is available; packaged Python-only installs fall back to Textual. The
Ratatui path starts the authenticated loopback API internally and never places
the API token in process arguments.

Interactive setup entrypoints:

```bash
gengowatcher --configure
gengowatcher --setup-email
gengowatcher --setup-website
gengowatcher --tui textual  # use the legacy Textual interface
```

Web-only mode (no TUI):

```bash
gengowatcher --web-only
gengowatcher --web   # TUI + web side-by-side
```

## Configuration

Settings are stored in `config.toml`. Key sections:

```toml
[Watcher]
feed_url = "https://your-rss-feed-url"
check_interval = 31
min_reward = 0.0

[WebSocket]
enable_websocket = true
user_id = 12345
user_session = "YOUR_SESSION_TOKEN"
user_key = "YOUR_USER_KEY"
```

Get WebSocket credentials from your browser's DevTools:

- **user_id** and **user_session**: Application → Cookies → gengo.com
- **user_key**: Application → Local Storage → gengo.com → userKey

### Browser Worker

The browser worker is an optional local Playwright sidecar that keeps a long-lived headed browser with a dedicated persistent profile. It launches with anti-automation flags (`--disable-blink-features=AutomationControlled`) and an init script that strips `navigator.webdriver`, so the browser session presents a clean fingerprint to Gengo's web tier.

Configure the `BrowserWorker` section in `config.toml`, then start it separately with:

```bash
PYTHONPATH=src python -m gengowatcher.browser_worker.main \
  --profile-path profiles/browser-worker \
  --socket-path /tmp/gengowatcher-browser-worker.sock
```

The operator procedure for black-box validation is documented in `docs/browser-worker-black-box-test-procedure.md`.

### Native Browser Listener

The native listener attaches to your real Firefox session via DevTools Protocol and observes workbench pages without injecting scripts or running a separate browser. Configure under `[NativeBrowserListener]`:

```toml
[NativeBrowserListener]
enabled = true
capture_interval_ms = 750

[Browser]
backend = "native"
debug_url = "ws://127.0.0.1:6000"
```

Observed events are projected into state by `state_projector.py` and surface in the **Jobs** tab as browser-collected rows with order ID, time-left, source text, and segment counts.

### Webhooks and API Events

Inbound and outbound webhooks live under `[Webhooks]` in `config.toml`. Inbound is HMAC-SHA256 signed with a per-request timestamp (clock-skew tolerance configurable); outbound supports multiple targets with exponential backoff retry and a JSONL audit log.

Public API event routes:

```text
POST /api/jobs/discovered      # requires bearer auth
POST /api/webhooks/jobs/discovered  # HMAC-required alias
GET  /api/events               # recent lifecycle events
GET  /api/events/audit         # webhook audit log
```

## Commands

| Command | Description |
|---------|-------------|
| `check` | Trigger immediate RSS check |
| `pause` and `resume` | Pause/resume monitoring |
| `wstest` | Test WebSocket connection |
| `notifytest` | Test notifications |
| `togglesound` | Toggle sound alerts |
| `autoaccept` | Toggle auto-acceptance |
| `help` | Show all commands |
| `exit` | Save state and quit |

### Ratatui controls

| Key | Action |
|-----|--------|
| `1`–`6`, `←` / `→` | Switch workspace |
| `↑` / `↓` | Select an available job |
| `a` | Confirm and accept the selected job |
| `i` | Ignore the selected job for this TUI session |
| `c` | Trigger an immediate watcher check |
| `p` | Pause or resume monitoring |
| `x` | Confirm cancellation of the active job |
| `q`, `Ctrl+C` | Exit |

## Web API

The built-in web API exposes status, jobs, events, file transfer, and webhook ingest. Endpoints live under `/api/...` and require a bearer token (auto-generated on first run; see `[WebServer].auth_token`).

```text
GET  /api/status
GET  /api/jobs
GET  /api/events
POST /api/jobs/{id}/accept
POST /api/jobs/cancel
POST /api/commands
GET  /api/config
PUT  /api/config/{section}/{option}
GET  /api/files
POST /api/files/upload
GET  /api/files/{stored_name}
WS   /ws/status            # real-time status stream
```

### File Transfer

The file store is rooted at `[Paths].file_storage_dir` and exposed as:

```text
GET  /api/files
POST /api/files/upload
GET  /api/files/{stored_name}
```

When `POST /api/files/upload` includes `job_id`, `tier`, `word_count`, and `value`,
stored files are renamed to:

```text
YYYYMMDD_HHMMSS_<job_id>_<pro|standard>_<word_count>w_<value>.<ext>
```

Example:

```text
20260410_163012_job-12345_pro_320w_16.00.txt
```

All three endpoints require the normal web API bearer token.

### Data Privacy and Retention

Customer source text and raw workbench payloads remain available in memory while
an active workflow needs them, but they are removed from persisted `state.json`.
Outbound webhooks also omit customer text and segments by default; set
`[Webhooks].outbound_include_customer_content = true` only for a trusted target
that explicitly requires that content.

Webhook audit entries and stored job files default to 30-day retention via
`[Webhooks].audit_retention_days` and
`[TranslationWorkflow].file_retention_days`. Set either value to `0` to disable
age-based cleanup. Size and line caps still apply to the webhook audit log.

Runtime secrets may be supplied through the environment variables documented in
`.env.example`. When secrets are stored in `config.toml`, GengoWatcher restricts
the file to user-only permissions (`0600`) on supported platforms.

## Development

```bash
# Run tests
python -m pytest

# Run a single test file
python -m pytest tests/test_state.py -q

# Type-check / syntax check
python -m py_compile src/gengowatcher/*.py tests/*.py scripts/*.py

# Format with Black (line length 88)
python -m black .

# Lint with flake8 (line length 88, E203 ignored)
python -m flake8 .

# Build a wheel + sdist
python -m build

# Build and validate the native TUI
make build-ratatui
make test-ratatui
```

The Makefile wraps the same commands using `.venv/bin/python` when available.

![GengoWatcher TUI Screenshot](assets/tui-screenshot.png)
