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
pip install -r requirements.txt
```

## Quick Start

```bash
make run
```

Or directly:

```bash
PYTHONPATH=src python -m gengowatcher.main
```

On first run, you'll be guided through configuration setup.

## Configuration
Settings are stored in `config.ini`. Environment variables override sensitive values in `config.ini`:

| Environment Variable | Config Section | Description |
|---------------------|----------------|-------------|
| `GENGO_USER_ID` | WebSocket | Your Gengo user ID |
| `GENGO_USER_SESSION` | WebSocket | Your session token (from cookies) |
| `GENGO_USER_KEY` | WebSocket | Your user key (from local storage) |
| `GENGOWATCHER_API_TOKEN` | WebServer | API token for the web interface |
| `GMAIL_CLIENT_ID` | EmailMonitor | Gmail OAuth client ID |
| `GMAIL_CLIENT_SECRET` | EmailMonitor | Gmail OAuth client secret |
| `GMAIL_REFRESH_TOKEN` | EmailMonitor | Gmail OAuth refresh token |

Key sections:
```ini
[Watcher]
feed_url = https://your-rss-feed-url
check_interval = 31
min_reward = 0.0

[WebSocket]
enable_websocket = true
user_id = 12345
user_session = YOUR_SESSION_TOKEN
user_key = YOUR_USER_KEY
```

Get WebSocket credentials from your browser's DevTools:
- **user_id** / **user_session**: Application → Cookies → gengo.com
- **user_key**: Application → Local Storage → gengo.com → userKey

## Commands

| Command | Description |
|---------|-------------|
| `check` | Trigger immediate RSS check |
| `pause` / `resume` | Pause/resume monitoring |
| `wstest` | Test WebSocket connection |
| `notifytest` | Test notifications |
| `togglesound` | Toggle sound alerts |
| `autoaccept` | Toggle auto job acceptance |
| `help` | Show all commands |
| `exit` | Save state and quit |

## License

MIT
