# Changelog

## [2.1.5] - 2025-06-23

### 🚀 Performance
- Drastically reduced idle CPU usage by replacing the high-frequency polling UI loop with an efficient, event-driven model. This results in near-zero CPU consumption when the application is running in the background.
- Eliminated input lag in the terminal, making the user interface feel instantly responsive.
- Reduced unnecessary disk I/O by optimizing the frequency of pause file checks.

### ✨ Added
- Added a new interactive diagnostic command, `wstest` (alias `wt`), to allow users to verify application health in real-time.
    - `wstest`: Checks WebSocket connection liveness with a PING/PONG test.
    - `wstest notify`: Simulates a fake job to test the full notification pipeline.

### 🔧 Changed
- Improved log message readability with enhanced color-coding:
    - New jobs are now highlighted in bold green.
    - Jobs ignored by the `min_reward` filter are now logged as yellow warnings.
- Standardized code formatting across the entire project for better readability and maintainability.

### 🐛 Fixed
- Resolved a race condition where job statistics could be calculated incorrectly from concurrent RSS and WebSocket events.
- Fixed a bug that caused the application to crash on startup when run in non-interactive terminals (e.g., IDE debug consoles).
- Corrected a rendering bug where `rich` markup tags in log messages were displayed as plain text instead of being parsed into colors.


## [2.0.0] - 2025-06-21

### 💥 Breaking Changes
- The application has been completely rewritten from a simple console script to a full-featured Terminal User Interface (TUI).
- The `config.ini` file format has changed significantly. Old configuration files are **not** compatible. The application will generate a new `config.ini` on first run.
- Persistent state (the last seen job) is now stored in `state.json` instead of the config file. [10]
- Command-line execution is now `python -m gengowatcher.main` or via a built executable, not `python gengowatcher.py`.

### ✨ Added
- Rich, interactive Text-Based User Interface (TUI) for at-a-glance status and control. [2, 11]
- Commands can be entered directly into the TUI (`help`, `pause`, `check`, `setminreward`, etc.). [2, 11]
- Cross-platform support for macOS and Linux, in addition to Windows. [2, 12]
- Ability to filter jobs by a minimum reward value (`setminreward` command). [2, 11]
- On-the-fly configuration changes for notifications and sound without restarting. [2, 11]
- Optional logging of all found jobs to a CSV file (`all_entries.log`) for data analysis. [12]
- A full test suite using `pytest` to ensure stability. [5, 15, 16, 17, 18]

### 🔧 Changed
- Project structure now follows standard Python packaging conventions (code is in the `src` directory). [8, 9, 10, 11, 12]
- Notifications now use the `plyer` library for better cross-platform compatibility. [6, 12]
- Installation is now done via `pip install -r requirements.txt`. [2, 7]

### 🗑️ Removed
- The old single-file `gengowatcher.py` script has been removed. [4]
- Direct integration with Vivaldi is replaced by a more generic browser-opening mechanism. [4, 12]