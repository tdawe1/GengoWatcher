from pathlib import Path

from gengowatcher.browser_worker.profile import BrowserProfileManager


def test_profile_manager_uses_seed_profile_once(tmp_path: Path):
    source = tmp_path / "seed"
    target = tmp_path / "worker"
    source.mkdir()
    (source / "Cookies").write_text("seed", encoding="utf-8")

    manager = BrowserProfileManager(target, seed_profile=source)
    manager.ensure_ready()

    assert (target / "Cookies").read_text(encoding="utf-8") == "seed"


def test_profile_manager_does_not_reseed_existing_profile(tmp_path: Path):
    source = tmp_path / "seed"
    target = tmp_path / "worker"
    source.mkdir()
    target.mkdir()
    (source / "Cookies").write_text("seed", encoding="utf-8")
    (target / "Cookies").write_text("worker", encoding="utf-8")

    manager = BrowserProfileManager(target, seed_profile=source)
    manager.ensure_ready()

    assert (target / "Cookies").read_text(encoding="utf-8") == "worker"
