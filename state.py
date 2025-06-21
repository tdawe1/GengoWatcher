import json
import threading
import pathlib
import logging


class AppState:
    STATE_FILE = "state.json"

    def __init__(
        self, logger: logging.Logger, state_file_path: str | pathlib.Path | None = None
    ):
        self.logger = logger
        self._lock = threading.Lock()
        self.state_file_path = pathlib.Path(state_file_path or self.STATE_FILE)

        self.last_seen_link = None
        self.total_new_entries_found = 0

        self._load_state()

    def _load_state(self):
        try:
            if self.state_file_path.is_file():
                with open(self.state_file_path, "r", encoding="utf-8") as f:
                    state_data = json.load(f)
                    with self._lock:
                        self.last_seen_link = state_data.get("last_seen_link")
                        self.total_new_entries_found = int(
                            state_data.get("total_new_entries_found", 0)
                        )
        except (json.JSONDecodeError, IOError) as e:
            self.logger.error(f"Could not load state file. Starting fresh. Error: {e}")

    def save_state(self):
        try:
            with self._lock:
                state_data = {
                    "last_seen_link": self.last_seen_link,
                    "total_new_entries_found": self.total_new_entries_found,
                }
                with open(self.state_file_path, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, indent=4)
        except IOError as e:
            self.logger.error(f"Error saving state to {self.STATE_FILE}: {e}")
