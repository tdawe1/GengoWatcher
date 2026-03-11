from __future__ import annotations

import shutil
from pathlib import Path


class BrowserProfileManager:
    _SINGLETON_PREFIX = "Singleton"

    def __init__(self, profile_path: Path, seed_profile: Path | None = None):
        self.profile_path = Path(profile_path)
        self.seed_profile = Path(seed_profile) if seed_profile else None

    def ensure_ready(self) -> Path:
        if self.profile_path.exists():
            if not self.profile_path.is_dir():
                raise ValueError(
                    f"browser profile path exists but is not a directory: {self.profile_path}"
                )
            self._remove_singleton_artifacts()
            return self.profile_path

        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
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
            shutil.copytree(
                self.seed_profile,
                self.profile_path,
                ignore=self._ignore_seed_entries,
            )
        else:
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            self.profile_path.mkdir(parents=True, exist_ok=True)
        self._remove_singleton_artifacts()
        return self.profile_path

    def _ignore_seed_entries(self, directory: str, entries: list[str]) -> list[str]:
        if self.seed_profile is None or Path(directory) != self.seed_profile:
            return []
        return [
            entry for entry in entries if entry.startswith(self._SINGLETON_PREFIX)
        ]

    def _remove_singleton_artifacts(self) -> None:
        for artifact in self.profile_path.glob(f"{self._SINGLETON_PREFIX}*"):
            if artifact.is_dir() and not artifact.is_symlink():
                shutil.rmtree(artifact)
                continue
            artifact.unlink(missing_ok=True)
