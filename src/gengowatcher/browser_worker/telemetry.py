from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import time
from typing import Any


@dataclass(slots=True)
class TimingEvent:
    name: str
    monotonic_ms: float
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "monotonic_ms": self.monotonic_ms,
        }
        if self.details:
            payload["details"] = dict(self.details)
        return payload


class BrowserWorkerTelemetry:
    def __init__(self, log_path: Path):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: TimingEvent, **extra: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "recorded_at": time.time(),
            "event": event.to_dict(),
        }
        payload.update(extra)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return payload

    def write_text_artifact(self, name: str, content: str) -> Path:
        artifact_path = self.log_path.parent / name
        artifact_path.write_text(content, encoding="utf-8")
        return artifact_path
