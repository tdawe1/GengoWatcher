import pytest
import os
import configparser
from pathlib import Path

from unittest.mock import patch

from gengowatcher.config import AppConfig


@pytest.fixture
def test_dir(tmp_path):
    """Fixture to create a temporary working directory for tests."""
    original_cwd = Path.cwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(original_cwd)


def test_config_creates_default_file(test_dir):
    """Test that AppConfig creates a default config.ini if one doesn't exist."""
    config_file = test_dir / "config.ini"
    assert not config_file.is_file()

    with patch("sys.exit") as mock_exit:
        AppConfig()
        assert config_file.is_file()
        mock_exit.assert_called_once_with(0)


def test_config_loads_default_values(test_dir):
    """Test that AppConfig loads default values correctly after creating a file."""
    with patch("sys.exit"):
        AppConfig()

    app_config = AppConfig()

    assert app_config.get("Watcher", "check_interval") == 31
    assert app_config.get("Watcher", "enable_notifications") is True
    assert app_config.get("Network", "user_agent_email") == "your_email@example.com"
