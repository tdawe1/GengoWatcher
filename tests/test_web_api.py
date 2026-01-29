"""Comprehensive tests for web.py API endpoints and WebAPI class."""

import pytest
import tempfile
import pathlib
from unittest.mock import MagicMock, AsyncMock, patch
import json
import time

from fastapi.testclient import TestClient

# Mock dependencies before importing web module
import sys
from unittest.mock import MagicMock

mock_config = MagicMock()
mock_state = MagicMock()
mock_logger = MagicMock()

sys.modules['gengowatcher.watcher'].GengoWatcher = MagicMock


class TestWebAPIInitialization:
    """Test WebAPI class initialization."""

    def test_webapi_initialization(self):
        """Test that WebAPI initializes correctly."""
        from gengowatcher.web import WebAPI
        from gengowatcher.config import AppConfig
        from gengowatcher.state import AppState
        import logging

        config = MagicMock(spec=AppConfig)
        state = MagicMock(spec=AppState)
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher'):
            api = WebAPI(config, state, logger)

            assert api.config == config
            assert api.state == state
            assert api.logger == logger
            assert hasattr(api, 'watcher')

    def test_webapi_starts_watcher_thread(self):
        """Test that WebAPI starts watcher in a thread."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        state = MagicMock()
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher') as mock_watcher_class:
            mock_watcher = MagicMock()
            mock_watcher_class.return_value = mock_watcher

            api = WebAPI(config, state, logger)

            # Should have started watcher thread
            assert hasattr(api, 'watcher_thread')


class TestWebAPIStatus:
    """Test status retrieval methods."""

    def test_get_status_returns_watcher_status(self):
        """Test that get_status returns WatcherStatus model."""
        from gengowatcher.web import WebAPI, WatcherStatus
        import logging
        import datetime

        config = MagicMock()
        state = MagicMock()
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher') as mock_watcher_class:
            mock_watcher = MagicMock()
            mock_watcher.shutdown_event.is_set.return_value = False
            mock_watcher.websocket_status = "Live"
            mock_watcher.rss_action = "Checking"
            mock_watcher.last_check_time = datetime.datetime.now()
            mock_watcher.next_check_time = time.time() + 60
            mock_watcher.session_new_entries = 10
            mock_watcher.session_total_value = 150.0
            mock_watcher.start_time = time.time() - 3600
            mock_watcher.failure_count = 0
            mock_watcher.get_cancellation_stats.return_value = None
            mock_watcher_class.return_value = mock_watcher

            api = WebAPI(config, state, logger)
            status = api.get_status()

            assert isinstance(status, WatcherStatus)
            assert status.is_running is True
            assert status.websocket_status == "Live"
            assert status.rss_status == "Checking"

    def test_get_status_with_float_timestamp(self):
        """Test get_status when last_check_time is a float."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        state = MagicMock()
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher') as mock_watcher_class:
            mock_watcher = MagicMock()
            mock_watcher.shutdown_event.is_set.return_value = False
            mock_watcher.websocket_status = "Live"
            mock_watcher.rss_action = "Checking"
            mock_watcher.last_check_time = 1234567890.0  # Float timestamp
            mock_watcher.next_check_time = time.time() + 60
            mock_watcher.session_new_entries = 0
            mock_watcher.session_total_value = 0.0
            mock_watcher.start_time = time.time()
            mock_watcher.failure_count = 0
            mock_watcher.get_cancellation_stats.return_value = None
            mock_watcher_class.return_value = mock_watcher

            api = WebAPI(config, state, logger)
            status = api.get_status()

            assert status.last_check_time == 1234567890.0


class TestWebAPIJobs:
    """Test job retrieval methods."""

    def test_get_recent_jobs_with_pagination(self):
        """Test retrieving recent jobs with pagination."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        state = MagicMock()
        logger = logging.getLogger("test")

        # Mock state to return jobs
        mock_jobs = [
            {
                "id": str(i),
                "title": f"Job {i}",
                "reward": float(i * 10),
                "currency": "USD",
                "url": f"http://example.com/{i}",
                "timestamp": time.time(),
                "source": "RSS",
            }
            for i in range(100)
        ]
        state.get_recent_jobs.return_value = mock_jobs

        with patch('gengowatcher.web.GengoWatcher'):
            api = WebAPI(config, state, logger)
            result = api.get_recent_jobs(limit=10, page=1)

            assert "jobs" in result
            assert "pagination" in result
            assert len(result["jobs"]) <= 10
            assert result["pagination"]["page"] == 1
            assert result["pagination"]["limit"] == 10

    def test_get_recent_jobs_handles_invalid_job_data(self):
        """Test that invalid job data is skipped gracefully."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        state = MagicMock()
        logger = logging.getLogger("test")

        # Mock state with invalid jobs
        mock_jobs = [
            {"id": "1", "title": "Valid Job", "reward": 10.0, "currency": "USD",
             "url": "http://example.com", "timestamp": time.time(), "source": "RSS"},
            {"id": "", "title": "", "reward": -10},  # Invalid
        ]
        state.get_recent_jobs.return_value = mock_jobs

        with patch('gengowatcher.web.GengoWatcher'):
            api = WebAPI(config, state, logger)
            result = api.get_recent_jobs(limit=10, page=1)

            # Should skip invalid job
            assert len(result["jobs"]) == 1

    def test_add_job(self):
        """Test adding a new job."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        state = MagicMock()
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher'):
            api = WebAPI(config, state, logger)

            api.add_job("123", "Test Job", 50.0, "http://example.com", "RSS")

            state.add_job.assert_called_once()


class TestWebAPIConfig:
    """Test configuration management methods."""

    def test_get_config(self):
        """Test retrieving configuration."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        config.config = {
            "Watcher": {
                "check_interval": 30,
                "min_reward": 10.0,
            }
        }
        state = MagicMock()
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher'):
            api = WebAPI(config, state, logger)
            sections = api.get_config()

            assert isinstance(sections, list)
            assert len(sections) > 0

    def test_update_config(self):
        """Test updating configuration."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        state = MagicMock()
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher') as mock_watcher_class:
            mock_watcher = MagicMock()
            mock_watcher_class.return_value = mock_watcher

            api = WebAPI(config, state, logger)

            result = api.update_config("Watcher", "check_interval", "60")

            assert result is True
            mock_watcher.set_config_value.assert_called_once()

    def test_update_config_handles_error(self):
        """Test that config update errors are handled."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        state = MagicMock()
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher') as mock_watcher_class:
            mock_watcher = MagicMock()
            mock_watcher.set_config_value.side_effect = Exception("Config error")
            mock_watcher_class.return_value = mock_watcher

            api = WebAPI(config, state, logger)

            result = api.update_config("Watcher", "check_interval", "60")

            assert result is False


class TestWebAPICommands:
    """Test command execution methods."""

    def test_execute_check_command(self):
        """Test executing check command."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        state = MagicMock()
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher') as mock_watcher_class:
            mock_watcher = MagicMock()
            mock_watcher_class.return_value = mock_watcher

            api = WebAPI(config, state, logger)

            result = api.execute_command("check")

            assert result["status"] == "success"
            mock_watcher.check_now_event.set.assert_called_once()

    def test_execute_pause_command(self):
        """Test executing pause command."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        state = MagicMock()
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher') as mock_watcher_class:
            with patch('builtins.open', create=True) as mock_open:
                mock_watcher = MagicMock()
                mock_watcher.PAUSE_FILE = "/tmp/test_pause"
                mock_watcher_class.return_value = mock_watcher

                api = WebAPI(config, state, logger)

                result = api.execute_command("pause")

                assert result["status"] == "success"

    def test_execute_unknown_command(self):
        """Test executing unknown command."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        state = MagicMock()
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher'):
            api = WebAPI(config, state, logger)

            result = api.execute_command("unknown_command")

            assert result["status"] == "error"


class TestPydanticModels:
    """Test Pydantic model validation."""

    def test_job_entry_validation(self):
        """Test JobEntry model validation."""
        from gengowatcher.web import JobEntry

        # Valid job
        job = JobEntry(
            id="123",
            title="Test Job",
            reward=50.0,
            currency="USD",
            url="http://example.com",
            timestamp=time.time(),
            source="RSS"
        )

        assert job.id == "123"
        assert job.reward == 50.0

    def test_job_entry_invalid_reward(self):
        """Test JobEntry validation with invalid reward."""
        from gengowatcher.web import JobEntry
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            JobEntry(
                id="123",
                title="Test",
                reward=-10.0,  # Negative reward
                currency="USD",
                url="http://example.com",
                timestamp=time.time(),
                source="RSS"
            )

    def test_watcher_status_validation(self):
        """Test WatcherStatus model validation."""
        from gengowatcher.web import WatcherStatus

        status = WatcherStatus(
            is_running=True,
            websocket_status="Live",
            rss_status="Checking",
            last_check_time=time.time(),
            next_check_time=time.time() + 60,
            session_stats={"uptime": 3600},
            failure_count=0
        )

        assert status.is_running is True
        assert status.websocket_status == "Live"

    def test_command_request_validation(self):
        """Test CommandRequest model validation."""
        from gengowatcher.web import CommandRequest

        cmd = CommandRequest(command="check", args=[])

        assert cmd.command == "check"
        assert cmd.args == []

    def test_command_request_invalid_command(self):
        """Test CommandRequest with invalid command."""
        from gengowatcher.web import CommandRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CommandRequest(command="invalid_cmd")

    def test_pagination_params_validation(self):
        """Test PaginationParams model validation."""
        from gengowatcher.web import PaginationParams

        params = PaginationParams(page=1, limit=50)

        assert params.page == 1
        assert params.limit == 50

    def test_pagination_params_invalid_page(self):
        """Test PaginationParams with invalid page."""
        from gengowatcher.web import PaginationParams
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PaginationParams(page=0)  # Page must be >= 1

    def test_pagination_params_limit_exceeds_max(self):
        """Test PaginationParams with limit exceeding maximum."""
        from gengowatcher.web import PaginationParams
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PaginationParams(limit=200)  # Max limit is 100


class TestAPIAuthenticator:
    """Test API authentication."""

    def test_authenticator_initialization_with_key(self):
        """Test APIAuthenticator with provided key."""
        from gengowatcher.web import APIAuthenticator

        auth = APIAuthenticator(api_key="test_key_123")

        assert auth.api_key == "test_key_123"

    def test_authenticator_initialization_generates_key(self):
        """Test APIAuthenticator generates key if not provided."""
        from gengowatcher.web import APIAuthenticator

        auth = APIAuthenticator()

        assert auth.api_key is not None
        assert len(auth.api_key) > 0

    def test_get_api_key(self):
        """Test getting API key."""
        from gengowatcher.web import APIAuthenticator

        auth = APIAuthenticator(api_key="test_key")

        assert auth.get_api_key() == "test_key"


class TestWebAPIJobCancellation:
    """Test job cancellation functionality."""

    @pytest.mark.asyncio
    async def test_cancel_current_job(self):
        """Test cancelling current job."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        state = MagicMock()
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher') as mock_watcher_class:
            mock_watcher = MagicMock()
            mock_watcher.cancel_current_job_async = AsyncMock(return_value=True)
            mock_watcher_class.return_value = mock_watcher

            api = WebAPI(config, state, logger)

            result = await api.cancel_current_job()

            assert result is True


class TestWebAPICSVJobs:
    """Test CSV job retrieval."""

    def test_get_jobs_from_csv_file_not_found(self):
        """Test getting jobs from non-existent CSV file."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        config.get.return_value = "/nonexistent/file.csv"
        state = MagicMock()
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher'):
            api = WebAPI(config, state, logger)

            result = api.get_jobs_from_csv(limit=10, page=1)

            assert result["pagination"]["total"] == 0
            assert len(result["jobs"]) == 0

    def test_get_jobs_from_csv_with_filters(self):
        """Test getting jobs from CSV with filters."""
        from gengowatcher.web import WebAPI
        import logging
        import tempfile
        import csv

        config = MagicMock()
        state = MagicMock()
        logger = logging.getLogger("test")

        # Create temp CSV file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "title", "reward", "link", "summary"])
            writer.writerow(["2024-01-01", "Job 1", "50.00", "http://example.com/1", "Test"])
            writer.writerow(["2024-01-02", "Job 2", "100.00", "http://example.com/2", "Test"])
            csv_path = f.name

        config.get.return_value = csv_path

        try:
            with patch('gengowatcher.web.GengoWatcher'):
                api = WebAPI(config, state, logger)

                result = api.get_jobs_from_csv(
                    limit=10,
                    page=1,
                    min_reward=75.0,
                    max_reward=150.0
                )

                # Should only return Job 2 (reward 100.00)
                assert len(result["jobs"]) == 1
        finally:
            import os
            os.unlink(csv_path)


class TestWebAPIShutdown:
    """Test API shutdown."""

    def test_shutdown_calls_watcher_exit(self):
        """Test that shutdown calls watcher.handle_exit."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        state = MagicMock()
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher') as mock_watcher_class:
            mock_watcher = MagicMock()
            mock_watcher_class.return_value = mock_watcher

            api = WebAPI(config, state, logger)
            api.shutdown()

            mock_watcher.handle_exit.assert_called_once()


class TestWebAPIEdgeCases:
    """Test edge cases and error handling."""

    def test_get_recent_jobs_with_exception(self):
        """Test get_recent_jobs when exception occurs."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        state = MagicMock()
        state.get_recent_jobs.side_effect = Exception("State error")
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher'):
            api = WebAPI(config, state, logger)

            result = api.get_recent_jobs(limit=10, page=1)

            # Should return empty result
            assert result["pagination"]["total"] == 0

    @pytest.mark.asyncio
    async def test_accept_job_not_found(self):
        """Test accepting job that doesn't exist."""
        from gengowatcher.web import WebAPI
        import logging

        config = MagicMock()
        state = MagicMock()
        state.get_recent_jobs.return_value = []
        logger = logging.getLogger("test")

        with patch('gengowatcher.web.GengoWatcher'):
            api = WebAPI(config, state, logger)

            result = await api.accept_job("nonexistent_id")

            assert result is False