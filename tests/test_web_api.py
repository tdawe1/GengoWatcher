"""Comprehensive tests for the web API module."""

import pytest
import asyncio
import json
import tempfile
import pathlib
import time
import tempfile as tf
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

from gengowatcher.web import (
    APIAuthenticator,
    WebAPI,
    JobEntry,
    WatcherStatus,
    ConfigSection,
    CommandRequest,
    PaginationParams,
    app,
)


@pytest.fixture
def mock_config():
    """Create mock config for testing."""
    config = MagicMock()
    config.get.side_effect = lambda s, k, **kw: {
        ("WebServer", "auth_token"): "test_api_key_12345",
        ("Paths", "all_entries_log"): "logs/test_entries.csv",
    }.get((s, k), kw.get("fallback", ""))
    config.config = {
        "Watcher": {"check_interval": 60, "min_reward": 5.0},
        "WebSocket": {"enable_websocket": True},
    }
    return config


@pytest.fixture
def mock_state():
    """Create mock state for testing."""
    state = MagicMock()
    state.get_recent_jobs.return_value = []
    return state


@pytest.fixture
def mock_logger():
    """Create mock logger for testing."""
    import logging

    return logging.getLogger("test")


@pytest.fixture
def mock_watcher():
    """Create mock watcher for testing."""
    watcher = MagicMock()
    watcher.start_time = time.time()
    watcher.websocket_status = "Live"
    watcher.rss_action = "Checking"
    watcher.last_check_time = time.time()
    watcher.next_check_time = time.time() + 60
    watcher.session_new_entries = 5
    watcher.session_total_value = 125.50
    watcher.failure_count = 0
    watcher.shutdown_event = MagicMock()
    watcher.shutdown_event.is_set.return_value = False
    watcher.PAUSE_FILE = f"{tf.gettempdir()}/test_pause"
    watcher.get_cancellation_stats.return_value = {"cancellations_today": 2}
    watcher.job_acceptance_engine = MagicMock()
    return watcher


class TestAPIAuthenticator:
    """Tests for API authentication."""

    def test_authenticator_initialization_with_key(self):
        """Test authenticator initializes with provided key."""
        auth = APIAuthenticator(api_key="test_key_123")
        assert auth.api_key == "test_key_123"

    def test_authenticator_initialization_generates_key(self):
        """Test authenticator generates random key when not provided."""
        auth = APIAuthenticator()
        assert auth.api_key is not None
        assert len(auth.api_key) > 20  # Token should be reasonably long

    def test_authenticate_valid_credentials(self):
        """Test authentication with valid credentials."""
        auth = APIAuthenticator(api_key="valid_key")

        mock_creds = MagicMock()
        mock_creds.credentials = "valid_key"

        result = auth.authenticate(mock_creds)
        assert result is True

    def test_authenticate_invalid_credentials(self):
        """Test authentication with invalid credentials."""
        auth = APIAuthenticator(api_key="valid_key")

        mock_creds = MagicMock()
        mock_creds.credentials = "wrong_key"

        result = auth.authenticate(mock_creds)
        assert result is False

    def test_authenticate_no_credentials(self):
        """Test authentication with no credentials provided."""
        auth = APIAuthenticator(api_key="valid_key")
        result = auth.authenticate(None)
        assert result is False

    def test_get_api_key(self):
        """Test getting the current API key."""
        auth = APIAuthenticator(api_key="my_key")
        assert auth.get_api_key() == "my_key"


