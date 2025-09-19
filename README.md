# GengoWatcher v2.2.0

GengoWatcher is an intelligent terminal application designed to find and alert you to new freelance jobs the instant they become available. It monitors both your personal Gengo RSS feed and a real-time WebSocket connection, ensuring maximum notification speed.

It features an interactive text-based user interface (TUI) that runs directly in your terminal, providing real-time status updates, activity logs, and command controls.

---

## ✨ Key Features

- **Dual-Source Monitoring**: Fetches jobs from both a personal RSS feed (as a fallback) and a real-time WebSocket connection.
- **Highly Efficient**: Near-zero CPU usage when idle, ensuring it runs quietly in the background without impacting system performance.
- **Responsive Interactive TUI**: A clean, modern interface that provides at-a-glance status, feels responsive to user input, and includes command controls.
- **Interactive Diagnostics**: A `wstest` command allows you to test WebSocket connectivity and the full notification pipeline on demand.
- **Customizable Alerts**:
    - Filter jobs by a minimum reward value.
    - Toggle desktop and sound alerts on/off.
- **Auto Job Acceptance**: Automatically accept jobs that meet your criteria with configurable delays and CAPTCHA solving integration.
- **CAPTCHA Solving Integration**: Automated solving for job acceptance using 2Captcha, Anti-Captcha, or local ML-based solver.
- **Interactive Controls**: Pause, resume, restart, and trigger manual checks on the fly.
- **Robust & Resilient**: Handles connection errors with an exponential backoff strategy and runs correctly even in non-interactive terminals.
- **Persistent State**: Remembers the last job seen in `state.json`, so you only get notified about truly new entries.
- **CSV Logging**: Optionally logs every job entry to a CSV file for historical data analysis.
- **Web Interface**: Optional web-based monitoring interface with real-time job tracking.

---

![GengoWatcher TUI Screenshot](assets/tui-screenshot.png)

---

## 📋 Table of Contents

