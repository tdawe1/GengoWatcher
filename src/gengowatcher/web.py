"""
Web API layer for GengoWatcher - provides REST and WebSocket endpoints
for web UI integration while maintaining compatibility with existing TUI.
"""

import asyncio
import json
import logging
import threading
import time
import secrets
import csv
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    Request,
    Depends,
    Query,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
import uvicorn
import os

from .config import AppConfig
from .state import AppState
from .watcher import GengoWatcher

# Authentication
security = HTTPBearer(auto_error=False)


class APIAuthenticator:
    """Simple API key authentication for web API."""

    def __init__(self, api_key: str = None):
        """Initialize the API authenticator.

        Args:
            api_key: Optional API key string. If not provided, generates a secure random key.
        """
        self.api_key = api_key or secrets.token_urlsafe(32)

    def authenticate(
        self, credentials: HTTPAuthorizationCredentials = Depends(security)
    ) -> bool:
        """Authenticate API request using Bearer token."""
        if not credentials:
            return False
        return credentials.credentials == self.api_key

    def get_api_key(self) -> str:
        """Get the current API key."""
        return self.api_key


# Global authenticator instance
authenticator = APIAuthenticator()


# Pydantic models for API responses
class JobEntry(BaseModel):
    id: str
    title: str
    reward: float
    currency: str = "USD"
    url: str
    timestamp: float
    source: str  # "rss" or "websocket"

    @field_validator("id", "title", "url", "source")
    @classmethod
    def validate_string_fields(cls, v):
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Field must be a non-empty string")
        return v.strip()

    @field_validator("reward")
    @classmethod
    def validate_reward(cls, v):
        if not isinstance(v, (int, float)) or v < 0:
            raise ValueError("Reward must be a non-negative number")
        return float(v)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v):
        if not isinstance(v, (int, float)) or v < 0:
            raise ValueError("Timestamp must be a valid positive number")
        return float(v)


class WatcherStatus(BaseModel):
    is_running: bool
    websocket_status: str
    rss_status: str
    last_check_time: Optional[float]
    next_check_time: float
    session_stats: Dict[str, Any]
    failure_count: int
    cancellation_stats: Optional[Dict[str, Any]] = None
    health: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("websocket_status", "rss_status")
    @classmethod
    def validate_status_fields(cls, v):
        if not isinstance(v, str):
            raise ValueError("Status must be a string")
        return v.strip()


class ConfigSection(BaseModel):
    section: str
    options: Dict[str, Any]

    @field_validator("section")
    @classmethod
    def validate_section(cls, v):
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Section must be a non-empty string")
        return v.strip()


class CommandRequest(BaseModel):
    command: str
    args: Optional[List[str]] = []

    @field_validator("command")
    @classmethod
    def validate_command(cls, v):
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Command must be a non-empty string")
        allowed_commands = ["check", "pause", "resume", "ping", "notify", "cancel"]
        if v.strip().lower() not in allowed_commands:
            raise ValueError(f"Command must be one of: {', '.join(allowed_commands)}")
        return v.strip().lower()

    @field_validator("args")
    @classmethod
    def validate_args(cls, v):
        if v is not None:
            if not isinstance(v, list):
                raise ValueError("Args must be a list or None")
            for arg in v:
                if not isinstance(arg, str):
                    raise ValueError("All args must be strings")
        return v


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("page", "limit")
    @classmethod
    def validate_pagination(cls, v, info):
        field_name = info.field_name
        if not isinstance(v, int) or v < 1:
            raise ValueError(f"{field_name} must be a positive integer")
        if field_name == "limit" and v > 100:
            raise ValueError("Limit cannot exceed 100")
        return v


