from __future__ import annotations

import threading


class AcceptanceCoordinator:
    def __init__(self):
        self._lock = threading.Lock()
        self._busy = False

    def acquire(self) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            return True

    def release(self) -> None:
        with self._lock:
            self._busy = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy
