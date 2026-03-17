from __future__ import annotations

from collections import deque
import threading

from .models import JobIntent


class JobRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: dict[str, JobIntent] = {}
        self._queue: deque[JobIntent] = deque()
        self._queued_ids: set[str] = set()

    def register(self, intent: JobIntent) -> JobIntent:
        with self._lock:
            existing = self._jobs.setdefault(intent.job_id, intent)
            return existing

    def enqueue(self, intent: JobIntent) -> bool:
        with self._lock:
            authoritative = self._jobs.setdefault(intent.job_id, intent)
            if authoritative.job_id in self._queued_ids:
                return False
            self._queue.append(authoritative)
            self._queued_ids.add(authoritative.job_id)
            return True

    def pop_next(self) -> JobIntent | None:
        with self._lock:
            if not self._queue:
                return None
            intent = self._queue.popleft()
            self._queued_ids.discard(intent.job_id)
            return intent

    def get(self, job_id: str) -> JobIntent | None:
        with self._lock:
            return self._jobs.get(job_id)
