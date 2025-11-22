# GengoWatcher

## Project Overview

GengoWatcher is a Python application designed to monitor freelance job postings from Gengo. It uses a dual-source approach, fetching jobs from both a personal RSS feed and a real-time WebSocket connection. The application features a text-based user interface (TUI) for real-time monitoring and an optional web interface. It also includes features like auto job acceptance and CAPTCHA solving.

The project is a monorepo containing a Python backend and a React frontend.

**Backend:**

*   **Language:** Python
*   **Main Libraries:**
    *   `aiohttp`: For asynchronous HTTP requests.
    *   `feedparser`: for parsing RSS feeds.
    *   `rich`: For the text-based user interface (TUI).
    *   `websockets`: For WebSocket communication.
    *   `fastapi`: For the web API.
    *   `uvicorn`: For running the FastAPI server.
    *   `selenium`: For browser automation.
*   **Configuration:** The application uses a `config.ini` file for configuration.
*   **Entry Point:** `src/gengowatcher/main.py`

**Frontend:**

*   **Framework:** React
*   **Build Tool:** Vite
*   **Styling:** Tailwind CSS and Material-UI
*   **Key Libraries:**
    *   `@mui/material`: For UI components.
    *   `@nivo/*`: For data visualization.
    *   `react-router-dom`: For routing.
    *   `@tanstack/react-query`: For data fetching.
*   **Package Manager:** npm

## Building and Running

### Backend

**Installation:**

1.  Create and activate a Python virtual environment.
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

**Running:**

*   **TUI only:**
    ```bash
    python -m gengowatcher.main
    ```
*   **TUI with web server:**
    ```bash
    python -m gengowatcher.main --web
    ```
*   **Web server only:**
    ```bash
    python -m gengowatcher.main --web-only
    ```

### Frontend

**Installation:**

1.  Navigate to the `frontend` directory.
2.  Install dependencies:
    ```bash
    npm install
    ```

**Running:**

*   **Development server:**
    ```bash
    npm run dev
    ```
*   **Build for production:**
    ```bash
    npm run build
    ```
*   **Preview production build:**
    ```bash
    npm run preview
    ```

## Development Conventions

### Backend

*   **Testing:** The project uses `pytest` for testing. Run tests with `make test`.
*   **Linting:** The project uses `flake8` for linting. Run the linter with `make lint`.
*   **Formatting:** The project uses `black` for code formatting. Format the code with `make format`.

### Frontend

*   **Testing:** The project uses `vitest` for testing. Run tests with `npm test`.
*   **Linting:** The project uses `eslint` for linting. Run the linter with `npm run lint`.
