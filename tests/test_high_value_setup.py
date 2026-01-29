"""Tests for the high-value job setup test script."""

import pytest
import tempfile
import pathlib
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path


@pytest.fixture
def mock_config():
    """Create a mock AppConfig for testing."""
    from gengowatcher.config import AppConfig

    config = MagicMock(spec=AppConfig)
    config.CONFIG_FILE = "config_high_value.ini"

    def get_side_effect(section, key, **kwargs):
        config_data = {
            "Watcher": {
                "feed_url": "https://gengo.com/rss/available_jobs/test_key",
            },
            "WebSocket": {
                "user_id": 12345,
                "user_session": "valid_session_token",
                "user_key": "valid_user_key",
            },
            "HighValue": {
                "threshold": "500.0",
                "very_high_threshold": "1000.0",
                "extreme_threshold": "5000.0",
                "max_per_day": "3",
                "min_interval_seconds": "21600",
            },
            "Captcha": {
                "service": "2captcha",
                "api_key": "valid_api_key",
            },
        }
        return config_data.get(section, {}).get(key, "")

    config.get.side_effect = get_side_effect
    return config


class TestConfigValidation:
    """Tests for configuration validation function."""

    def test_configuration_file_not_found(self, tmp_path, monkeypatch):
        """Test error message when config file is missing."""
        monkeypatch.chdir(tmp_path)

        # Import after changing directory
        from scripts.test_high_value_setup import test_configuration

        result = test_configuration()
        assert result is False

    def test_configuration_valid_settings(self, tmp_path, monkeypatch, mock_config):
        """Test successful validation with valid config."""
        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text("[Watcher]\nfeed_url = https://gengo.com/rss/test\n")
        monkeypatch.chdir(tmp_path)

        with patch("scripts.test_high_value_setup.AppConfig", return_value=mock_config):
            from scripts.test_high_value_setup import test_configuration

            result = test_configuration()
            assert result is True

    def test_configuration_invalid_rss_url(self, tmp_path, monkeypatch, capsys):
        """Test detection of invalid RSS URL."""
        from gengowatcher.config import AppConfig

        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text("[Watcher]\nfeed_url = https://example.com/YOUR_RSS_KEY\n")
        monkeypatch.chdir(tmp_path)

        mock_config = MagicMock(spec=AppConfig)
        mock_config.CONFIG_FILE = "config_high_value.ini"
        mock_config.get.side_effect = lambda s, k: "https://example.com/YOUR_RSS_KEY" if k == "feed_url" else ""

        with patch("scripts.test_high_value_setup.AppConfig", return_value=mock_config):
            from scripts.test_high_value_setup import test_configuration

            result = test_configuration()
            captured = capsys.readouterr()
            assert "RSS feed URL needs configuration" in captured.out

    def test_configuration_missing_websocket_credentials(self, tmp_path, monkeypatch, capsys):
        """Test detection of missing WebSocket credentials."""
        from gengowatcher.config import AppConfig

        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text("[WebSocket]\nuser_id = 0\n")
        monkeypatch.chdir(tmp_path)

        mock_config = MagicMock(spec=AppConfig)
        mock_config.CONFIG_FILE = "config_high_value.ini"
        mock_config.get.side_effect = lambda s, k: {
            ("Watcher", "feed_url"): "https://gengo.com/rss/test",
            ("WebSocket", "user_id"): 0,
            ("WebSocket", "user_session"): "YOUR_SESSION_TOKEN",
            ("WebSocket", "user_key"): "YOUR_USER_KEY",
        }.get((s, k), "")

        with patch("scripts.test_high_value_setup.AppConfig", return_value=mock_config):
            from scripts.test_high_value_setup import test_configuration

            result = test_configuration()
            captured = capsys.readouterr()
            assert "WebSocket needs configuration" in captured.out

    def test_configuration_loads_thresholds(self, tmp_path, monkeypatch, mock_config, capsys):
        """Test that high-value thresholds are loaded correctly."""
        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text("[HighValue]\nthreshold = 500.0\n")
        monkeypatch.chdir(tmp_path)

        with patch("scripts.test_high_value_setup.AppConfig", return_value=mock_config):
            from scripts.test_high_value_setup import test_configuration

            result = test_configuration()
            captured = capsys.readouterr()
            assert "$500.0" in captured.out or "$500" in captured.out

    def test_configuration_captcha_not_configured(self, tmp_path, monkeypatch, capsys):
        """Test warning when CAPTCHA service is not configured."""
        from gengowatcher.config import AppConfig

        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text("[Captcha]\nservice = \n")
        monkeypatch.chdir(tmp_path)

        mock_config = MagicMock(spec=AppConfig)
        mock_config.CONFIG_FILE = "config_high_value.ini"
        mock_config.get.side_effect = lambda s, k: {
            ("Watcher", "feed_url"): "https://gengo.com/rss/test",
            ("WebSocket", "user_id"): 12345,
            ("WebSocket", "user_session"): "valid_token",
            ("WebSocket", "user_key"): "valid_key",
            ("HighValue", "threshold"): "500.0",
            ("HighValue", "very_high_threshold"): "1000.0",
            ("HighValue", "extreme_threshold"): "5000.0",
            ("Captcha", "service"): "",
            ("Captcha", "api_key"): "",
        }.get((s, k), "")

        with patch("scripts.test_high_value_setup.AppConfig", return_value=mock_config):
            from scripts.test_high_value_setup import test_configuration

            result = test_configuration()
            captured = capsys.readouterr()
            assert "CAPTCHA service not configured" in captured.out