class TestPydanticModels:
    """Tests for Pydantic validation models."""

    def test_job_entry_validation_success(self):
        """Test JobEntry validates correct data."""
        job = JobEntry(
            id="12345",
            title="Translation Job",
            reward=25.50,
            currency="USD",
            url="https://gengo.com/jobs/12345",
            timestamp=time.time(),
            source="rss",
        )
        assert job.id == "12345"
        assert job.reward == 25.50

    def test_job_entry_validation_negative_reward(self):
        """Test JobEntry rejects negative reward."""
        with pytest.raises(ValueError):
            JobEntry(
                id="12345",
                title="Job",
                reward=-10.0,
                url="https://example.com",
                timestamp=time.time(),
                source="rss",
            )

    def test_job_entry_validation_empty_id(self):
        """Test JobEntry rejects empty ID."""
        with pytest.raises(ValueError):
            JobEntry(
                id="",
                title="Job",
                reward=10.0,
                url="https://example.com",
                timestamp=time.time(),
                source="rss",
            )

    def test_job_entry_strips_whitespace(self):
        """Test JobEntry strips whitespace from strings."""
        job = JobEntry(
            id="  12345  ",
            title="  Job Title  ",
            reward=10.0,
            url="  https://example.com  ",
            timestamp=time.time(),
            source="  rss  ",
        )
        assert job.id == "12345"
        assert job.title == "Job Title"

    def test_watcher_status_validation(self):
        """Test WatcherStatus validates correctly."""
        status = WatcherStatus(
            is_running=True,
            websocket_status="Live",
            rss_status="Checking",
            last_check_time=time.time(),
            next_check_time=time.time() + 60,
            session_stats={"uptime": 3600},
            failure_count=0,
        )
        assert status.is_running is True
        assert status.websocket_status == "Live"

    def test_command_request_validation_valid(self):
        """Test CommandRequest validates valid commands."""
        cmd = CommandRequest(command="check")
        assert cmd.command == "check"

        cmd = CommandRequest(command="pause", args=["arg1"])
        assert cmd.command == "pause"
        assert cmd.args == ["arg1"]

    def test_command_request_validation_invalid_command(self):
        """Test CommandRequest rejects invalid commands."""
        with pytest.raises(ValueError):
            CommandRequest(command="invalid_command")

    def test_pagination_params_validation(self):
        """Test PaginationParams validates correctly."""
        params = PaginationParams(page=1, limit=50)
        assert params.page == 1
        assert params.limit == 50

    def test_pagination_params_validation_invalid(self):
        """Test PaginationParams rejects invalid values."""
        with pytest.raises(ValueError):
            PaginationParams(page=0, limit=50)

        with pytest.raises(ValueError):
            PaginationParams(page=1, limit=200)  # Exceeds max


