"""Tests for scripts/test_high_value_setup.py."""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import tempfile
import asyncio

# Add scripts to path
scripts_path = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_path))

from test_high_value_setup import (
    test_configuration,
    test_high_value_manager,
    show_setup_instructions,
    main,
)


@pytest.fixture
def mock_config_file(tmp_path):
    """Create a temporary config file for testing."""
    config_file = tmp_path / "config_high_value.ini"
    config_file.write_text(
        """[Watcher]
feed_url = https://gengo.com/rss/available_jobs/TEST_RSS_KEY

[WebSocket]
user_id = 12345
user_session = test_session_token_12345678
user_key = test_user_key_12345678

[HighValue]
threshold = 500.0
very_high_threshold = 1000.0
extreme_threshold = 5000.0
max_per_day = 3
min_interval_seconds = 21600

[Captcha]
service = 2captcha
api_key = test_api_key_12345678
"""
    )
    return config_file


class TestConfigurationChecks:
    """Test configuration validation functions."""

    def test_configuration_with_valid_config(self, mock_config_file, monkeypatch):
        """Test configuration validation with a valid config file."""
        monkeypatch.chdir(mock_config_file.parent)

        # Mock AppConfig to load our test config
        mock_config_class = MagicMock()
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        def mock_get(section, key):
            config_values = {
                ("Watcher", "feed_url"): "https://gengo.com/rss/available_jobs/TEST_RSS_KEY",
                ("WebSocket", "user_id"): 12345,
                ("WebSocket", "user_session"): "test_session_token_12345678",
                ("WebSocket", "user_key"): "test_user_key_12345678",
                ("HighValue", "threshold"): "500.0",
                ("HighValue", "very_high_threshold"): "1000.0",
                ("HighValue", "extreme_threshold"): "5000.0",
                ("HighValue", "max_per_day"): "3",
                ("HighValue", "min_interval_seconds"): "21600",
                ("Captcha", "service"): "2captcha",
                ("Captcha", "api_key"): "test_api_key_12345678",
            }
            return config_values.get((section, key), "")

        mock_config.get.side_effect = mock_get

        with patch("test_high_value_setup.AppConfig", mock_config_class):
            result = test_configuration()

        assert result is True

    def test_configuration_missing_file(self, tmp_path, monkeypatch):
        """Test configuration validation when config file is missing."""
        monkeypatch.chdir(tmp_path)
        result = test_configuration()
        assert result is False

    def test_configuration_with_placeholder_values(self, tmp_path, monkeypatch):
        """Test configuration validation with placeholder values."""
        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text(
            """[Watcher]
feed_url = https://gengo.com/rss/available_jobs/YOUR_RSS_KEY_HERE

[WebSocket]
user_id = 0
user_session = YOUR_SESSION_TOKEN
user_key = YOUR_USER_KEY
"""
        )
        monkeypatch.chdir(tmp_path)

        mock_config_class = MagicMock()
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        def mock_get(section, key):
            config_values = {
                ("Watcher", "feed_url"): "https://gengo.com/rss/available_jobs/YOUR_RSS_KEY_HERE",
                ("WebSocket", "user_id"): 0,
                ("WebSocket", "user_session"): "YOUR_SESSION_TOKEN",
                ("WebSocket", "user_key"): "YOUR_USER_KEY",
                ("HighValue", "threshold"): "500.0",
                ("HighValue", "very_high_threshold"): "1000.0",
                ("HighValue", "extreme_threshold"): "5000.0",
                ("Captcha", "service"): "",
                ("Captcha", "api_key"): "YOUR_2CAPTCHA_API_KEY",
            }
            return config_values.get((section, key), "")

        mock_config.get.side_effect = mock_get

        with patch("test_high_value_setup.AppConfig", mock_config_class):
            # Should still return True but with warnings
            result = test_configuration()

        # The function prints warnings but still returns True after loading config
        assert result is True

    def test_configuration_invalid_config(self, tmp_path, monkeypatch):
        """Test configuration validation with invalid config that raises exception."""
        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text("INVALID CONFIG DATA")
        monkeypatch.chdir(tmp_path)

        mock_config_class = MagicMock()
        mock_config_class.return_value.load_config.side_effect = Exception(
            "Invalid config"
        )

        with patch("test_high_value_setup.AppConfig", mock_config_class):
            result = test_configuration()

        assert result is False