class TestHighValueManager:
    """Tests for HighValueJobManager testing function."""

    @pytest.mark.asyncio
    async def test_manager_initialization(self, tmp_path, monkeypatch, mock_config, mock_logger):
        """Test that HighValueJobManager initializes correctly."""
        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text("[HighValue]\nthreshold = 500.0\n")
        monkeypatch.chdir(tmp_path)

        with patch("scripts.test_high_value_setup.AppConfig", return_value=mock_config):
            from scripts.test_high_value_setup import test_high_value_manager

            result = await test_high_value_manager()
            assert result is True

    @pytest.mark.asyncio
    async def test_manager_job_classification(self, tmp_path, monkeypatch, mock_config, capsys):
        """Test that jobs are classified correctly by value."""
        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text("[HighValue]\nthreshold = 500.0\n")
        monkeypatch.chdir(tmp_path)

        with patch("scripts.test_high_value_setup.AppConfig", return_value=mock_config):
            from scripts.test_high_value_setup import test_high_value_manager

            result = await test_high_value_manager()
            captured = capsys.readouterr()

            # Verify that different job values are classified
            assert "Small job" in captured.out
            assert "High-value job" in captured.out or "HIGH" in captured.out.upper()

    @pytest.mark.asyncio
    async def test_manager_error_handling(self, tmp_path, monkeypatch, capsys):
        """Test error handling when manager initialization fails."""
        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text("[HighValue]\nthreshold = invalid\n")
        monkeypatch.chdir(tmp_path)

        from scripts.test_high_value_setup import test_high_value_manager

        result = await test_high_value_manager()
        captured = capsys.readouterr()

        # Should handle errors gracefully
        assert "Error" in captured.out or result is False


class TestSetupInstructions:
    """Tests for setup instructions display."""

    def test_show_setup_instructions_output(self, capsys):
        """Test that setup instructions are displayed correctly."""
        # Mock the missing module to allow import
        with patch.dict('sys.modules', {'gengowatcher.high_value_job_manager': MagicMock()}):
            from scripts.test_high_value_setup import show_setup_instructions

            show_setup_instructions()
            captured = capsys.readouterr()

            # Check for key instruction sections
            assert "HIGH-VALUE JOB SETUP INSTRUCTIONS" in captured.out
            assert "CONFIGURATION" in captured.out
            assert "RSS FEED" in captured.out
            assert "WEBSOCKET" in captured.out
            assert "RUNNING" in captured.out
            assert "SAFETY LIMITS" in captured.out

    def test_setup_instructions_contains_urls(self, capsys):
        """Test that setup instructions contain necessary URLs."""
        from urllib.parse import urlparse
        import re
        
        # Mock the missing module to allow import
        with patch.dict('sys.modules', {'gengowatcher.high_value_job_manager': MagicMock()}):
            from scripts.test_high_value_setup import show_setup_instructions

            show_setup_instructions()
            captured = capsys.readouterr()

            # Validate complete URLs instead of substrings to ensure proper sanitization
            assert "https://gengo.com/developers/dashboard" in captured.out
            assert "https://gengo.com/rss/available_jobs/" in captured.out
            
            # Verify URLs are properly formed
            for line in captured.out.split('\n'):
                if 'https://gengo.com' in line:
                    # Extract URL from the line and validate it
                    urls = re.findall(r'https://gengo\.com[^\s\)]*', line)
                    for url in urls:
                        parsed = urlparse(url)
                        assert parsed.scheme == 'https'
                        assert parsed.hostname and parsed.hostname.endswith('gengo.com')
            
            assert "RSS" in captured.out

    def test_setup_instructions_contains_limits(self, capsys):
        """Test that safety limits are documented."""
        # Mock the missing module to allow import
        with patch.dict('sys.modules', {'gengowatcher.high_value_job_manager': MagicMock()}):
            from scripts.test_high_value_setup import show_setup_instructions

            show_setup_instructions()
            captured = capsys.readouterr()

            assert "3 high-value jobs per day" in captured.out or "per day" in captured.out
            assert "6 hours" in captured.out or "hours between" in captured.out


