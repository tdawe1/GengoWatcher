from __future__ import annotations

import shutil
from pathlib import Path


class BrowserProfileManager:
    def __init__(self, profile_path: Path, seed_profile: Path | None = None):
        self.profile_path = Path(profile_path)
        self.seed_profile = Path(seed_profile) if seed_profile else None

    def ensure_ready(self) -> Path:
        if self.profile_path.exists():
            if not self.profile_path.is_dir():
                raise ValueError(
                    f"browser profile path exists but is not a directory: {self.profile_path}"
                )
            return self.profile_path

        if self.seed_profile:
            if not self.seed_profile.exists():
                raise ValueError(
                    f"seed profile does not exist: {self.seed_profile}"
                )
            if not self.seed_profile.is_dir():
                raise ValueError(
                    f"seed profile is not a directory: {self.seed_profile}"
                )
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.seed_profile, self.profile_path)
        else:
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            self.profile_path.mkdir(parents=True, exist_ok=True)
        return self.profile_path
