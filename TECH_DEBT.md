# Tech Debt Report

## 1. Architecture (Backend)

The core `GengoWatcher` class in `src/gengowatcher/watcher.py` is a classic "God Object" with low cohesion and high coupling.

*   **Size & Complexity**: The file is over 50KB and contains ~1000 lines of code. The `GengoWatcher` class handles:
    *   Configuration management
    *   State persistence
    *   RSS Feed fetching and parsing
    *   WebSocket connection management (with complex heartbeat and reconnect logic)
    *   Job processing and filtering
    *   Desktop notifications (GUI)
    *   Audio playback
    *   Job acceptance orchestration (threading)
    *   Browser automation integration
*   **Concurrency Model**: The code mixes `threading` and `asyncio` in a complex way. Methods like `cancel_current_job_sync` create new event loops, while `run` spawns threads that run `asyncio.run()`. This makes debugging and testing extremely difficult and is error-prone (e.g., `RuntimeError` if loops are nested improperly).
*   **Coupling**: High coupling between `GengoWatcher` and auxiliary classes (`BrowserAutomationEngine`, `JobAcceptanceEngine`, `CaptchaSolverManager`). Dependencies are sometimes imported inside `try/except` blocks to handle optionality, which leads to runtime fragility.
*   **Configuration**: `AppConfig` is passed around, but `GengoWatcher` also directly reads/writes config files and prompts users for input, mixing UI concerns with business logic.

## 2. Dependencies

*   **Outdated Packages**:
    *   `websockets` is pinned to `11.0.3` in `requirements.txt`, while the latest is `15.x`. This is a significant lag (major version 14 introduced breaking changes, so upgrading requires care).
    *   `selenium` is loose (`>=4.0.0`), which is good, but ensuring compatibility with the pinned `websockets` (which `selenium` might use indirectly or conflict with via `trio-websocket`) is important.
    *   `playwright` is present in the environment (v1.55.0) but not in `requirements.txt` (only `requirements-dev.txt` implies dev usage, but `frontend` verification might use it).
*   **Missing Dependencies**:
    *   `beautifulsoup4` was missing from the environment but required by `tests/test_recaptcha_v3_extraction.py`. It should be added to `requirements.txt`.
    *   `types-requests` and other type stubs are missing, causing `mypy` to fail on imports.

## 3. Testing

*   **Low Coverage**: Total code coverage is only **28%**.
    *   `watcher.py` coverage is 37%.
    *   `web.py`, `main.py`, `local_captcha_solver.py` have **0% coverage**.
*   **Test Failures**: Currently, **14 tests are failing** out of 65 (approx 20% failure rate).
    *   `test_auto_captcha.py`: Logic errors and TypeErrors suggesting code drift from tests.
    *   `test_config.py` & `test_watcher.py`: Mocking failures (`AssertionError: Expected '...' to be called once. Called 0 times`). This suggests the code implementation changed (e.g., side effects removed or changed) but tests weren't updated.
    *   `test_recaptcha_v3_extraction.py`: Failed due to missing `beautifulsoup4`.
*   **Test Quality**: Many tests rely heavily on mocking (e.g., `MagicMock`), which, while necessary for unit tests, has become brittle here. The mocks don't accurately reflect the current behavior of the dependencies.

## 4. Code Quality & Style

*   **Style Violations**: `flake8` reported **1140 violations**.
    *   The vast majority are `E501 line too long`, making code hard to read on standard splits.
    *   Occasional `W293` (blank line contains whitespace).
*   **Type Safety**: `mypy` reported **817 errors**.
    *   Most are due to missing type stubs (`import-untyped`) or `Optional` misuse (`Incompatible default for argument`).
    *   Many functions lack type annotations entirely (`def func(x) -> ?`), reducing the value of static analysis.
*   **Formatting**: `black` would reformat 27 files, indicating inconsistent code formatting across the project.

## 5. Frontend/Integration

*   **Frontend**: The frontend is a separate React application. Integration points (likely via `web.py` API or shared state) are not covered by integration tests.
*   **Duplicate Config**: Logic for "Job Sources" failed in tests because `config.get(...)` returned `None`, crashing when `.split()` was called. This indicates fragile configuration handling where defaults are not guaranteed.

## Recommendations

1.  **Refactor `GengoWatcher`**: Split it into smaller services: `NotificationService`, `RssMonitor`, `WebSocketMonitor`, `JobProcessor`. Use a proper event bus or queue for communication.
2.  **Fix Tests**: Prioritize fixing the 14 failing tests. Add `beautifulsoup4` to `requirements.txt`.
3.  **Upgrade Dependencies**: Bump `websockets` and verify/update `requirements.txt`.
4.  **Enforce Style**: Apply `black` formatting globally and configure `flake8` to ignore line length (or increase limit) if strict wrapping isn't desired, or better yet, let `black` handle it. Add type hints to critical paths.
5.  **Standardize Concurrency**: Choose one concurrency model (likely `asyncio` for I/O bound tasks) and stick to it, avoiding nested loops and mixed threading where possible.