class TestMainFunction:
    """Tests for the main test runner function."""

    def test_main_runs_configuration_test(self, tmp_path, monkeypatch, capsys):
        """Test that main function runs configuration test."""
        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text("[Watcher]\nfeed_url = test\n")
        monkeypatch.chdir(tmp_path)

        with patch("scripts.test_high_value_setup.test_configuration", return_value=False):
            from scripts.test_high_value_setup import main

            main()
            captured = capsys.readouterr()
            assert "GengoWatcher High-Value Job Setup Test" in captured.out

    def test_main_handles_config_failure(self, tmp_path, monkeypatch, capsys):
        """Test main function handles configuration test failure."""
        monkeypatch.chdir(tmp_path)

        with patch("scripts.test_high_value_setup.test_configuration", return_value=False):
            from scripts.test_high_value_setup import main

            main()
            captured = capsys.readouterr()
            assert "Configuration test failed" in captured.out or "failed" in captured.out.lower()

    def test_main_success_path(self, tmp_path, monkeypatch, capsys):
        """Test main function success path with all tests passing."""
        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text("[HighValue]\nthreshold = 500.0\n")
        monkeypatch.chdir(tmp_path)

        with patch("scripts.test_high_value_setup.test_configuration", return_value=True):
            with patch("scripts.test_high_value_setup.asyncio.run", return_value=True):
                from scripts.test_high_value_setup import main

                main()
                captured = capsys.readouterr()
                assert "All tests passed" in captured.out or "passed" in captured.out.lower()


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_configuration_with_placeholder_tokens(self, tmp_path, monkeypatch, capsys):
        """Test detection of various placeholder token formats."""
        from gengowatcher.config import AppConfig

        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text("[WebSocket]\nuser_key = REPLACE_WITH_BROWSER_USER_KEY\n")
        monkeypatch.chdir(tmp_path)

        mock_config = MagicMock(spec=AppConfig)
        mock_config.CONFIG_FILE = "config_high_value.ini"
        mock_config.get.side_effect = lambda s, k: {
            ("Watcher", "feed_url"): "https://gengo.com/rss/test",
            ("WebSocket", "user_id"): 12345,
            ("WebSocket", "user_session"): "valid_token",
            ("WebSocket", "user_key"): "REPLACE_WITH_BROWSER_USER_KEY",
        }.get((s, k), "")

        with patch("scripts.test_high_value_setup.AppConfig", return_value=mock_config):
            from scripts.test_high_value_setup import test_configuration

            result = test_configuration()
            captured = capsys.readouterr()
            assert "WebSocket needs configuration" in captured.out

    def test_configuration_exception_handling(self, tmp_path, monkeypatch, capsys):
        """Test that exceptions during config loading are handled."""
        config_file = tmp_path / "config_high_value.ini"
        config_file.write_text("[HighValue]\nthreshold = 500.0\n")
        monkeypatch.chdir(tmp_path)

        mock_config = MagicMock()
        mock_config.get.side_effect = Exception("Config error")

        with patch("scripts.test_high_value_setup.AppConfig", return_value=mock_config):
            from scripts.test_high_value_setup import test_configuration

            result = test_configuration()
            captured = capsys.readouterr()
            assert result is False
            assert "Error loading configuration" in captured.out