- [✨ Key Features](#-key-features)
- [🚀 Installation](#-installation)
- [⚙️ Usage](#️-usage)
  - [📝 Example `config.ini`](#-example-configini)
- [🤖 Auto Job Acceptance](#-auto-job-acceptance)
- [🔐 CAPTCHA Solver Setup](#-captcha-solver-setup)
- [⌨️ Commands](#️-commands)
- [🐛 Troubleshooting](#-troubleshooting)
- [📜 License](#-license)

---

## 🚀 Installation

GengoWatcher is a Python application requiring Python 3.8 or newer.

**1. Clone the Repository**

```bash
git clone https://github.com/tdawe1/GengoWatcher.git
cd GengoWatcher
```

**2. Set Up a Virtual Environment (Highly Recommended)**

Using a virtual environment keeps project dependencies isolated from your system's global Python installation.

```bash
# Create a virtual environment
python -m venv venv

# Activate it
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

**3. Install Dependencies**

```bash
pip install -r requirements.txt
```

---

## ⚙️ Usage

**1. Launch the Application**

From your terminal, run:

```bash
python -m gengowatcher.main
```

**Optional Command-Line Arguments:**

- `--web` - Run TUI with web server enabled (default port: 8000)
- `--web-only` - Run web server only (no TUI)
- `--web-port PORT` - Specify web server port
- `--configure` - Run interactive configuration setup
- `--set SECTION OPTION VALUE` - Set config value via CLI
- `--get SECTION OPTION` - Get config value via CLI
- `--list` - List all configuration values

**2. First-Time Setup**

The first time you run GengoWatcher, it will detect that it's a new installation and guide you through an interactive setup. It will ask for essential details needed for WebSocket and RSS monitoring.

**3. Start Monitoring**

After you complete the prompts, the application will automatically save your details to `config.ini` and begin monitoring for jobs.

---

### 📝 Example `config.ini`

The interactive setup will create a `config.ini` file for you. You can edit this file later to fine-tune your settings. It will look similar to this:

```ini
[Watcher]
feed_url = https://your-feed/rss.xml
check_interval = 31
min_reward = 0.0
enable_notifications = true
enable_sound = true
use_custom_user_agent = false

[WebSocket]
enable_websocket = true
user_id = 12345
user_session = your_long_session_token_here

[Paths]
sound_file = C:\Windows\Media\chimes.wav
log_file = logs/gengowatcher.log
notification_icon_path =
browser_path =
browser_args = --new-window {url}
all_entries_log = logs/all_entries.csv

[Logging]
log_max_bytes = 1000000
log_backup_count = 3
log_main_enabled = true
log_all_entries_enabled = true

[Network]
max_backoff = 300
user_agent_email = your_email@example.com

[AutoAccept]
enabled = false
min_reward = 0.0
max_reward = 999999.0
job_sources = rss,websocket
accept_delay_min = 5
accept_delay_max = 30
browser_profile_path =
notification_on_accept = true
log_acceptance = true

[Captcha]
service = 2captcha
max_retries = 3
retry_delay = 5
rate_limit = 60

[WebServer]
enabled = false
port = 8000
host = localhost
enable_auth = false
api_key =
```

---

## 🤖 Auto Job Acceptance

GengoWatcher can automatically accept jobs that meet your configured criteria:

### Configuration Options

- `enabled`: Enable/disable auto job acceptance (true/false)
- `min_reward`: Minimum reward amount for auto acceptance
- `max_reward`: Maximum reward amount for auto acceptance
- `job_sources`: Comma-separated list of sources (rss, websocket)
- `accept_delay_min`: Minimum delay in seconds before accepting a job
- `accept_delay_max`: Maximum delay in seconds before accepting a job
- `browser_profile_path`: Path to browser profile for job acceptance (if needed)
- `notification_on_accept`: Show notification when a job is accepted
- `log_acceptance`: Log accepted jobs to a file

### Rate Limiting & Error Handling

The auto-acceptance engine includes built-in rate limiting (30 requests/minute) to prevent exceeding API limits and implements retry mechanisms for failed acceptance attempts.

### Management Commands

- `toggleautoaccept` - Enable/disable auto-acceptance
- `acceptstats` - Display job acceptance statistics

---

## 🔐 CAPTCHA Solver Setup

GengoWatcher supports integration with CAPTCHA solving services to automate job acceptance:

### Supported Services

1. **2Captcha** - https://2captcha.com (Pay-per-solve)
2. **Anti-Captcha** - https://anti-captcha.com (Pay-per-solve)
3. **Local Solver** - ML-based solver (No API key required)

### Quick Setup

To configure CAPTCHA solving:
1. Run `python -m gengowatcher.main`
2. Type `captchasetup` in the command interface
3. Select your service and enter your API key (if required)
4. The API key is stored securely using Fernet encryption (AES-128-CBC with HMAC)

### Configuration Options

```ini
[Captcha]
service = 2captcha           # Service: 2captcha, anti-captcha, or local
max_retries = 3             # Maximum retry attempts
retry_delay = 5              # Seconds between retries
rate_limit = 60              # Requests per minute
```

### Management Commands

- `captchatest` - Verify API key and check balance
- `captchastats` - View usage statistics and costs
- `captchareset` - Clear configuration and start over

### Security Features

- API keys encrypted at rest using system-specific key derivation
- Restrictive file permissions (0o600)
- No sensitive data logged (tokens, keys, or solutions)
- HTTPS-only API communication

⚠️ **Note**: Using CAPTCHA solving services incurs costs. Monitor usage with `captchastats`.

---

## ⌨️ Commands

Type commands directly into the TUI and press `Enter` to execute them.

| Command               | Aliases      | Description                                                 |
| --------------------- | ------------ | ----------------------------------------------------------- |
| `acceptstats`         |              | Display job acceptance statistics.                          |
| `autoaccept`          |              | Toggle auto job acceptance on/off.                          |
| `captchasetup`        |              | Interactive CAPTCHA solver configuration.                   |
| `captchatest`         |              | Test CAPTCHA solving service connection and balance.        |
| `captchastats`        |              | View CAPTCHA usage statistics and costs.                    |
| `captchareset`        |              | Reset CAPTCHA configuration.                                |
| `captchatoggle`       |              | Toggle CAPTCHA solving on/off.                              |
| `check`               |              | Trigger an immediate RSS feed check.                        |
| `clear`               |              | Clear the command output panel.                             |
| `exit`                | `q`, `quit`  | Save the current state and exit the application.            |
| `help`                |              | Display the list of available commands.                     |
| `notifytest`          | `nt`         | Send a test notification to check sound and alerts.         |
| `pause`               | `p`          | Pause feed checks. A `gengowatcher.pause` file is created.  |
| `reloadconfig`        | `rl`         | Reload all settings from `config.ini`.                      |
| `restart`             |              | Restart the entire script.                                  |
| `resume`              | `r`          | Resume feed checks by deleting the pause file.              |
| `setminreward <amt>`  | `smr <amt>`  | Set a minimum reward value (e.g., `smr 5.50`).              |
| `toggleautoaccept`    | `taa`        | Toggle auto job acceptance on/off.                          |
| `togglenotifications` | `tn`         | Toggle desktop notifications on or off.                     |
| `togglesound`         | `ts`         | Toggle sound alerts on or off.                              |
| `togglewebsocket`     | `tw`         | Toggle WebSocket monitoring (requires restart).             |
| `wstest [mode]`       | `wt`         | Test the watcher. `wt` checks the WebSocket connection. `wt notify` sends a test job. |

---

## 🐛 Troubleshooting

#### Terminal Flickering or Rendering Issues

This application uses a Text-Based User Interface (TUI) which draws and redraws itself rapidly. Older terminals (like the default `cmd.exe` or `powershell.exe` on Windows) may struggle to keep up, causing flickering or graphical glitches.

**Solution**: Use a modern, hardware-accelerated terminal for the best experience.
-   **Windows**: [**Windows Terminal**](https://aka.ms/terminal) (recommended, available on the Microsoft Store)
-   **macOS**: [**iTerm2**](https://iterm2.com/)
-   **Linux/Cross-Platform**: [**Alacritty**](https://alacritty.org/), [**Kitty**](https://sw.kovidgoyal.net/kitty/)

#### WebSocket Connection Issues

If you're experiencing WebSocket connection problems:
1. Verify your user_id and user_session are correct
2. Check network connectivity
3. Use `wstest` to diagnose connection issues
4. Ensure your WebSocket headers match the expected format

#### CAPTCHA Solving Issues

If CAPTCHA solving isn't working:
1. Verify your API key with `captchatest`
2. Check your service balance
3. Ensure you haven't exceeded rate limits
4. Try resetting with `captchareset`

---

## 📜 License

This project is licensed under the MIT License. See the `LICENSE` file for details.