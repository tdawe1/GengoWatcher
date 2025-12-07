import json
import threading
import pathlib
from typing import Union, List, Dict, Any
import logging
import collections


class AppState:
    STATE_FILE = "state.json"
    MAX_STORED_JOBS = 1000  # Maximum number of jobs to store

    def __init__(
        self,
        logger: logging.Logger,
        state_file_path: Union[str, pathlib.Path, None] = None,
    ):
        self.logger = logger
        self._lock = threading.RLock()  # Reentrant lock for better safety
        self.state_file_path = pathlib.Path(state_file_path or self.STATE_FILE)

        self.last_seen_rss_link = None  # New variable for RSS tracking
        self.last_seen_link = None  # General last job (for display, optional)
        self.total_new_entries_found = 0
        self.seen_job_ids = collections.deque(maxlen=50)

        # Job storage for web API
        self._jobs: List[Dict[str, Any]] = []
        self._jobs_lock = threading.RLock()

        self._load_state()

    def _load_state(self):
        try:
            if self.state_file_path.is_file():
                with open(self.state_file_path, "r", encoding="utf-8") as f:
                    state_data = json.load(f)
                    with self._lock:
                        self.last_seen_rss_link = state_data.get("last_seen_rss_link")
                        self.last_seen_link = state_data.get("last_seen_link")
                        self.total_new_entries_found = int(
                            state_data.get("total_new_entries_found", 0)
                        )
                        loaded_ids = state_data.get("seen_job_ids", [])
                        self.seen_job_ids.clear()
                        self.seen_job_ids.extend(loaded_ids)

                        # Load stored jobs
                        stored_jobs = state_data.get("jobs", [])
                        with self._jobs_lock:
                            self._jobs = stored_jobs
                            # Sort by timestamp descending (newest first)
                            self._jobs.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.exception(f"Could not load state file. Starting fresh. Error: {e}")

    def save_state(self):
        try:
            with self._lock:
                with self._jobs_lock:
                    state_data = {
                        "last_seen_rss_link": self.last_seen_rss_link,
                        "last_seen_link": self.last_seen_link,
                        "total_new_entries_found": self.total_new_entries_found,
                        "seen_job_ids": list(self.seen_job_ids),
                        "jobs": self._jobs.copy(),  # Store jobs in state
                    }
                with open(self.state_file_path, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, indent=4)
        except IOError as e:
            self.logger.exception(f"Error saving state to {self.STATE_FILE}: {e}")

    def get_recent_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent jobs from storage."""
        with self._jobs_lock:
            return self._jobs[:limit]

    def add_job(self, job_data: Dict[str, Any]):
        """Add a new job to storage."""
        with self._jobs_lock:
            # Check if job already exists
            existing_job_ids = {job.get("id") for job in self._jobs}
            if job_data.get("id") in existing_job_ids:
                return  # Job already exists

            # Add new job
            self._jobs.insert(0, job_data)  # Add to beginning for newest first

            # Maintain maximum size
            if len(self._jobs) > self.MAX_STORED_JOBS:
                self._jobs = self._jobs[:self.MAX_STORED_JOBS]

            self.logger.debug(f"Added job {job_data.get('id')} to storage")

    def get_job_count(self) -> int:
        """Get total number of stored jobs."""
        with self._jobs_lock:
            return len(self._jobs)

