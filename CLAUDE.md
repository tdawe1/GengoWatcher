# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Running the Application
- `python -m gengowatcher.main` - Run the main application with TUI interface
- `python -m gengowatcher.main --web` - Run TUI with web server enabled (default port: 8000)
- `python -m gengowatcher.main --web-only` - Run web server only (no TUI)
- `python -m gengowatcher.main --web-port PORT` - Specify web server port
- `python -m gengowatcher.main --configure` - Run interactive configuration setup
- `python -m gengowatcher.main --set SECTION OPTION VALUE` - Set config value via CLI
- `python -m gengowatcher.main --get SECTION OPTION` - Get config value via CLI
- `python -m gengowatcher.main --list` - List all configuration values

### Frontend Development
- `cd frontend && npm install` - Install frontend dependencies
- `cd frontend && npm run dev` - Start Vite dev server (port 5173)
- `cd frontend && npm run build` - Build frontend for production
- `cd frontend && npm run lint` - Run ESLint
- `cd frontend && npm run test` - Run Vitest tests
- `cd frontend && npm run test:coverage` - Run tests with coverage

### CAPTCHA Management
- `python -m gengowatcher.main captchasetup` - Interactive CAPTCHA service setup
- `python -m gengowatcher.main captchatest` - Test CAPTCHA solving service
- `python -m gengowatcher.main captchastats` - View CAPTCHA statistics
- `python -m gengowatcher.main captchareset` - Reset CAPTCHA configuration

### Testing and Quality
- `pytest` or `make test` - Run all tests
- `pytest tests/test_websocket.py` - Run specific test file
- `pytest -s -v` - Run tests with verbose output
- `pytest --cov=.` or `make coverage` - Run tests with coverage report
- `flake8 .` or `make lint` - Run linting
- `black .` or `make format` - Format code with Black

### Dependencies
- `pip install -r requirements.txt` - Install runtime dependencies
- `pip install -r requirements-dev.txt` - Install all dependencies including dev tools

## Architecture Overview

### Core Components
GengoWatcher is a comprehensive freelance job monitoring platform with TUI and web interfaces:

**Main Modules:**
- `gengowatcher/main.py` - Application entry point, argument parsing, logging setup
- `gengowatcher/watcher.py` - Core monitoring logic for RSS and WebSocket feeds
- `gengowatcher/ui.py` - Rich-based TUI interface with live updates and command handling
- `gengowatcher/config.py` - Configuration management (reads/writes `config.ini`)
- `gengowatcher/state.py` - Persistent state management (tracks seen jobs in `state.json`)
- `gengowatcher/web.py` - FastAPI web server with RESTful API and WebSocket support

**Advanced Features:**
- `gengowatcher/job_acceptance.py` - Automated job acceptance engine with rate limiting
- `gengowatcher/captcha_manager.py` - CAPTCHA solving service management
- `gengowatcher/captcha_solver.py` - CAPTCHA solver implementations (2Captcha, AntiCaptcha)
- `gengowatcher/secure_storage.py` - Encrypted API key storage
- `gengowatcher/rate_limiter.py` - Sliding window rate limiting implementation
- `gengowatcher/browser_automation/` - Browser-based job acceptance framework

**Frontend Application:**
- **React 18** with TypeScript and Material-UI components
- **Vite** build tool with hot reload
- **TanStack Query** for server state management
- **ApexCharts** and **Nivo** for data visualization

**Key Technologies:**
- **TUI Framework**: Rich library for terminal UI with live updates
- **WebSocket**: Real-time job monitoring via websockets library (v11.0.3)
- **FastAPI**: Modern web API framework with automatic documentation
- **RSS Parsing**: feedparser for RSS feed monitoring
- **Notifications**: plyer for cross-platform desktop notifications
- **Threading**: Separate threads for watcher, UI, and web server
- **Async Operations**: aiohttp for non-blocking HTTP requests
- **Sound Playback**: winsound (Windows) / paplay (Linux)

### Data Flow Architecture
1. **Dual Monitoring Sources**: RSS feed (fallback) + WebSocket (primary) for job detection
2. **State Persistence**: Deduplication using `state.json` to track seen job IDs
3. **Event-Driven**: Threading events for immediate checks and graceful shutdown
4. **Notification Pipeline**: Desktop notifications + sound alerts + CSV logging

### Key Patterns

**Configuration Management:**
- INI-based config with interactive setup for missing values
- Environment-specific paths and user preferences
- Hot reload capability via `reloadconfig` command

**Threading Model:**
- Main thread: Rich TUI with live updates (60fps-like refresh)
- Watcher thread: RSS polling + WebSocket connection management
- Event coordination: `shutdown_event`, `check_now_event` for thread communication

**WebSocket Testing:**
- `wstest` command (alias `wt`) for PING connectivity tests
- `wstest notify` for end-to-end notification pipeline testing
- Status tracking: "Disabled", "Connecting", "Live", "Error" states

**Error Handling:**
- Exponential backoff for connection failures
- Graceful degradation (WebSocket fails → RSS-only mode)
- Comprehensive logging with rotating file handlers

