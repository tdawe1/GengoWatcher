from __future__ import annotations

import shutil
from pathlib import Path


class BrowserProfileManager:
    def __init__(self, profile_path: Path, seed_profile: Path | None = None):
        self.profile_path = Path(profile_path)
        self.seed_profile = Path(seed_profile) if seed_profile else None

    def ensure_ready(self) -> Path:
        if self.profile_path.exists():
            return self.profile_path

        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        if self.seed_profile:
            shutil.copytree(self.seed_profile, self.profile_path)
        else:
            self.profile_path.mkdir(parents=True, exist_ok=True)
        return self.profile_path
