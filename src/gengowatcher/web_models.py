from __future__ import annotations

import secrets
from typing import Any, Dict, List, Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

security = HTTPBearer(auto_error=False)


class APIAuthenticator:
    """Simple API key authentication for web API."""

    def __init__(self, api_key: str = None):
        """Initialize the API authenticator."""
        self.api_key = api_key or secrets.token_urlsafe(32)

    def authenticate(
        self, credentials: HTTPAuthorizationCredentials = Depends(security)
    ) -> bool:
        """Authenticate API request using Bearer token."""
        if not credentials:
            return False
        supplied = str(credentials.credentials or "")
        expected = str(self.api_key or "")
        return secrets.compare_digest(supplied, expected)

    def get_api_key(self) -> str:
        """Get the current API key."""
        return self.api_key


class JobEntry(BaseModel):
    id: str
    title: str
    reward: float
    currency: str = "USD"
    url: str
    timestamp: float
    source: str

    @field_validator("id", "title", "url", "source")
    @classmethod
    def validate_string_fields(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Field must be a non-empty string")
        return value.strip()

    @field_validator("reward")
    @classmethod
    def validate_reward(cls, value):
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError("Reward must be a non-negative number")
        return float(value)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value):
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError("Timestamp must be a valid positive number")
        return float(value)


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
    def validate_status_fields(cls, value):
        if not isinstance(value, str):
            raise ValueError("Status must be a string")
        return value.strip()


class ConfigSection(BaseModel):
    section: str
    options: Dict[str, Any]

    @field_validator("section")
    @classmethod
    def validate_section(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Section must be a non-empty string")
        return value.strip()


class CommandRequest(BaseModel):
    command: str
    args: Optional[List[str]] = []

    @field_validator("command")
    @classmethod
    def validate_command(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Command must be a non-empty string")
        allowed_commands = ["check", "pause", "resume", "cancel", "ping", "notify"]
        if value.strip().lower() not in allowed_commands:
            raise ValueError(f"Command must be one of: {', '.join(allowed_commands)}")
        return value.strip().lower()

    @field_validator("args")
    @classmethod
    def validate_args(cls, value):
        if value is not None:
            if not isinstance(value, list):
                raise ValueError("Args must be a list or None")
            for arg in value:
                if not isinstance(arg, str):
                    raise ValueError("All args must be strings")
        return value


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("page", "limit")
    @classmethod
    def validate_pagination(cls, value, info):
        field_name = info.field_name
        if not isinstance(value, int) or value < 1:
            raise ValueError(f"{field_name} must be a positive integer")
        if field_name == "limit" and value > 100:
            raise ValueError("Limit cannot exceed 100")
        return value