class TestWebAPI:
    """Tests for WebAPI class."""

    def test_web_api_initialization(self, mock_config, mock_state, mock_logger):
        """Test WebAPI initializes correctly."""
        with patch("gengowatcher.web.GengoWatcher") as mock_watcher_class:
            mock_watcher_instance = MagicMock()
            mock_watcher_class.return_value = mock_watcher_instance

            api = WebAPI(mock_config, mock_state, mock_logger)

            assert api.config == mock_config
            assert api.state == mock_state
            assert api.logger == mock_logger
            assert api.watcher is not None

    def test_get_status(self, mock_config, mock_state, mock_logger, mock_watcher):
        """Test getting watcher status."""
        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)
            api.watcher = mock_watcher

            status = api.get_status()

            assert isinstance(status, WatcherStatus)
            assert status.is_running is True
            assert status.websocket_status == "Live"
            assert status.rss_status == "Checking"

    def test_get_recent_jobs(self, mock_config, mock_state, mock_logger, mock_watcher):
        """Test getting recent jobs with pagination."""
        mock_state.get_recent_jobs.return_value = [
            {
                "id": "123",
                "title": "Job 1",
                "reward": 10.0,
                "url": "https://example.com/123",
                "timestamp": time.time(),
                "source": "rss",
            },
            {
                "id": "456",
                "title": "Job 2",
                "reward": 20.0,
                "url": "https://example.com/456",
                "timestamp": time.time(),
                "source": "websocket",
            },
        ]

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            result = api.get_recent_jobs(limit=50, page=1)

            assert "jobs" in result
            assert "pagination" in result
            assert len(result["jobs"]) == 2
            assert result["pagination"]["total"] == 2

    def test_get_recent_jobs_pagination(
        self, mock_config, mock_state, mock_logger, mock_watcher
    ):
        """Test job pagination works correctly."""
        jobs = [
            {
                "id": str(i),
                "title": f"Job {i}",
                "reward": 10.0,
                "url": f"https://example.com/{i}",
                "timestamp": time.time(),
                "source": "rss",
            }
            for i in range(100)
        ]
        mock_state.get_recent_jobs.return_value = jobs

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            # Get first page
            result = api.get_recent_jobs(limit=10, page=1)
            assert len(result["jobs"]) == 10
            assert result["pagination"]["pages"] == 10

    def test_get_jobs_from_csv(
        self, mock_config, mock_state, mock_logger, mock_watcher, tmp_path
    ):
        """Test reading jobs from CSV file."""
        # Create a test CSV file
        csv_file = tmp_path / "test_entries.csv"
        csv_content = """timestamp,title,reward,link,summary
2024-01-01T12:00:00,Job 1,10.50,https://example.com/1,Summary 1
2024-01-01T13:00:00,Job 2,25.00,https://example.com/2,Summary 2
"""
        csv_file.write_text(csv_content)

        mock_config.get.side_effect = lambda s, k, **kw: {
            ("Paths", "all_entries_log"): str(csv_file)
        }.get((s, k), kw.get("fallback", ""))

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            result = api.get_jobs_from_csv(limit=50, page=1)

            assert "jobs" in result
            assert len(result["jobs"]) == 2
            assert result["jobs"][0].reward == 10.5
            assert result["jobs"][1].reward == 25.0

    def test_get_jobs_from_csv_with_filters(
        self, mock_config, mock_state, mock_logger, mock_watcher, tmp_path
    ):
        """Test CSV reading with min/max reward filters."""
        csv_file = tmp_path / "test_entries.csv"
        csv_content = """timestamp,title,reward,link,summary
2024-01-01T12:00:00,Job 1,5.00,https://example.com/1,Summary 1
2024-01-01T13:00:00,Job 2,15.00,https://example.com/2,Summary 2
2024-01-01T14:00:00,Job 3,25.00,https://example.com/3,Summary 3
"""
        csv_file.write_text(csv_content)

        mock_config.get.side_effect = lambda s, k, **kw: {
            ("Paths", "all_entries_log"): str(csv_file)
        }.get((s, k), kw.get("fallback", ""))

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            # Filter for jobs between $10 and $20
            result = api.get_jobs_from_csv(
                limit=50, page=1, min_reward=10.0, max_reward=20.0
            )

            assert len(result["jobs"]) == 1
            assert result["jobs"][0].reward == 15.0

    def test_get_jobs_from_csv_search_term(
        self, mock_config, mock_state, mock_logger, mock_watcher, tmp_path
    ):
        """Test CSV reading with search term filter."""
        csv_file = tmp_path / "test_entries.csv"
        csv_content = """timestamp,title,reward,link,summary
2024-01-01T12:00:00,Translation JA→EN,10.00,https://example.com/1,Japanese translation
2024-01-01T13:00:00,Translation EN→FR,15.00,https://example.com/2,French translation
"""
        csv_file.write_text(csv_content)

        mock_config.get.side_effect = lambda s, k, **kw: {
            ("Paths", "all_entries_log"): str(csv_file)
        }.get((s, k), kw.get("fallback", ""))

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            result = api.get_jobs_from_csv(limit=50, page=1, search_term="Japanese")

            assert len(result["jobs"]) == 1
            assert "JA→EN" in result["jobs"][0].title

    def test_add_job(self, mock_config, mock_state, mock_logger, mock_watcher):
        """Test adding a new job to state."""
        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            api.add_job("12345", "Test Job", 25.0, "https://example.com", "test")

            mock_state.add_job.assert_called_once()
            call_args = mock_state.add_job.call_args[0][0]
            assert call_args["id"] == "12345"
            assert call_args["reward"] == 25.0

    @pytest.mark.asyncio
    async def test_accept_job(self, mock_config, mock_state, mock_logger, mock_watcher):
        """Test accepting a job via API."""
        mock_state.get_recent_jobs.return_value = [
            {
                "id": "12345",
                "title": "Test Job",
                "reward": 25.0,
                "url": "https://example.com",
                "source": "rss",
            }
        ]

        async def mock_accept(job):
            return True

        mock_watcher.job_acceptance_engine._attempt_job_acceptance = mock_accept

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)
            api.watcher = mock_watcher

            # Need to wrap the get_recent_jobs to return JobEntry objects
            api.get_recent_jobs = MagicMock(
                return_value={
                    "jobs": [
                        JobEntry(
                            id="12345",
                            title="Test Job",
                            reward=25.0,
                            url="https://example.com",
                            timestamp=time.time(),
                            source="rss",
                        )
                    ]
                }
            )

            result = await api.accept_job("12345")
            assert result is True

    def test_get_config(self, mock_config, mock_state, mock_logger, mock_watcher):
        """Test getting configuration."""
        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            config = api.get_config()

            assert isinstance(config, list)
            assert all(isinstance(section, ConfigSection) for section in config)

    def test_update_config(self, mock_config, mock_state, mock_logger, mock_watcher):
        """Test updating configuration."""
        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            result = api.update_config("Watcher", "check_interval", "30")
            assert result is True

    def test_execute_command_check(
        self, mock_config, mock_state, mock_logger, mock_watcher
    ):
        """Test executing check command."""
        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            result = api.execute_command("check")

            assert result["status"] == "success"
            mock_watcher.check_now_event.set.assert_called_once()

    def test_execute_command_pause(
        self, mock_config, mock_state, mock_logger, mock_watcher, tmp_path
    ):
        """Test executing pause command."""
        pause_file = tmp_path / "pause"
        mock_watcher.PAUSE_FILE = str(pause_file)

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)
            api.watcher = mock_watcher

            result = api.execute_command("pause")

            assert result["status"] == "success"
            assert pause_file.exists()

    def test_execute_command_resume(
        self, mock_config, mock_state, mock_logger, mock_watcher, tmp_path
    ):
        """Test executing resume command."""
        pause_file = tmp_path / "pause"
        pause_file.write_text("")
        mock_watcher.PAUSE_FILE = str(pause_file)

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)
            api.watcher = mock_watcher

            result = api.execute_command("resume")

            assert result["status"] == "success"
            assert not pause_file.exists()

    def test_execute_command_cancel(
        self, mock_config, mock_state, mock_logger, mock_watcher
    ):
        """Test executing cancel command."""
        mock_watcher.cancel_current_job_sync.return_value = True

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)
            api.watcher = mock_watcher

            result = api.execute_command("cancel")

            assert result["status"] == "success"

    def test_execute_command_unknown(
        self, mock_config, mock_state, mock_logger, mock_watcher
    ):
        """Test executing unknown command."""
        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            # Bypass validation by calling directly
            result = api.execute_command("unknown_command")

            assert result["status"] == "error"


