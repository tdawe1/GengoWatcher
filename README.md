# GengoWatcher v1.1.0

GengoWatcher is a lightweight Windows application that monitors RSS feeds and delivers desktop notifications. It integrates with the Vivaldi browser and supports sound alerts and logging.

## Features

* Monitor RSS feeds
* Desktop notifications for new feed items
* Sound alerts for notifications
* Integration with Vivaldi browser for opening links
* Logging of feed checks and notifications
* Interactive console commands for control

## Installation

1.  Download `gengowatcher.exe` and place it in a folder of your choice.
2.  Ensure `config.ini` is in the same directory as `gengowatcher.exe`. If it's not present, a default one will be created on the first run.
3.  Run `gengowatcher.exe` by double-clicking or via the command line.

## Usage

### Starting the application

Double-click `gengowatcher.exe` to start monitoring your RSS feeds automatically.

### Interactive Console Commands

Once the application is running, you can interact with it by typing commands in the console window:

* **`help`**: Display a list of available commands and their descriptions.
* **`check`**: Immediately trigger an RSS feed check, regardless of the configured interval.
* **`status`**: Show the current watcher status, including last check time, total new entries found, and configuration details.
* **`notifytest`**: Send a test desktop notification to verify functionality.
* **`exit` / `quit`**: Gracefully stop the watcher and exit the application.

## Configuration

The application uses `config.ini` for its settings. If `config.ini` is not found, a default one will be created.

Modify `config.ini` to adjust settings like the RSS `feed_url`, `check_interval`, notification preferences, and file paths.

**Example configuration (`config.ini`):**

```ini
[Watcher]
# RSS feed URL to monitor
feed_url = https://www.theguardian.com/uk/rss

# Interval in seconds between RSS feed checks
check_interval = 31

# Enable or disable desktop notifications (True/False)
enable_notifications = True

# Whether to use a custom User-Agent header for HTTP requests
use_custom_user_agent = False


[Paths]
# Full path to the WAV sound file to play on new entries
sound_file = C:\path\to\your\sound.wav

# Full path to Vivaldi browser executable
vivaldi_path = C:\path\to\your\vivaldi.exe

# Log file path (relative or absolute)
log_file = rss_check_log.txt

# Optional icon path for notifications (leave blank for default)
notification_icon_path =


[Logging]
# Maximum size in bytes for a single log file before rotation
log_max_bytes = 1000000

# Number of backup log files to keep
log_backup_count = 3


[Network]
# Maximum backoff time (seconds) for retrying failed RSS fetches
max_backoff = 300

# Email to use in User-Agent when use_custom_user_agent is True
user_agent_email = your_email@example.com


[State]
# Last seen RSS entry link (do not edit manually unless you want to reset)
last_seen_link =

# Total number of new entries found since starting (do not edit manually)
total_new_entries_found = 0
```

## Notifications

* New items in your feeds trigger desktop notifications.
* Notifications will attempt to open the item link in the Vivaldi browser when clicked (if Vivaldi path is configured).
* Sound alerts accompany notifications if enabled.

## Logs

The app logs feed checks and notification events to a log file (default: `rss_check_log.txt` as specified in `config.ini`).

## Updating

Download the latest version `gengowatcher.exe` and replace the old executable.
Your `config.ini` and log files will remain intact.