class TestHighValueManager:
    """Test high value manager functionality."""

    @pytest.mark.asyncio
    async def test_high_value_manager_initialization(self, mock_config_file, monkeypatch):
        """Test that HighValueJobManager can be initialized."""
        monkeypatch.chdir(mock_config_file.parent)

        mock_config_class = MagicMock()
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        def mock_get(section, key):
            config_values = {
                ("HighValue", "threshold"): "500.0",
                ("HighValue", "very_high_threshold"): "1000.0",
                ("HighValue", "extreme_threshold"): "5000.0",
                ("HighValue", "max_per_day"): "3",
                ("HighValue", "min_interval_seconds"): "21600",
            }
            return config_values.get((section, key), "")

        mock_config.get.side_effect = mock_get

        mock_manager_class = MagicMock()
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager

        # Mock is_high_value to return appropriate values
        def mock_is_high_value(reward):
            if reward >= 5000:
                return (True, "EXTREME")
            elif reward >= 1000:
                return (True, "VERY_HIGH")
            elif reward >= 500:
                return (True, "HIGH")
            return (False, "STANDARD")

        mock_manager.is_high_value.side_effect = mock_is_high_value

        mock_manager.get_stats.return_value = {
            "thresholds": {"high": 500.0, "very_high": 1000.0, "extreme": 5000.0},
            "jobs_accepted_today": 0,
            "max_per_day": 3,
        }

        with patch("test_high_value_setup.AppConfig", mock_config_class):
            with patch(
                "test_high_value_setup.HighValueJobManager", mock_manager_class
            ):
                result = await test_high_value_manager()

        assert result is True

    @pytest.mark.asyncio
    async def test_high_value_manager_with_exception(self, tmp_path, monkeypatch):
        """Test high value manager handling exceptions."""
        monkeypatch.chdir(tmp_path)

        mock_config_class = MagicMock()
        mock_config_class.return_value.load_config.side_effect = Exception(
            "Config error"
        )

        with patch("test_high_value_setup.AppConfig", mock_config_class):
            result = await test_high_value_manager()

        assert result is False


class TestSetupInstructions:
    """Test setup instructions display."""

    def test_show_setup_instructions(self, capsys):
        """Test that setup instructions are printed correctly."""
        show_setup_instructions()

        captured = capsys.readouterr()
        output = captured.out

        # Verify key sections are present
        assert "HIGH-VALUE JOB SETUP INSTRUCTIONS" in output
        assert "CONFIGURATION:" in output
        assert "RSS FEED:" in output
        assert "WEBSOCKET:" in output
        assert "RUNNING:" in output
        assert "SAFETY LIMITS:" in output
        assert "NOTIFICATIONS:" in output

        # Verify specific details
        assert "config_high_value.ini" in output
        assert "gengo.com" in output
        assert "3 high-value jobs per day" in output


