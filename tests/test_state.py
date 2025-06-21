import pytest
import state
import logging
import os


def pytest_configure(config):
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler()],
    )
    logging.getLogger().setLevel(logging.DEBUG)


@pytest.fixture(autouse=True)
def debug_test_start_and_end(request):
    logging.debug(f"\n--- START TEST: {request.node.name} ---")
    yield
    logging.debug(f"--- END TEST: {request.node.name} ---\n")


@pytest.fixture
def temp_state_file(tmp_path):
    """Provides a temporary file path for state tests."""
    return tmp_path / "state.json"


def test_appstate_initialization(temp_state_file):
    """Test that AppState initializes with default values."""
    assert hasattr(state, "AppState")
    app_state = state.AppState(
        logger=logging.getLogger("test"), state_file_path=temp_state_file
    )
    assert hasattr(app_state, "save_state")
    assert hasattr(app_state, "_load_state")
    assert app_state.last_seen_link is None
    assert app_state.total_new_entries_found == 0


def test_save_and_load_state(temp_state_file):
    """Test that state is correctly saved to and loaded from a file."""
    logger = logging.getLogger("test")
    app_state = state.AppState(logger=logger, state_file_path=temp_state_file)
    app_state.last_seen_link = "http://example.com/job1"
    app_state.total_new_entries_found = 42
    app_state.save_state()

    # Create a new instance to load the state from the file
    app_state2 = state.AppState(logger=logger, state_file_path=temp_state_file)
    assert app_state2.last_seen_link == "http://example.com/job1"
    assert app_state2.total_new_entries_found == 42


def test_corrupted_state_file(temp_state_file):
    """Test that the app handles a corrupted or invalid state file gracefully."""
    with open(temp_state_file, "w", encoding="utf-8") as f:
        f.write("this is not valid json")
    logger = logging.getLogger("test")
    app_state = state.AppState(logger=logger, state_file_path=temp_state_file)
    assert app_state.last_seen_link is None
    assert app_state.total_new_entries_found == 0
