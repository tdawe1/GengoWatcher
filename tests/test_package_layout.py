from pathlib import Path


def test_watcher_implementations_live_in_orchestration_package():
    package_root = Path(__file__).resolve().parents[1] / "src" / "gengowatcher"
    root_watcher_modules = sorted(
        path.name for path in package_root.glob("watcher_*.py")
    )
    orchestration_modules = sorted(
        path.name
        for path in (package_root / "orchestration").glob("watcher_*.py")
    )

    assert root_watcher_modules == [
        "watcher_debug.py",
        "watcher_health.py",
        "watcher_job_metadata.py",
    ]
    assert "watcher_job_processor.py" in orchestration_modules
    assert "watcher_ws_logic.py" in orchestration_modules
    assert "watcher_session_sync.py" in orchestration_modules