## Testing Strategy

### Test Structure
- `tests/test_websocket.py` - WebSocket connection and message handling tests
- `tests/test_watcher.py` - Core watcher functionality tests
- `tests/test_ui.py` - TUI command handling tests
- `tests/test_config.py` - Configuration management tests
- `tests/test_state.py` - State persistence tests
- `tests/conftest.py` - Shared test fixtures

**Mock Patterns:**
- AsyncMock for WebSocket connections
- MagicMock for config/state objects
- Parametrized tests for different platform behaviors

### WebSocket Testing Commands
Within the application:
- `wstest` - Test WebSocket PING if connection is live
- `wstest notify` - Test full notification pipeline with fake job
- `notifytest` - Test notification system without WebSocket

### Testing Patterns

**Backend Testing:**
- Use `pytest` with `AsyncMock` for async operations
- Mock external services (CAPTCHA, job APIs)
- Test thread safety with concurrent operations
- Validate configuration parsing and validation

**Frontend Testing:**
- Vitest with React Testing Library
- Mock API calls with MSW (Mock Service Worker)
- Test component state and user interactions
- Validate form submissions and error handling

**Integration Testing:**
- End-to-end job acceptance flows
- WebSocket message handling
- CAPTCHA solving integration
- Web API endpoint validation

**Security Testing:**
- Validate input sanitization
- Test authentication and authorization
- Verify encryption/decryption operations
- Check rate limiting enforcement

## Development Environment

### Project Structure
```
src/gengowatcher/           # Main package
├── __init__.py
├── main.py                # Entry point
├── watcher.py             # Core monitoring
├── ui.py                  # TUI interface
├── config.py              # Configuration
├── state.py               # State management
├── web.py                 # FastAPI web server
├── job_acceptance.py      # Auto-accept engine
├── captcha_manager.py     # CAPTCHA service manager
├── captcha_solver.py      # CAPTCHA solver implementations
├── secure_storage.py      # Encrypted storage
├── rate_limiter.py        # Rate limiting
├── captcha_cli.py         # CAPTCHA CLI interface
├── browser_automation/    # Browser automation framework
│   ├── __init__.py
│   ├── engine.py
│   └── profiles.py

frontend/                  # React frontend
├── src/
│   ├── components/        # Reusable components
│   ├── pages/            # Page components
│   ├── hooks/            # Custom React hooks
│   ├── store/            # Zustand state store
│   └── utils/            # Utility functions
├── public/               # Static assets
└── package.json

tests/                    # Test suite
├── test_*.py
└── conftest.py

requirements.txt          # Runtime dependencies
requirements-dev.txt      # Dev dependencies + test tools
config.ini               # User configuration
state.json               # Persistent application state
Makefile                 # Build automation
```

### Platform Considerations
- Cross-platform sound playback (winsound on Windows, paplay on Linux)
- Terminal input handling differences (msvcrt vs termios)
- Path handling for config/state files
- Desktop notification compatibility via plyer

### Configuration System
Configuration is stored in `config.ini` with sections:
- `[Watcher]` - RSS feed settings, intervals, reward filters
- `[WebSocket]` - Real-time connection settings
- `[Paths]` - File paths for sounds, logs, browser
- `[Logging]` - Log rotation and CSV export settings
- `[Network]` - Connection timeouts and user agent settings
- `[AutoAccept]` - Automated job acceptance criteria and behavior
- `[Captcha]` - CAPTCHA solving service configuration
- `[WebServer]` - Web API server settings and authentication

### Important Implementation Details

**WebSocket Version**: The project uses websockets==11.0.3 specifically. Other versions may cause compatibility issues.

**Module Entry Point**: The application is run using `python -m gengowatcher.main` rather than direct script execution.

**State Management**: Uses threading.Lock for thread-safe operations on shared state like `_seen_jobs_session`.

**Logging**: Implements custom UILoggingHandler that captures logs and displays them in the TUI with timestamps and color-coded levels.

**Sound System**: Uses paplay on Linux and winsound on Windows for notification sounds.

### Advanced Features Architecture

**Job Acceptance Engine:**
- Configurable reward range and source filtering
- Rate limiting (30 requests/minute default)
- Integration with CAPTCHA solving
- Asynchronous operations with retry logic
- Structured logging for audit trail

**CAPTCHA Solving System:**
- Service abstraction supporting multiple providers (2Captcha, AntiCaptcha)
- Connection pooling (20 pools, 50 connections each)
- Adaptive polling with exponential backoff
- Encrypted API key storage with AES-GCM
- Performance metrics and cost tracking

**Web API Architecture:**
- RESTful endpoints with Pydantic validation
- WebSocket support for real-time updates
- Bearer token authentication
- CORS configuration for security
- Thread-safe operations with reentrant locks

**Security Implementation:**
- System-specific key derivation for encryption
- Restrictive file permissions (0o600)
- Secure session management
- Input validation and sanitization
- Rate limiting on API endpoints