class WebAPI:
    """Web API wrapper for GengoWatcher that maintains thread safety."""

    def __init__(self, config: AppConfig, state: AppState, logger: logging.Logger):
        """Initialize the WebAPI instance.

        Creates a separate GengoWatcher instance for the web API to avoid conflicts
        with the TUI. Sets up thread safety mechanisms and starts the watcher thread.

        Args:
            config: Application configuration object.
            state: Application state object for data persistence.
            logger: Logger instance for recording events.
        """
        self.config = config
        self.state = state
        self.logger = logger

        # Create a separate watcher instance for web API
        # This allows web UI to run alongside TUI without conflicts
        self.watcher = GengoWatcher(config, state, logger)

        # Thread safety for shared state access
        self._status_lock = threading.RLock()  # Reentrant lock for better safety
        self._active_connections: List[WebSocket] = []
        self._connections_lock = threading.RLock()
        self._jobs_lock = threading.RLock()

        # Start the watcher in a separate thread
        self.watcher_thread = threading.Thread(
            target=self.watcher.run, daemon=True, name="WebWatcherThread"
        )
        self.watcher_thread.start()

        self.logger.info("WebAPI initialized and watcher thread started")

    def get_status(self) -> WatcherStatus:
        """Get current watcher status."""
        with self._status_lock:
            # Convert datetime to timestamp for JSON serialization
            last_check = None
            if self.watcher.last_check_time:
                if isinstance(self.watcher.last_check_time, float):
                    last_check = self.watcher.last_check_time
                else:
                    # Assume it's a datetime object
                    last_check = self.watcher.last_check_time.timestamp()

            health_snapshot = {}
            health_getter = getattr(self.watcher, "get_health_snapshot", None)
            if callable(health_getter):
                try:
                    candidate = health_getter()
                except Exception as exc:
                    self.logger.warning(
                        "Failed to collect watcher health snapshot: %s",
                        exc,
                    )
                else:
                    if isinstance(candidate, dict):
                        health_snapshot = candidate

            return WatcherStatus(
                is_running=not self.watcher.shutdown_event.is_set(),
                websocket_status=self.watcher.websocket_status,
                rss_status=self.watcher.rss_action,
                last_check_time=last_check,
                next_check_time=self.watcher.next_check_time,
                session_stats={
                    "new_entries": self.watcher.session_new_entries,
                    "total_value": self.watcher.session_total_value,
                    "uptime": time.time() - self.watcher.start_time,
                },
                failure_count=self.watcher.failure_count,
                cancellation_stats=self.watcher.get_cancellation_stats(),
                health=health_snapshot,
            )

    async def cancel_current_job(self) -> bool:
        """Cancel the currently tracked job via the watcher."""
        return await self.watcher.cancel_current_job_async()

    def get_recent_jobs(self, limit: int = 50, page: int = 1) -> Dict[str, Any]:
        """Get recent jobs from state with pagination."""
        try:
            with self._jobs_lock:
                recent_jobs = self.state.get_recent_jobs(
                    limit * page
                )  # Get more to handle pagination
                total_jobs = len(recent_jobs)

                # Apply pagination
                start_idx = (page - 1) * limit
                end_idx = start_idx + limit
                paginated_jobs = recent_jobs[start_idx:end_idx]

                jobs = []
                for job_data in paginated_jobs:
                    try:
                        jobs.append(JobEntry(**job_data))
                    except Exception as e:
                        self.logger.warning(f"Invalid job data: {e}, skipping job")

                return {
                    "jobs": jobs,
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": total_jobs,
                        "pages": (total_jobs + limit - 1) // limit,  # Ceiling division
                    },
                }
        except Exception as e:
            self.logger.exception(f"Error retrieving recent jobs: {e}")
            return {
                "jobs": [],
                "pagination": {"page": page, "limit": limit, "total": 0, "pages": 0},
            }

    def get_jobs_from_csv(
        self,
        limit: int = 50,
        page: int = 1,
        min_reward: Optional[float] = None,
        max_reward: Optional[float] = None,
        search_term: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get jobs from CSV file with pagination and filtering."""
        try:
            # Get CSV file path from config
            csv_file_path = self.config.get(
                "Paths", "all_entries_log", fallback="logs/all_entries.csv"
            )

            # Check if file exists
            if not os.path.exists(csv_file_path):
                self.logger.warning(f"CSV file not found: {csv_file_path}")
                return {
                    "jobs": [],
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": 0,
                        "pages": 0,
                    },
                }

            # Count total rows first (for pagination)
            total_rows = 0
            with open(csv_file_path, "r", encoding="utf-8") as f:
                total_rows = sum(1 for line in f) - 1  # Subtract 1 for header row

            # If no rows, return empty result
            if total_rows <= 0:
                return {
                    "jobs": [],
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": 0,
                        "pages": 0,
                    },
                }

            jobs = []
            current_row = 0
            start_idx = (page - 1) * limit
            end_idx = start_idx + limit
            rows_processed = 0

            # Read CSV file with filtering
            with open(csv_file_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)

                for row in reader:
                    current_row += 1

                    # Skip header row if present
                    if current_row == 1 and row.get("timestamp") == "timestamp":
                        continue

                    try:
                        # Extract data from row
                        timestamp = row.get("timestamp", "")
                        title = row.get("title", "N/A")
                        reward_str = row.get("reward", "0")
                        link = row.get("link", "")
                        summary = row.get("summary", "")

                        # Convert reward to float
                        try:
                            reward = float(reward_str) if reward_str else 0.0
                        except ValueError:
                            reward = 0.0

                        # Apply reward filtering
                        if min_reward is not None and reward < min_reward:
                            continue
                        if max_reward is not None and reward > max_reward:
                            continue

                        # Apply search filtering
                        if search_term:
                            search_lower = search_term.lower()
                            if (
                                search_lower not in title.lower()
                                and search_lower not in summary.lower()
                            ):
                                continue

                        # Create job entry
                        job_entry = JobEntry(
                            id=str(hash(f"{link}{timestamp}")),  # Create unique ID
                            title=title,
                            reward=reward,
                            currency="USD",
                            url=link,
                            timestamp=time.time(),  # Use current time since we don't have exact timestamp
                            source="csv",
                        )

                        # Apply pagination
                        if rows_processed >= start_idx and rows_processed < end_idx:
                            jobs.append(job_entry)

                        rows_processed += 1

                        # Stop if we have enough jobs
                        if len(jobs) >= limit:
                            break

                    except Exception as e:
                        self.logger.warning(
                            f"Error processing CSV row {current_row}: {e}"
                        )
                        continue

            return {
                "jobs": jobs,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": rows_processed,
                    "pages": (rows_processed + limit - 1) // limit,  # Ceiling division
                },
            }

        except FileNotFoundError:
            self.logger.warning(f"CSV file not found: {csv_file_path}")
            return {
                "jobs": [],
                "pagination": {"page": page, "limit": limit, "total": 0, "pages": 0},
            }
        except Exception as e:
            self.logger.exception(f"Error reading jobs from CSV: {e}")
            return {
                "jobs": [],
                "pagination": {"page": page, "limit": limit, "total": 0, "pages": 0},
            }

    def add_job(self, job_id: str, title: str, reward: float, url: str, source: str):
        """Add a new job to the state storage."""
        try:
            with self._jobs_lock:
                job_data = {
                    "id": job_id,
                    "title": title,
                    "reward": reward,
                    "currency": "USD",
                    "url": url,
                    "timestamp": time.time(),
                    "source": source,
                }
                self.state.add_job(job_data)
                self.logger.debug(f"Added job to storage: {job_id}")
        except Exception as e:
            self.logger.exception(f"Error adding job to storage: {e}")

    async def accept_job(self, job_id: str) -> bool:
        """Accept a job by ID using the job acceptance engine."""
        try:
            # Check if the watcher has a job acceptance engine
            if not hasattr(self.watcher, "job_acceptance_engine"):
                self.logger.error("Job acceptance engine not available")
                return False

            # Find the job in the state
            jobs_result = self.get_recent_jobs(limit=1000)  # Get all jobs to search
            jobs = jobs_result["jobs"]
            target_job = None

            for job in jobs:
                if str(job.id) == str(job_id):
                    target_job = {
                        "id": job.id,
                        "title": job.title,
                        "reward": job.reward,
                        "url": job.url,
                        "source": job.source,
                    }
                    break

            if not target_job:
                self.logger.error(f"Job {job_id} not found")
                return False

            # Attempt to accept the job
            success = await self.watcher.job_acceptance_engine._attempt_job_acceptance(
                target_job
            )
            return success

        except Exception as e:
            self.logger.exception(f"Error accepting job {job_id}: {e}")
            return False

    def get_config(self) -> List[ConfigSection]:
        """Get current configuration."""
        sections = []
        # Use the proper config access methods
        for section_name in self.config.config.keys():
            section_data = {}
            for key in self.config.config[section_name].keys():
                try:
                    # Try to get the value using the appropriate method based on type
                    default_val = self.config.config[section_name][key]
                    if isinstance(default_val, bool):
                        value = self.config.getboolean(section_name, key, default_val)
                    elif isinstance(default_val, int):
                        value = self.config.getint(section_name, key, default_val)
                    elif isinstance(default_val, float):
                        value = self.config.getfloat(section_name, key, default_val)
                    else:
                        value = self.config.get(section_name, key, default_val)
                    section_data[key] = value
                except Exception:
                    # Fallback to direct access if method fails
                    section_data[key] = self.config.config[section_name][key]
            sections.append(ConfigSection(section=section_name, options=section_data))
        return sections

    def update_config(self, section: str, option: str, value: str) -> bool:
        """Update configuration value."""
        try:
            self.watcher.set_config_value(section, option, value)
            return True
        except Exception as e:
            self.logger.exception(f"Failed to update config {section}.{option}: {e}")
            return False

    def execute_command(
        self, command: str, args: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Execute a watcher command."""
        try:
            if command == "check":
                self.watcher.check_now_event.set()
                return {"status": "success", "message": "Check triggered"}
            elif command == "pause":
                # Create pause file
                with open(self.watcher.PAUSE_FILE, "w") as f:
                    f.write("")
                return {"status": "success", "message": "Watcher paused"}
            elif command == "resume":
                # Remove pause file
                try:
                    import os

                    os.remove(self.watcher.PAUSE_FILE)
                except FileNotFoundError:
                    pass
                return {"status": "success", "message": "Watcher resumed"}
            elif command == "cancel":
                success = self.watcher.cancel_current_job_sync()
                if success:
                    return {"status": "success", "message": "Current job cancelled"}
                return {
                    "status": "error",
                    "message": "No active job to cancel or cancellation failed",
                }
            else:
                return {"status": "error", "message": f"Unknown command: {command}"}
        except Exception as e:
            # Log full details server-side, but return a generic error message
            self.logger.exception(
                f"Unexpected error executing watcher command '%s': %s",
                command,
                e,
            )
            return {
                "status": "error",
                "message": "Internal command execution error",
            }

    async def broadcast_status_update(self):
        """Broadcast status update to all connected WebSocket clients."""
        status = self.get_status()
        message = {"type": "status_update", "data": status.model_dump()}

        with self._connections_lock:
            disconnected = []
            for connection in self._active_connections:
                try:
                    await connection.send_json(message)
                except Exception:
                    disconnected.append(connection)

            # Clean up disconnected clients
            for conn in disconnected:
                self._active_connections.remove(conn)

    def shutdown(self):
        """Shutdown the web API and watcher."""
        self.logger.info("Shutting down WebAPI")
        self.watcher.handle_exit()


# Global API instance
api_instance: Optional[WebAPI] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager."""
    global api_instance

    # Startup
    logger = logging.getLogger("gengowatcher.web")
    try:
        # Check if config exists, create it if needed
        from pathlib import Path

        config_path = Path(AppConfig.CONFIG_FILE)
        if not config_path.exists():
            logger.info("Creating default %s for web API", AppConfig.CONFIG_FILE)
            config_path.write_text(
                AppConfig._dump_toml(AppConfig.DEFAULT_CONFIG),
                encoding="utf-8",
            )
            logger.info(
                "Default config created. Please review %s before using the web API.",
                AppConfig.CONFIG_FILE,
            )

        config = AppConfig()
        state = AppState(logger=logger)

        # Initialize authenticator with config token
        api_token = config.get("WebServer", "auth_token")

        if not api_token or api_token == "REPLACE_WITH_YOUR_WEB_API_TOKEN":
            api_token = secrets.token_urlsafe(32)
            config.set("WebServer", "auth_token", api_token)
            config.save_config()
            logger.warning(
                "No WebServer auth_token found or it was a placeholder. Generated a new one."
            )
            logger.warning(
                "Check %s [WebServer] for the auth_token value.",
                AppConfig.CONFIG_FILE,
            )

        global authenticator
        authenticator = APIAuthenticator(api_token)

        api_instance = WebAPI(config, state, logger)
        logger.info("WebAPI started successfully")
    except Exception as e:
        logger.exception(f"Failed to start WebAPI: {e}")
        raise

    yield

    # Shutdown
    if api_instance:
        api_instance.shutdown()


# Create FastAPI app
app = FastAPI(
    title="GengoWatcher API",
    description="Web API for GengoWatcher job monitoring application",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware with security restrictions
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",  # Vite dev server
        "http://127.0.0.1:5173",
        "http://localhost:5174",  # Vite dev server (alternative port)
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# Mount static files for React app
static_path = os.path.join(os.path.dirname(__file__), "..", "..", "static", "web")
if os.path.exists(static_path):
    app.mount("/web", StaticFiles(directory=static_path, html=True), name="web")
else:
    logging.getLogger("gengowatcher.web").warning(
        f"Static files directory not found: {static_path}"
    )


async def verify_auth(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify API authentication."""
    if not authenticator.authenticate(credentials):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True


@app.get("/api/status", response_model=WatcherStatus)
async def get_status(authenticated: bool = Depends(verify_auth)):
    """Get current watcher status."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")
    try:
        return api_instance.get_status()
    except Exception as e:
        api_instance.logger.exception(f"Error getting status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/jobs")
async def get_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    min_reward: Optional[float] = Query(None, ge=0),
    max_reward: Optional[float] = Query(None, ge=0),
    search: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    authenticated: bool = Depends(verify_auth),
):
    """Get recent jobs with pagination and filtering."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")

    try:
        # If source is specified as 'csv' or if we want to include CSV data, read from CSV
        if source == "csv":
            result = api_instance.get_jobs_from_csv(
                limit=limit,
                page=page,
                min_reward=min_reward,
                max_reward=max_reward,
                search_term=search,
            )
            return result
        else:
            # Default behavior - get recent jobs from state
            result = api_instance.get_recent_jobs(limit, page)
            return result
    except Exception as e:
        api_instance.logger.exception(f"Error getting jobs: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/jobs/{job_id}/accept")