class TestMainFunction:
    """Test main execution flow."""

    def test_main_success_flow(self, mock_config_file, monkeypatch):
        """Test successful execution of main function."""
        monkeypatch.chdir(mock_config_file.parent)

        mock_config_class = MagicMock()
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        def mock_get(section, key):
            config_values = {
                ("Watcher", "feed_url"): "https://gengo.com/rss/available_jobs/TEST_RSS_KEY",
                ("WebSocket", "user_id"): 12345,
                ("WebSocket", "user_session"): "test_session_token",
                ("WebSocket", "user_key"): "test_user_key",
                ("HighValue", "threshold"): "500.0",
                ("HighValue", "very_high_threshold"): "1000.0",
                ("HighValue", "extreme_threshold"): "5000.0",
                ("HighValue", "max_per_day"): "3",
                ("HighValue", "min_interval_seconds"): "21600",
                ("Captcha", "service"): "2captcha",
                ("Captcha", "api_key"): "test_api_key",
            }
            return config_values.get((section, key), "")

        mock_config.get.side_effect = mock_get

        mock_manager_class = MagicMock()
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager
        mock_manager.is_high_value.return_value = (True, "HIGH")
        mock_manager.get_stats.return_value = {
            "thresholds": {"high": 500.0},
            "jobs_accepted_today": 0,
        }

        with patch("test_high_value_setup.AppConfig", mock_config_class):
            with patch(
                "test_high_value_setup.HighValueJobManager", mock_manager_class
            ):
                with patch("test_high_value_setup.asyncio.run") as mock_run:
                    mock_run.return_value = True
                    main()

    def test_main_config_failure(self, tmp_path, monkeypatch, capsys):
        """Test main function when configuration fails."""
        monkeypatch.chdir(tmp_path)

        with patch("test_high_value_setup.test_configuration") as mock_test_config:
            mock_test_config.return_value = False
            main()

        captured = capsys.readouterr()
        assert "Configuration test failed" in captured.out

    def test_main_manager_failure(self, mock_config_file, monkeypatch, capsys):
        """Test main function when manager test fails."""
        monkeypatch.chdir(mock_config_file.parent)

        with patch("test_high_value_setup.test_configuration") as mock_test_config:
            with patch("test_high_value_setup.asyncio.run") as mock_run:
                mock_test_config.return_value = True
                mock_run.return_value = False
                main()

        captured = capsys.readouterr()
        assert "Manager test failed" in captured.out


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_configuration_with_empty_strings(self, tmp_path, monkeypatch):
        """Test configuration with empty string values."""
        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text(
            """[Watcher]
feed_url =

[WebSocket]
user_id = 0
user_session =
user_key =
"""
        )
        monkeypatch.chdir(tmp_path)

        mock_config_class = MagicMock()
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        def mock_get(section, key):
            return ""

        mock_config.get.side_effect = mock_get

        with patch("test_high_value_setup.AppConfig", mock_config_class):
            # Should handle empty strings gracefully
            result = test_configuration()

        # Will return True but with warnings about missing values
        assert result is True

    @pytest.mark.asyncio
    async def test_high_value_thresholds_boundary(self, mock_config_file, monkeypatch):
        """Test high value manager with boundary threshold values."""
        monkeypatch.chdir(mock_config_file.parent)

        mock_config_class = MagicMock()
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        def mock_get(section, key):
            config_values = {
                ("HighValue", "threshold"): "0.01",  # Very low threshold
                ("HighValue", "very_high_threshold"): "0.02",
                ("HighValue", "extreme_threshold"): "0.03",
                ("HighValue", "max_per_day"): "1",  # Minimum
                ("HighValue", "min_interval_seconds"): "1",  # Minimum
            }
            return config_values.get((section, key), "")

        mock_config.get.side_effect = mock_get

        mock_manager_class = MagicMock()
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager
        mock_manager.is_high_value.return_value = (True, "HIGH")
        mock_manager.get_stats.return_value = {
            "thresholds": {"high": 0.01},
            "jobs_accepted_today": 0,
        }

        with patch("test_high_value_setup.AppConfig", mock_config_class):
            with patch(
                "test_high_value_setup.HighValueJobManager", mock_manager_class
            ):
                result = await test_high_value_manager()

        assert result is True

    def test_configuration_with_special_characters(self, tmp_path, monkeypatch):
        """Test configuration with special characters in values."""
        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text(
            """[WebSocket]
user_key = test_key_with_special_chars_!@#$%^&*()
user_session = session_with_equals=sign
"""
        )
        monkeypatch.chdir(tmp_path)

        mock_config_class = MagicMock()
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        def mock_get(section, key):
            if section == "WebSocket" and key == "user_key":
                return "test_key_with_special_chars_!@#$%^&*()"
            if section == "WebSocket" and key == "user_session":
                return "session_with_equals=sign"
            return ""

        mock_config.get.side_effect = mock_get

        with patch("test_high_value_setup.AppConfig", mock_config_class):
            # Should handle special characters without issues
            try:
                result = test_configuration()
                assert isinstance(result, bool)
            except Exception as e:
                pytest.fail(f"Should not raise exception with special chars: {e}")