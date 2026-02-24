import json
import os
import tempfile
import threading
import pathlib
from typing import Union, List, Dict, Any
import logging
import collections
import time
import datetime


class AppState:
    STATE_FILE = "state.json"

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
        self.seen_job_ids = collections.deque()  # Unbounded - no limit
        self._sparkline_data = []

        # Job storage for web API
        self._jobs: List[Dict[str, Any]] = []
        self._jobs_lock = threading.RLock()

        self._load_state()

    @property
    def sparkline_data(self) -> List:
        with self._lock:
            return self._sparkline_data.copy()

    @sparkline_data.setter
    def sparkline_data(self, value: List):
        with self._lock:
            self._sparkline_data = list(value)

    def _load_state(self):
        try:
            if self.state_file_path.is_file():
                with open(self.state_file_path, "r", encoding="utf-8") as f:
                    state_data = json.load(f)
                    with self._lock:
                        self.last_seen_rss_link = state_data.get("last_seen_rss_link")
                        self.last_seen_link = state_data.get("last_seen_link")
                        # Session data cleared on startup - start fresh each session
                        self.total_new_entries_found = 0
                        self.seen_job_ids.clear()
                        # Persist sparkline data across sessions
                        self._sparkline_data = state_data.get("sparkline_data", [])

                        # Load stored jobs
                        stored_jobs = state_data.get("jobs", [])
                        with self._jobs_lock:
                            self._jobs = stored_jobs
                            # Sort by timestamp descending (newest first)
                            self._jobs.sort(
                                key=lambda x: x.get("timestamp", 0), reverse=True
                            )
        except (json.JSONDecodeError, IOError) as e:
            self.logger.exception(
                f"Could not load state file. Starting fresh. Error: {e}"
            )

    def load_jobs_from_csv(self, csv_path: str):
        """Load jobs from CSV file if state is empty or user requests history."""
        import csv
        import re

        try:
            path = pathlib.Path(csv_path)
            if not path.exists():
                return

            with open(path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    return

                new_jobs = []
                for row in reader:
                    if len(row) < 4:
                        continue
                    try:
                        timestamp_str = row[0]
                        try:
                            dt = datetime.datetime.fromisoformat(timestamp_str)
                            ts = dt.timestamp()
                        except ValueError:
                            ts = time.time()

                        title = row[1]
                        # Handle "$ 12.34" or "12.34"
                        reward_str = (
                            str(row[2]).replace("$", "").replace("US", "").strip()
                        )
                        reward = float(reward_str) if reward_str else 0.0
                        url = row[3]

                        match = re.search(r"/jobs/details/(\d+)", url)
                        job_id = match.group(1) if match else f"csv_{int(ts)}"

                        job = {
                            "timestamp": ts,
                            "id": job_id,
                            "title": title,
                            "source": "History",
                            "lang_pair": (
                                title.split("|")[0].strip()
                                if "|" in title
                                else "Unknown"
                            ),
                            "reward": reward,
                            "currency": "USD",
                            "url": url,
                        }
                        new_jobs.append(job)
                    except (ValueError, IndexError):
                        continue

                with self._jobs_lock:
                    for job in new_jobs:
                        self.add_job(job)

            self.logger.info(f"Loaded {len(new_jobs)} jobs from CSV history.")
        except Exception as e:
            self.logger.error(f"Error loading jobs from CSV: {e}")

    def save_state(self):
        """Save state atomically - write to temp file then rename."""
        try:
            with self._lock:
                with self._jobs_lock:
                    state_data = {
                        "last_seen_rss_link": self.last_seen_rss_link,
                        "last_seen_link": self.last_seen_link,
                        "total_new_entries_found": self.total_new_entries_found,
                        "sparkline_data": self._sparkline_data.copy(),
                        "seen_job_ids": list(self.seen_job_ids),
                        "jobs": self._jobs.copy(),  # Store jobs in state
                    }

                # Atomic write: write to temp file, then rename
                dir_path = self.state_file_path.parent
                fd, temp_path = tempfile.mkstemp(
                    suffix=".tmp", prefix="state_", dir=dir_path
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(state_data, f, indent=4)
                    # Atomic rename (on POSIX systems)
                    os.replace(temp_path, self.state_file_path)
                except Exception:
                    # Clean up temp file on error
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
                    raise
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

            self.logger.debug(f"Added job {job_data.get('id')} to storage")

    def get_job_count(self) -> int:
        """Get total number of stored jobs."""
        with self._jobs_lock:
            return len(self._jobs)
