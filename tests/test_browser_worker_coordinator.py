from gengowatcher.browser_worker.coordinator import AcceptanceCoordinator


def test_only_one_acceptance_routine_can_run_at_once():
    coordinator = AcceptanceCoordinator()

    assert coordinator.acquire() is True
    assert coordinator.acquire() is False


def test_coordinator_can_release_lock():
    coordinator = AcceptanceCoordinator()

    assert coordinator.acquire() is True
    coordinator.release()

    assert coordinator.acquire() is True
