# GengoWatcher Project Context

## Project Overview

GengoWatcher is a Python terminal application that monitors freelance job opportunities from Gengo using both RSS feeds and WebSocket connections. It features a rich Text-Based User Interface (TUI) built with the `rich` library, providing real-time status updates and interactive controls.

### Key Features
- **Dual-Source Monitoring**: Uses both RSS feeds (fallback) and WebSocket connections (primary) for job detection
- **Interactive TUI**: Modern terminal interface with live updates using the `rich` library
- **Real-time Notifications**: Desktop notifications and sound alerts for new jobs
- **Configurable Filtering**: Filter jobs by minimum reward value
- **Persistent State**: Tracks seen jobs in `state.json` to avoid duplicate notifications
- **CSV Logging**: Optional logging of all job entries to a CSV file for analysis
- **Cross-platform**: Works on Windows, macOS, and Linux

### Core Technologies
- Python 3.8+
- `rich` library for TUI
- `feedparser` for RSS parsing
- `websockets` library (v11.0.3) for real-time connections
- `plyer` for cross-platform notifications
- `pytest` for testing

## Project Structure

```
src/gengowatcher/     # Main package
├── __init__.py
├── main.py          # Application entry point
├── watcher.py       # Core monitoring logic
├── ui.py           # TUI interface
├── config.py        # Configuration management
└── state.py         # State persistence

tests/               # Test suite
├── test_*.py       # Test modules
└── conftest.py     # Test fixtures

requirements.txt     # Runtime dependencies
requirements-dev.txt # Development dependencies
config.ini           # User configuration (created on first run)
state.json           # Persistent application state
```

## Core Components

### Main Modules
1. **`gengowatcher/main.py`** - Entry point, CLI argument parsing, logging setup
2. **`gengowatcher/watcher.py`** - Core monitoring logic for RSS and WebSocket feeds
3. **`gengowatcher/ui.py`** - Rich-based TUI interface with live updates and command handling
4. **`gengowatcher/config.py`** - Configuration management (reads/writes `config.ini`)
5. **`gengowatcher/state.py`** - Persistent state management (tracks seen jobs in `state.json`)

### Architecture Patterns
- **Threading Model**: Separate threads for watcher and UI to maintain responsiveness
- **Event Coordination**: Uses `shutdown_event` and `check_now_event` for thread communication
- **State Persistence**: Deduplication using `state.json` to track seen job IDs
- **Configuration Management**: INI-based config with interactive setup for missing values

## Development Workflow

### Running the Application
```bash
# Run the main application
python -m gengowatcher.main

# Interactive configuration setup
python -m gengowatcher.main --configure

# Set config value via CLI
python -m gengowatcher.main --set SECTION OPTION VALUE

# Get config value via CLI
python -m gengowatcher.main --get SECTION OPTION

# List all configuration values
python -m gengowatcher.main --list
```

### Testing and Quality
```bash
# Run all tests
pytest
make test

# Run specific test file
pytest tests/test_websocket.py

# Run tests with verbose output
pytest -s -v

# Run tests with coverage report
pytest --cov=.
make coverage

# Run linting
flake8 .
make lint

# Format code with Black
black .
make format
```

### Dependencies
```bash
# Install runtime dependencies
pip install -r requirements.txt

# Install all dependencies including dev tools
pip install -r requirements-dev.txt
```

## Configuration System

Configuration is stored in `config.ini` with the following sections:
- `[Watcher]` - RSS feed settings, intervals, reward filters
- `[WebSocket]` - Real-time connection settings
- `[Paths]` - File paths for sounds, logs, browser
- `[Logging]` - Log rotation and CSV export settings
- `[Network]` - Connection timeouts and user agent settings

## Key Commands

Within the TUI, users can enter these commands:
- `help` - Display command list
- `check` - Trigger immediate RSS feed check
- `pause`/`resume` - Pause/resume monitoring
- `setminreward <amt>` - Set minimum reward filter
- `togglenotifications`/`togglesound` - Toggle notification types
- `togglewebsocket` - Enable/disable WebSocket monitoring
- `reloadconfig` - Reload configuration from file
- `restart` - Restart the application
- `wstest` - Test WebSocket connectivity
- `wstest notify` - Test notification pipeline with fake job
- `notifytest` - Test notification system
- `clear` - Clear command output
- `exit`/`quit` - Exit the application

## Testing Strategy

The test suite uses `pytest` with the following structure:
- `tests/test_websocket.py` - WebSocket connection and message handling
- `tests/test_watcher.py` - Core watcher functionality
- `tests/test_ui.py` - TUI command handling
- `tests/test_config.py` - Configuration management
- `tests/test_state.py` - State persistence
- `tests/conftest.py` - Shared test fixtures

## Platform Considerations

- Cross-platform sound playback (winsound on Windows, paplay on Linux)
- Terminal input handling differences (msvcrt vs termios)
- Path handling for config/state files
- Desktop notification compatibility via plyer

## Recent Improvements (v2.1.5)

- Drastically reduced idle CPU usage with event-driven model
- Added interactive diagnostic command `wstest` for WebSocket testing
- Improved log message readability with enhanced color-coding
- Fixed race conditions and rendering bugs
- Resolved issues with non-interactive terminal execution

## Upcoming Features

### Captcha Solving Integration
- Modular captcha solving service integration for automated job rejection
- Support for 2Captcha and Anti-Captcha providers
- Configurable auto-rejection based on job criteria
- Secure handling of API credentials
- Graceful error handling and fallback mechanisms