class TestFastAPIEndpoints:
    """Tests for FastAPI endpoints using TestClient."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_root_endpoint(self, client):
        """Test root endpoint returns API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert data["name"] == "GengoWatcher API"

    def test_health_check_endpoint(self, client):
        """Test health check endpoint."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_get_jobs_from_csv_file_not_found(
        self, mock_config, mock_state, mock_logger, mock_watcher
    ):
        """Test handling of missing CSV file."""
        mock_config.get.side_effect = lambda s, k, **kw: {
            ("Paths", "all_entries_log"): "/nonexistent/file.csv"
        }.get((s, k), kw.get("fallback", ""))

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            result = api.get_jobs_from_csv(limit=50, page=1)

            assert result["jobs"] == []
            assert result["pagination"]["total"] == 0

    def test_get_jobs_from_csv_malformed_data(
        self, mock_config, mock_state, mock_logger, mock_watcher, tmp_path
    ):
        """Test handling of malformed CSV data."""
        csv_file = tmp_path / "malformed.csv"
        csv_content = """timestamp,title,reward,link,summary
2024-01-01,Job 1,not_a_number,https://example.com/1,Summary
2024-01-02,Job 2,25.00,https://example.com/2,Summary
"""
        csv_file.write_text(csv_content)

        mock_config.get.side_effect = lambda s, k, **kw: {
            ("Paths", "all_entries_log"): str(csv_file)
        }.get((s, k), kw.get("fallback", ""))

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            result = api.get_jobs_from_csv(limit=50, page=1)

            # Should skip malformed row and return valid one
            assert len(result["jobs"]) >= 1

    def test_accept_job_not_found(
        self, mock_config, mock_state, mock_logger, mock_watcher
    ):
        """Test accepting a job that doesn't exist."""
        mock_state.get_recent_jobs.return_value = []

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            result = asyncio.run(api.accept_job("nonexistent"))
            assert result is False

    def test_update_config_error_handling(
        self, mock_config, mock_state, mock_logger, mock_watcher
    ):
        """Test error handling when config update fails."""
        mock_watcher.set_config_value = MagicMock(side_effect=Exception("Config error"))

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)
            api.watcher = mock_watcher

            result = api.update_config("Watcher", "check_interval", "30")
            assert result is False

    def test_get_recent_jobs_invalid_data(
        self, mock_config, mock_state, mock_logger, mock_watcher
    ):
        """Test handling of invalid job data."""
        mock_state.get_recent_jobs.return_value = [
            {},  # Empty dict
            {"id": "123"},  # Missing required fields
            {
                "id": "456",
                "title": "Valid",
                "reward": 10.0,
                "url": "https://example.com",
                "timestamp": time.time(),
                "source": "rss",
            },
        ]

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            result = api.get_recent_jobs(limit=50, page=1)

            # Should only return valid job
            assert len(result["jobs"]) == 1
            assert result["jobs"][0].id == "456"

    @pytest.mark.asyncio
    async def test_cancel_current_job_async(
        self, mock_config, mock_state, mock_logger, mock_watcher
    ):
        """Test async job cancellation via API."""

        async def mock_cancel():
            return True

        mock_watcher.cancel_current_job_async = mock_cancel

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)
            api.watcher = mock_watcher

            result = await api.cancel_current_job()
            assert result is True

    def test_pagination_ceiling_division(
        self, mock_config, mock_state, mock_logger, mock_watcher
    ):
        """Test pagination calculates pages correctly with ceiling division."""
        mock_state.get_recent_jobs.return_value = [
            {
                "id": str(i),
                "title": f"Job {i}",
                "reward": 10.0,
                "url": f"https://example.com/{i}",
                "timestamp": time.time(),
                "source": "rss",
            }
            for i in range(25)  # 25 jobs with limit of 10 should give 3 pages
        ]

        with patch("gengowatcher.web.GengoWatcher", return_value=mock_watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            result = api.get_recent_jobs(limit=10, page=1)

            assert result["pagination"]["pages"] == 3
