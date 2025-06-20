# GengoWatcher

A terminal-based utility for monitoring RSS feeds. It provides desktop notifications and filters new entries based on user-defined criteria. The application is primarily designed for use with Gengo's RSS feed but can be configured for other feeds.

---

## 💾 Standalone Executable

For users who do not wish to install Python or manage dependencies, a pre-compiled executable is available.

1.  Navigate to the **[Releases](https://github.com/tdawe1/GengoWatcher/releases)** page.
2.  Download the `GengoWatcher-vX.X.X.exe` file from the most recent release.
3.  Place the executable in its own folder.
4.  Run the executable. A `config.ini` file will be generated in the same directory for configuration.

---

## ✨ Features

*   **Terminal User Interface:** Provides a text-based user interface using the `rich` library for formatted output, including a status dashboard and tables.
*   **Reward-Based Filtering:** Allows users to set a minimum monetary value to filter which feed entries trigger an alert.
*   **Desktop Notifications:** Delivers desktop notifications via `plyer` and can play a `.wav` sound file upon finding a qualifying entry.
*   **Interactive Console:** An interactive console accepts commands and aliases for real-time application control.
*   **State Persistence:** The application saves the last-seen feed entry to `config.ini` on exit, allowing it to resume without reprocessing old entries.
*   **Configuration File:** Most application behavior is controlled through a `config.ini` file.
*   **Error Handling:** Implements an exponential backoff strategy to handle temporary network or feed availability issues.
*   **Logging:** Can maintain a main application log and a secondary log that records all entries found in the feed.

---

## 🐍 Installation from Source

This method is for users who prefer to run the script directly from its source code.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/tdawe1/GengoWatcher.git
    cd GengoWatcher
    ```
2.  **Create and activate a virtual environment:**
    ```bash
    # On Windows
    python -m venv .venv
    .\.venv\Scripts\activate
    ```
3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Configure and Run:**
    The `config.ini` file will be generated on the first run. Edit this file with the required settings and then start the application:
    ```bash
    python gengowatcher.py
    ```

---

## ⚙️ Configuration (`config.ini`)

The `config.ini` file contains all user-configurable settings.

*   **`[Watcher]`**
    *   `feed_url`: The URL of the RSS feed to monitor.
    *   `check_interval`: Time in seconds between feed checks.
    *   `min_reward`: The minimum value to trigger an alert. A value of `0.0` disables the filter.
    *   `enable_notifications`: Toggles desktop notifications (`True`/`False`).
    *   `enable_sound`: Toggles sound alerts (`True`/`False`).
*   **`[Paths]`**
    *   `sound_file`: Filesystem path to a `.wav` file for sound alerts.
    *   `browser_path`: Path to a browser executable. If empty, the system default is used.
    *   `browser_args`: Command-line arguments for the custom browser (e.g., `--new-window {url}`).
*   **`[Logging]`**
    *   `log_main_enabled`: Toggles the main application log (`rss_check_log.txt`).
    *   `log_all_entries_enabled`: Toggles the log that records all found feed entries (`all_entries_log.txt`).

---

## ⌨️ Command Reference

Type a command or its alias and press Enter. Commands are not case-sensitive.

| Command              | Aliases          | Arguments  | Description                                        |
| -------------------- | ---------------- | ---------- | -------------------------------------------------- |
| **`status`**         | `s`, `st`        | -          | Show the application status dashboard.             |
| **`check`**          | `c`, `now`       | -          | Trigger an immediate RSS feed check.               |
| **`help`**           | `h`              | -          | Display the list of available commands.            |
| **`exit`**           | `q`, `quit`      | -          | Save state and exit the application.               |
| **`pause`**          | `p`              | -          | Pause RSS feed checks.                             |
| **`resume`**         | `r`              | -          | Resume RSS feed checks.                            |
| **`togglesound`**    | `ts`             | -          | Enable or disable sound alerts.                    |
| **`togglenotifications`** | `tn`        | -          | Enable or disable desktop notifications.           |
| **`setminreward`**   | `smr`            | `<amount>` | Set the minimum reward value for filtering.        |
| **`reloadconfig`**   | `rl`             | -          | Reload settings from the `config.ini` file.        |
| **`restart`**        | -                | -          | Restart the application.                           |
| **`notifytest`**     | `nt`             | -          | Send a test notification to verify settings.       |

---

## 📄 License

This project is distributed under the MIT License. See the `LICENSE` file for details.

---
## Acknowledgements
*   [Rich](https://github.com/Textualize/rich) - For terminal UI formatting.
*   [feedparser](https://github.com/kurtmckee/feedparser) - For RSS feed parsing.
*   [plyer](https://github.com/kivy/plyer) - For cross-platform desktop notifications.
