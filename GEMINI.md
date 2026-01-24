# GengoWatcher

## Project Overview

GengoWatcher is a Python application designed to monitor freelance job postings from Gengo. It uses a multi-source approach, fetching jobs from RSS feed, real-time WebSocket connection, email notifications (Gmail IMAP with OAuth2), and website scraping (Playwright stealth). The application features a text-based user interface (TUI) built with Textual for real-time monitoring and an optional FastAPI web server for external integrations.

Key features include:
- Real-time job monitoring from multiple sources
- Auto job acceptance with CAPTCHA solving
- Kanagawa Wave themed TUI dashboard
- Statistics tracking (session, all-time, by source)
- Desktop notifications and sound alerts

**Tech Stack:**

*   **Language:** Python 3.8+
*   **Main Libraries:**
    *   `textual`: For the terminal user interface (TUI)
    *   `rich`: For enhanced terminal output and logging
    *   `aiohttp`: For asynchronous HTTP requests
    *   `feedparser`: For parsing RSS feeds
    *   `websockets`: For WebSocket communication
    *   `fastapi`: For the optional web API
    *   `uvicorn`: For running the FastAPI server
    *   `selenium`/`playwright`: For browser automation
*   **Configuration:** The application uses a `config.ini` file for configuration.
*   **Entry Point:** `src/gengowatcher/main.py`

## Building and Running

### Installation

1.  Create and activate a Python virtual environment:
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    ```
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

### Running

*   **TUI only:**
    ```bash
    make run
    # or
    python -m gengowatcher.main
    ```
*   **TUI with web server:**
    ```bash
    make run-web
    # or
    python -m gengowatcher.main --web
    ```
*   **Web server only:**
    ```bash
    make run-web-only
    # or
    python -m gengowatcher.main --web-only
    ```

## Development Conventions

*   **Testing:** The project uses `pytest` for testing. Run tests with `make test`.
*   **Linting:** The project uses `flake8` for linting. Run the linter with `make lint`.
*   **Formatting:** The project uses `black` for code formatting. Format the code with `make format`.
*   **Coverage:** Run `make coverage` for test coverage report.

## Key Directories

```
src/gengowatcher/     # Main application code
  main.py             # CLI entry point
  watcher.py          # Job monitoring orchestrator
  ui_textual.py       # TUI widgets and app
  gengo_watcher.tcss  # TUI stylesheet (Kanagawa Wave theme)
  stats.py            # Statistics manager
  config.py           # Configuration handling
  state.py            # State persistence
  web.py              # FastAPI web server
tests/                # pytest test suite
docs/                 # Documentation and plans
assets/               # Screenshots and shared assets
```