async def accept_job(job_id: str, authenticated: bool = Depends(verify_auth)):
    """Force accept a job by ID."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")

    try:
        success = await api_instance.accept_job(job_id)

        if success:
            return {
                "status": "success",
                "message": f"Job {job_id} accepted successfully",
            }
        else:
            raise HTTPException(
                status_code=500, detail=f"Failed to accept job {job_id}"
            )

    except HTTPException:
        raise
    except Exception as e:
        api_instance.logger.exception(f"Error accepting job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/api/jobs/cancel")
async def cancel_current_job(authenticated: bool = Depends(verify_auth)):
    """Cancel the currently tracked job."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")

    try:
        success = await api_instance.cancel_current_job()
        if success:
            return {"status": "success", "message": "Current job cancelled"}
        raise HTTPException(
            status_code=400, detail="No active job to cancel or cancellation failed"
        )
    except HTTPException:
        raise
    except Exception as e:
        api_instance.logger.exception(f"Error cancelling current job: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/config", response_model=List[ConfigSection])
async def get_config(authenticated: bool = Depends(verify_auth)):
    """Get current configuration."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")
    try:
        return api_instance.get_config()
    except Exception as e:
        api_instance.logger.exception(f"Error getting config: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.put("/api/config/{section}/{option}")
async def update_config(
    section: str, option: str, value: str, authenticated: bool = Depends(verify_auth)
):
    """Update configuration value."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")

    # Validate input
    if not section or not option:
        raise HTTPException(status_code=400, detail="Section and option are required")

    try:
        success = api_instance.update_config(section, option, value)
        if not success:
            raise HTTPException(
                status_code=400, detail="Failed to update configuration"
            )
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        api_instance.logger.exception(f"Error updating config: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/commands")
async def execute_command(
    request: CommandRequest, authenticated: bool = Depends(verify_auth)
):
    """Execute a watcher command."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")

    try:
        result = api_instance.execute_command(request.command, request.args)
        if result["status"] == "error":
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        api_instance.logger.exception(f"Error executing command: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """WebSocket endpoint for real-time status updates."""
    if not api_instance:
        await websocket.close(code=1011)  # Internal error
        return

    # Simple authentication via query parameter
    api_key = websocket.query_params.get("api_key")
    if not api_key or api_key != authenticator.get_api_key():
        await websocket.close(code=1008)  # Policy violation
        return

    await websocket.accept()

    # Add to active connections
    with api_instance._connections_lock:
        api_instance._active_connections.append(websocket)

    try:
        # Send initial status
        status = api_instance.get_status()
        await websocket.send_json(
            {"type": "status_update", "data": status.model_dump()}
        )

        # Keep connection alive and listen for client messages
        while True:
            # Wait for client messages or timeout
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Handle any client messages if needed
                try:
                    message = json.loads(data)
                    if message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except json.JSONDecodeError:
                    pass  # Ignore invalid JSON
            except asyncio.TimeoutError:
                # Send periodic status updates
                try:
                    status = api_instance.get_status()
                    await websocket.send_json(
                        {"type": "status_update", "data": status.model_dump()}
                    )
                except Exception as e:
                    api_instance.logger.exception(f"Error sending status update: {e}")
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        api_instance.logger.exception(f"WebSocket error: {e}")
    finally:
        # Remove from active connections
        with api_instance._connections_lock:
            try:
                if websocket in api_instance._active_connections:
                    api_instance._active_connections.remove(websocket)
            except ValueError:
                pass  # Already removed


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "GengoWatcher API",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "/api/status",
        "api_key_required": True,
    }


@app.get("/api/auth/key")
async def get_api_key():
    """Get API key for frontend authentication (development only)."""
    # Only allow in development mode
    dev_mode = os.getenv("GENGOWATCHER_DEV_MODE", "false").lower() == "true"
    if not dev_mode:
        raise HTTPException(
            status_code=403,
            detail="This endpoint is only available in development mode",
        )

    return {
        "api_key": authenticator.get_api_key(),
        "warning": "This endpoint should be disabled in production",
    }


@app.get("/api/stats")
async def get_stats(authenticated: bool = Depends(verify_auth)):
    """Get application statistics."""
    if not api_instance:
        raise HTTPException(status_code=503, detail="API not initialized")

    try:
        status = api_instance.get_status()
        jobs_result = api_instance.get_recent_jobs(limit=1000)  # Get all for stats

        total_jobs = jobs_result["pagination"]["total"]
        jobs = jobs_result["jobs"]

        # Calculate statistics
        total_value = sum(job.reward for job in jobs)
        avg_reward = total_value / total_jobs if total_jobs > 0 else 0

        source_counts = {}
        for job in jobs:
            source_counts[job.source] = source_counts.get(job.source, 0) + 1

        return {
            "total_jobs": total_jobs,
            "total_value": round(total_value, 2),
            "average_reward": round(avg_reward, 2),
            "jobs_by_source": source_counts,
            "session_stats": status.session_stats,
            "uptime": status.session_stats.get("uptime", 0),
        }
    except Exception as e:
        api_instance.logger.exception(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    if not api_instance:
        return {
            "status": "unhealthy",
            "detail": "API not initialized",
            "timestamp": time.time(),
        }

    try:
        status = api_instance.get_status()
        return {
            "status": "healthy",
            "watcher_running": status.is_running,
            "websocket_status": status.websocket_status,
            "timestamp": time.time(),
        }
    except Exception as e:
        api_instance.logger.exception(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "detail": "Internal error",
            "timestamp": time.time(),
        }


@app.get("/web/{path:path}")
async def serve_react_app(path: str):
    """Serve React app for any unmatched /web routes."""
    index_path = os.path.join(static_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        raise HTTPException(status_code=404, detail="React app not built yet")


def run_web_server(host: str = "127.0.0.1", port: int = 8000):
    """Run the web server."""
    uvicorn.run(
        "gengowatcher.web:app", host=host, port=port, reload=False, log_level="info"
    )


if __name__ == "__main__":
    run_web_server()
