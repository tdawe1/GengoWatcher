from pathlib import Path

import pytest

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


def test_profile_manager_strips_singleton_artifacts_from_seed_profile(tmp_path: Path):
    source = tmp_path / "seed"
    target = tmp_path / "worker"
    source.mkdir()
    (source / "Cookies").write_text("seed", encoding="utf-8")
    (source / "SingletonLock").write_text("stale", encoding="utf-8")
    (source / "SingletonCookie").write_text("stale", encoding="utf-8")

    manager = BrowserProfileManager(target, seed_profile=source)
    manager.ensure_ready()

    assert (target / "Cookies").read_text(encoding="utf-8") == "seed"
    assert (target / "SingletonLock").exists() is False
    assert (target / "SingletonCookie").exists() is False


def test_profile_manager_strips_singleton_artifacts_from_existing_profile(
    tmp_path: Path,
):
    target = tmp_path / "worker"
    target.mkdir()
    (target / "Cookies").write_text("worker", encoding="utf-8")
    (target / "SingletonLock").write_text("stale", encoding="utf-8")
    (target / "SingletonSocket").write_text("stale", encoding="utf-8")

    manager = BrowserProfileManager(target)
    manager.ensure_ready()

    assert (target / "Cookies").read_text(encoding="utf-8") == "worker"
    assert (target / "SingletonLock").exists() is False
    assert (target / "SingletonSocket").exists() is False


def test_profile_manager_rejects_profile_path_that_is_a_file(tmp_path: Path):
    target = tmp_path / "worker"
    target.write_text("not-a-dir", encoding="utf-8")

    manager = BrowserProfileManager(target)

    with pytest.raises(ValueError, match="not a directory"):
        manager.ensure_ready()


def test_profile_manager_rejects_missing_seed_profile(tmp_path: Path):
    manager = BrowserProfileManager(
        tmp_path / "worker",
        seed_profile=tmp_path / "missing-seed",
    )

    with pytest.raises(ValueError, match="does not exist"):
        manager.ensure_ready()


def test_profile_manager_rejects_seed_profile_file(tmp_path: Path):
    seed = tmp_path / "seed"
    seed.write_text("not-a-dir", encoding="utf-8")

    manager = BrowserProfileManager(tmp_path / "worker", seed_profile=seed)

    with pytest.raises(ValueError, match="not a directory"):
        manager.ensure_ready()
