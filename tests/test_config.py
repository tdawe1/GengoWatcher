import os
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from gengowatcher.config import AppConfig


@pytest.fixture
def test_dir(tmp_path):
    """Fixture to create a temporary working directory for tests."""
    original_cwd = Path.cwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(original_cwd)


def test_config_creates_default_file(test_dir):
    """Test that AppConfig creates a default config.toml if one doesn't exist."""
    config_file = test_dir / "config.toml"
    assert not config_file.is_file()

    with patch("sys.exit") as mock_exit:
        AppConfig()
        assert config_file.is_file()
        mock_exit.assert_not_called()


def test_config_loads_default_values(test_dir):
    """Test that AppConfig loads default values correctly after creating a file."""
    with patch("sys.exit"):
        AppConfig()

    app_config = AppConfig()

    assert app_config.get("Watcher", "check_interval") == 31
    assert app_config.get("Watcher", "enable_notifications") is True
    assert app_config.get("Network", "user_agent_email") == ""
    assert app_config.get("Paths", "websocket_stale_sound_file") == ""
    assert app_config.get("UI", "theme_name") == "nord"

    assert app_config.get("WebSocket", "enable_websocket") is True
    assert app_config.get("WebSocket", "user_id") == 0
    assert (
        app_config.get("WebSocket", "user_session") == "REPLACE_WITH_YOUR_SESSION_TOKEN"
    )
    assert app_config.get("WebSocket", "user_key") == "REPLACE_WITH_YOUR_USER_KEY"
    assert app_config.get("Metrics", "enabled") is False
    assert app_config.get("Metrics", "host") == "127.0.0.1"
    assert app_config.get("Metrics", "port") == 9091


def test_save_config_uses_sidecar_lock_file(test_dir):
    """Test that save_config locks a sidecar file so atomic replace works on Windows."""
    with patch("sys.exit"):
        app_config = AppConfig()

    app_config.set("Watcher", "check_interval", 42)

    real_open = open
    open_calls = []

    def tracking_open(file, mode="r", *args, **kwargs):
        open_calls.append((str(file), mode))
        return real_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=tracking_open):
        app_config.save_config()

    assert ("config.toml.lock", "a+") in open_calls
    assert ("config.toml", "a+") not in open_calls


def test_default_list_values_are_stored_as_toml_arrays(test_dir):
    """Default list values should be serialized as TOML arrays in config.toml."""
    with patch("sys.exit"):
        AppConfig()

    with open(test_dir / "config.toml", "rb") as handle:
        parsed = tomllib.load(handle)

    assert (
        parsed["WebServer"]["cors_origins"]
        == AppConfig.DEFAULT_CONFIG["WebServer"]["cors_origins"]
    )


def test_missing_list_option_is_repaired_using_toml_array(test_dir):
    """Repairing a missing list option should restore a TOML array value."""
    with patch("sys.exit"):
        AppConfig()

    config_file = test_dir / "config.toml"
    config_file.write_text(
        """
[Watcher]
check_interval = 31

[WebServer]
enabled = false
host = "127.0.0.1"
port = 8000
auth_token = "REPLACE_WITH_YOUR_WEB_API_TOKEN"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with patch("sys.exit"):
        AppConfig()

    with open(config_file, "rb") as handle:
        repaired = tomllib.load(handle)

    assert (
        repaired["WebServer"]["cors_origins"]
        == AppConfig.DEFAULT_CONFIG["WebServer"]["cors_origins"]
    )


def test_missing_metrics_section_is_repaired_with_defaults(test_dir):
    """Repairing config should restore the Metrics section with default values."""
    with patch("sys.exit"):
        AppConfig()

    config_file = test_dir / "config.toml"
    config_file.write_text(
        """
[Watcher]
check_interval = 31
feed_url = "https://example.com/feed"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with patch("sys.exit"):
        repaired_config = AppConfig()

    assert repaired_config.get("Metrics", "enabled") is False
    assert repaired_config.get("Metrics", "host") == "127.0.0.1"
    assert repaired_config.get("Metrics", "port") == 9091


def test_get_returns_fallback_for_missing_keys(test_dir):
    """Missing values should honor the explicit fallback."""
    with patch("sys.exit"):
        app_config = AppConfig()

    assert (
        app_config.get("Watcher", "does_not_exist", fallback="fallback") == "fallback"
    )
