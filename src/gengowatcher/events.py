"""Canonical event model for GengoWatcher."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional
import uuid


class EventType(str, Enum):
    # Browser observation events
    BROWSER_WORKBENCH_VISIBLE = "browser.workbench.visible"
    BROWSER_WORKBENCH_DETAILS = "browser.workbench.details"
    BROWSER_WORKBENCH_START_RESPONSE = "browser.workbench.start_response"
    BROWSER_WORKBENCH_STATUS = "browser.workbench.status"
    BROWSER_WORKBENCH_FILE_SEEN = "browser.workbench.file_seen"
    BROWSER_CHALLENGE_REQUIRED = "browser.challenge.required"
    BROWSER_NAVIGATION = "browser.navigation"

    # Job lifecycle events
    JOB_ACCEPTED = "job.accepted"
    JOB_VISIBLE = "job.visible"
    JOB_DETAILS = "job.details"
    JOB_STATUS = "job.status"
    JOB_FILE_PENDING = "job.file_pending"
    JOB_FILE_READY = "job.file_ready"

    # Command events
    COMMAND_STARTED = "command.started"
    COMMAND_COMPLETED = "command.completed"
    COMMAND_FAILED = "command.failed"
    USER_ACTION_REQUIRED = "browser.user_action.required"


@dataclass
class EventEnvelope:
    """Standard event envelope."""

    type: str
    source: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    observed_at: float = field(default_factory=time.time)
    payload: dict[str, Any] = field(default_factory=dict)
    collection_id: Optional[str] = None
    order_id: Optional[str] = None
    job_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventEnvelope:
        return cls(**data)