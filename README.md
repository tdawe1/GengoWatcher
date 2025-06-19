# GengoWatcher v1.1.0

GengoWatcher is a lightweight Windows application that monitors RSS feeds and delivers desktop notifications. It integrates with the Vivaldi browser and supports sound alerts and logging.

## Features

* Monitor multiple RSS feeds
* Desktop notifications for new feed items
* Sound alerts for notifications
* Integration with Vivaldi browser for opening links
* Logging of feed checks and notifications
* Command-line options for advanced control

## Installation

1.  Download `gengowatcher.exe` and place it in a folder of your choice.
2.  (Optional) Include your feed configuration file (e.g., `feeds.json`) if used externally.
3.  Run `gengowatcher.exe` by double-clicking or via the command line.

## Usage

### Starting the application

Double-click `gengowatcher.exe` to start monitoring your RSS feeds automatically.

### Command-line options

You can run `gengowatcher.exe` with the following options:

```lua
Usage: gengowatcher.exe [options]

Options:
  --help             Show this help message and exit
  --feeds <file>     Specify an alternate feed configuration file
  --silent           Start without showing notifications (runs in background)
  --log <file>       Specify log file location
  --version          Show version information
```

**Example:**

```css
gengowatcher.exe --feeds myfeeds.json --log logs.txt
```

## Configuration

By default, the application uses `feeds.json` (or your specified file) for RSS feed URLs.
Modify the feed URLs in your JSON config file to add or remove feeds.

**Example feed config (`feeds.json`):**

```json
[
  "https://example.com/feed1.xml",
  "https://example.com/feed2.xml"
]
```

## Notifications

* New items in your feeds trigger desktop notifications.
* Notifications open the item link in the Vivaldi browser when clicked.
* Sound alerts accompany notifications if enabled.

## Logs

The app logs feed checks and notification events to a log file (default: `gengowatcher.log`).
Use the `--log` option to specify a different log file.

## Updating

Download the latest version `gengowatcher.exe` and replace the old executable.
Your feed config and log files will remain intact.