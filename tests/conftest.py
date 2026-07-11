import sys
import logging
import collections
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gengowatcher.config import AppConfig
from gengowatcher.state import AppState

# Add src to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


@pytest.fixture
def mock_logger():
    """Create a mock logger for testing."""
    logger = logging.getLogger("test")
    logger.setLevel(logging.DEBUG)
    return logger


@pytest.fixture
def mock_config():
    """Create a mock AppConfig with common defaults."""
    config = MagicMock(spec=AppConfig)

    config_data = {
        "Watcher": {
            "min_reward": 0.0,
            "use_custom_user_agent": False,
            "feed_url": "https://example.com/feed",
            "check_interval": 31,
            "enable_notifications": True,
        },
        "Paths": {
            "browser_path": "",
            "browser_args": "{url}",
        },
        "Network": {
            "user_agent_email": "test@example.com",
        },
        "Logging": {
            "log_all_entries_enabled": False,
        },
        "AutoAccept": {
            "enabled": False,
            "job_sources": "rss,websocket",
            "min_reward": 0.0,
            "max_reward": 999999.0,
        },
        "WebSocket": {
            "enable_websocket": True,
            "user_id": 12345,
            "user_session": "fake_session_token",
            "user_key": "fake_user_key",
        },
        "Captcha": {
            "service": "2captcha",
            "enable_browser_automation_fallback": False,
        },
        "EmailMonitor": {
            "enabled": False,
            "email": "test@gmail.com",
            "poll_interval": 30,
        },
        "WebsiteMonitor": {
            "enabled": False,
            "jobs_url": "https://example.com/jobs",
            "check_interval_min": 30,
            "check_interval_max": 60,
            "headless": True,
        },
    }

    def get_side_effect(section, key, **kwargs):
        fallback = kwargs.get("fallback", None)
        return config_data.get(section, {}).get(key, fallback)

    config.get.side_effect = get_side_effect
    config.config = config_data

    # Support getint/getboolean/getfloat
    config.getint.side_effect = lambda s, k, **kw: int(get_side_effect(s, k, **kw) or 0)
    config.getboolean.side_effect = lambda s, k, **kw: bool(get_side_effect(s, k, **kw))
    config.getfloat.side_effect = lambda s, k, **kw: float(
        get_side_effect(s, k, **kw) or 0.0
    )

    return config


@pytest.fixture
def mock_state():
    """Create a mock AppState with common defaults."""
    state = MagicMock(spec=AppState)
    state.seen_job_ids = collections.deque(maxlen=50)
    state.accepted_jobs = []
    state.failed_jobs = []
    state.total_new_entries_found = 0
    state.total_jobs_accepted = 0
    state.total_value_found = 0.0
    return state


@pytest.fixture
def test_dir(tmp_path):
    """Fixture to create a temporary working directory for tests."""
    import os

    original_cwd = Path.cwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(original_cwd)
