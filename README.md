# GengoWatcher
A terminal-based monitor for Gengo translation jobs with real-time notifications.
## Features
- **Real-time monitoring** via WebSocket and RSS feed
- **Desktop notifications** with sound alerts
- **Auto-accept jobs** matching your criteria
- **Multiple sources** - WebSocket, RSS, email, and website scraping
- **CAPTCHA solving** integration (2Captcha, Anti-Captcha)
- **Modern TUI** built with Textual
## Installation
```bash
git clone https://github.com/tdawe1/GengoWatcher.git
cd GengoWatcher
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e .
```

That installs `gengowatcher` on your PATH, plus the release-friendly aliases
`gengo-watcher` and `gengowatcher-browser-worker`.

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

Interactive setup entrypoints:
```bash
gengowatcher --configure
gengowatcher --setup-email
gengowatcher --setup-website
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

The browser worker is an optional local Playwright sidecar that keeps a long-lived headed browser with a dedicated persistent profile. Configure the `BrowserWorker` section in `config.toml`, then start it separately with:

```bash
gengowatcher-browser-worker \
  --profile-path profiles/browser-worker \
  --socket-path /tmp/gengowatcher-browser-worker.sock
```

The module form still works if you need it:

```bash
PYTHONPATH=src python -m gengowatcher.browser_worker.main \
  --profile-path profiles/browser-worker \
  --socket-path /tmp/gengowatcher-browser-worker.sock
```

On Windows PowerShell, use a temp socket path instead of the Unix `/tmp/...` example:

```powershell
$socket = Join-Path $env:TEMP "gengowatcher-browser-worker.sock"
PYTHONPATH=src python -m gengowatcher.browser_worker.main `
  --profile-path profiles/browser-worker `
  --socket-path $socket
```

The operator procedure for black-box validation is documented in `docs/browser-worker-black-box-test-procedure.md`.

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

## File Transfer API

The built-in web API now includes a local file store for release artifacts, exports,
or handoff documents. It is rooted at `[Paths].file_storage_dir` and exposed as:

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

![GengoWatcher TUI Screenshot](assets/tui-screenshot.png)