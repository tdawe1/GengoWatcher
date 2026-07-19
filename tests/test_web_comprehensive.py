"""Comprehensive tests for src/gengowatcher/web.py"""

import pytest
import asyncio
import tempfile
from unittest.mock import MagicMock, patch, AsyncMock

from gengowatcher.web import (
    WebAPI,
    APIAuthenticator,
    JobEntry,
    WatcherStatus,
    ConfigSection,
    CommandRequest,
    PaginationParams,
    ManagedWebServer,
    run_web_server,
)
import gengowatcher.web as web_module
from gengowatcher.config import AppConfig
from gengowatcher.state import AppState


@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    import logging

    return logging.getLogger("test")


@pytest.fixture
def mock_config(tmp_path):
    """Create a mock config."""
    config = MagicMock(spec=AppConfig)

    def mock_get(section, option, *args, **kwargs):
        fallback = kwargs.get("fallback", args[0] if args else "test_value")
        return {
            ("Watcher", "check_interval"): 60,
            ("Paths", "all_entries_log"): str(tmp_path / "test_entries.csv"),
            ("WebServer", "auth_token"): "test_token_12345",
        }.get((section, option), fallback)

    config.get.side_effect = mock_get
    config.getint.side_effect = lambda *_, **__: 60
    config.getboolean.side_effect = lambda *_, **__: False
    config.getfloat.side_effect = lambda *_, **__: 0.0
    config.config = {
        "Watcher": {"check_interval": 60},
        "WebSocket": {"enable_websocket": True},
    }
    return config


@pytest.fixture
def mock_state():
    """Create a mock state."""
    state = MagicMock(spec=AppState)
    state.get_recent_jobs.return_value = [
        {
            "id": "123",
            "title": "Test Job",
            "reward": 10.50,
            "currency": "USD",
            "url": "http://example.com/123",
            "timestamp": 1234567890.0,
            "source": "rss",
        }
    ]
    return state


@pytest.fixture
def web_api(mock_config, mock_state, mock_logger):
    """Create a WebAPI instance."""
    with patch("gengowatcher.web.GengoWatcher"):
        api = WebAPI(mock_config, mock_state, mock_logger)
        api.watcher.shutdown_event.is_set.return_value = False
        api.watcher.websocket_status = "Live"
        api.watcher.rss_action = "Checking"
        api.watcher.last_check_time = 1234567890.0
        api.watcher.next_check_time = 1234567950.0
        api.watcher.session_new_entries = 5
        api.watcher.session_total_value = 50.00
        api.watcher.start_time = 1234567800.0
        api.watcher.failure_count = 0
        api.watcher.get_cancellation_stats.return_value = None
        yield api


class TestAPIAuthenticator:
    """Test API authentication."""

    def test_authenticator_with_provided_key(self):
        """Test authenticator with provided API key."""
        auth = APIAuthenticator(api_key="test_key_123")
        assert auth.api_key == "test_key_123"

    def test_authenticator_generates_key(self):
        """Test authenticator generates key if not provided."""
        auth = APIAuthenticator()
        assert auth.api_key is not None
        assert len(auth.api_key) > 20

    def test_get_api_key(self):
        """Test get_api_key method."""
        auth = APIAuthenticator(api_key="my_secret_key")
        assert auth.get_api_key() == "my_secret_key"


class TestPydanticModels:
    """Test Pydantic model validation."""

    def test_job_entry_validation_success(self):
        """Test valid JobEntry."""
        job = JobEntry(
            id="123",
            title="Test Job",
            reward=10.50,
            currency="USD",
            url="http://example.com/123",
            timestamp=1234567890.0,
            source="rss",
        )
        assert job.id == "123"
        assert job.reward == 10.50

    def test_job_entry_empty_string_validation(self):
        """Test JobEntry rejects empty strings."""
        with pytest.raises(ValueError):
            JobEntry(
                id="",
                title="Test",
                reward=10.0,
                currency="USD",
                url="http://example.com",
                timestamp=1234567890.0,
                source="rss",
            )

    def test_job_entry_negative_reward_validation(self):
        """Test JobEntry rejects negative reward."""
        with pytest.raises(ValueError):
            JobEntry(
                id="123",
                title="Test",
                reward=-10.0,
                currency="USD",
                url="http://example.com",
                timestamp=1234567890.0,
                source="rss",
            )

    def test_job_entry_invalid_timestamp(self):
        """Test JobEntry rejects invalid timestamp."""
        with pytest.raises(ValueError):
            JobEntry(
                id="123",
                title="Test",
                reward=10.0,
                currency="USD",
                url="http://example.com",
                timestamp=-1.0,
                source="rss",
            )

    def test_watcher_status_validation(self):
        """Test WatcherStatus validation."""
        status = WatcherStatus(
            is_running=True,
            websocket_status="Live",
            rss_status="Checking",
            last_check_time=1234567890.0,
            next_check_time=1234567950.0,
            session_stats={"uptime": 100},
            failure_count=0,
        )
        assert status.is_running is True
        assert status.websocket_status == "Live"

    def test_config_section_validation(self):
        """Test ConfigSection validation."""
        section = ConfigSection(section="Watcher", options={"check_interval": 60})
        assert section.section == "Watcher"
        assert section.options["check_interval"] == 60

    def test_config_section_empty_name_validation(self):
        """Test ConfigSection rejects empty section name."""
        with pytest.raises(ValueError):
            ConfigSection(section="", options={})

    def test_command_request_validation(self):
        """Test CommandRequest validation."""
        cmd = CommandRequest(command="check", args=[])
        assert cmd.command == "check"
        assert cmd.args == []

    def test_command_request_invalid_command(self):
        """Test CommandRequest rejects invalid command."""
        with pytest.raises(ValueError):
            CommandRequest(command="invalid_command", args=[])

    def test_command_request_valid_commands(self):
        """Test all valid commands."""
        valid_commands = ["check", "pause", "resume", "cancel", "ping", "notify"]
        for cmd in valid_commands:
            request = CommandRequest(command=cmd, args=[])
            assert request.command == cmd

    def test_pagination_params_defaults(self):
        """Test PaginationParams default values."""
        params = PaginationParams()
        assert params.page == 1
        assert params.limit == 50

    def test_pagination_params_invalid_page(self):
        """Test PaginationParams rejects invalid page."""
        with pytest.raises(ValueError):
            PaginationParams(page=0, limit=50)

    def test_pagination_params_limit_exceeds_max(self):
        """Test PaginationParams rejects limit > 100."""
        with pytest.raises(ValueError):
            PaginationParams(page=1, limit=101)


class TestWebAPIInitialization:
    """Test WebAPI initialization."""

    def test_web_api_initialization(self, mock_config, mock_state, mock_logger):
        """Test WebAPI initialization."""
        with patch("gengowatcher.web.GengoWatcher") as mock_watcher_class:
            with patch("threading.Thread") as mock_thread:
                api = WebAPI(mock_config, mock_state, mock_logger)
                assert api.config == mock_config
                assert api.state == mock_state
                assert api.logger == mock_logger
                mock_watcher_class.assert_called_once()
                mock_thread.assert_called_once()

    def test_web_api_reuses_shared_watcher_without_starting_thread(
        self, mock_config, mock_state, mock_logger
    ):
        """Shared watcher mode must not create a duplicate monitor thread."""
        shared_watcher = MagicMock()

        with patch("gengowatcher.web.GengoWatcher") as mock_watcher_class:
            with patch("threading.Thread") as mock_thread:
                api = WebAPI(
                    mock_config,
                    mock_state,
                    mock_logger,
                    watcher=shared_watcher,
                    start_watcher_thread=False,
                )

        assert api.watcher is shared_watcher
        mock_watcher_class.assert_not_called()
        mock_thread.assert_not_called()

    def test_shutdown_does_not_stop_shared_watcher(
        self, mock_config, mock_state, mock_logger
    ):
        """Runtime-owned watchers should not be shut down by the web wrapper."""
        shared_watcher = MagicMock()
        api = WebAPI(
            mock_config,
            mock_state,
            mock_logger,
            watcher=shared_watcher,
            start_watcher_thread=False,
        )

        api.shutdown()

        shared_watcher.handle_exit.assert_not_called()

    def test_run_web_server_requires_complete_runtime_context(
        self, mock_config, mock_state
    ):
        with pytest.raises(ValueError, match="config and state"):
            run_web_server(config=mock_config)

        with pytest.raises(ValueError, match="config and state"):
            run_web_server(state=mock_state)

    def test_run_web_server_stores_shared_runtime_context(
        self, mock_config, mock_state, mock_logger
    ):
        shared_watcher = MagicMock()
        try:
            with patch("gengowatcher.web.uvicorn.run") as mock_uvicorn_run:
                run_web_server(
                    host="127.0.0.1",
                    port=37181,
                    config=mock_config,
                    state=mock_state,
                    logger=mock_logger,
                    watcher=shared_watcher,
                    start_watcher_thread=False,
                )

            assert web_module.shared_runtime_context == {
                "config": mock_config,
                "state": mock_state,
                "logger": mock_logger,
                "watcher": shared_watcher,
                "start_watcher_thread": False,
            }
            mock_uvicorn_run.assert_called_once_with(
                web_module.app,
                host="127.0.0.1",
                port=37181,
                reload=False,
                log_level="info",
            )
        finally:
            web_module.shared_runtime_context = None

    def test_web_api_thread_safety_locks(self, mock_config, mock_state, mock_logger):
        """Test that thread safety locks are created."""
        with patch("gengowatcher.web.GengoWatcher"):
            api = WebAPI(mock_config, mock_state, mock_logger)
            assert hasattr(api, "_status_lock")
            assert hasattr(api, "_connections_lock")
            assert hasattr(api, "_jobs_lock")


class TestManagedWebServer:
    def test_tui_mode_disables_uvicorn_terminal_logging(self):
        server = ManagedWebServer(terminal_logging=False)

        with (
            patch("gengowatcher.web.uvicorn.Config") as config_class,
            patch("gengowatcher.web.uvicorn.Server"),
            patch("gengowatcher.web.threading.Thread") as thread_class,
        ):
            thread_class.return_value = MagicMock()
            server.start()

        assert config_class.call_args.kwargs["log_config"] is None
        assert config_class.call_args.kwargs["access_log"] is False

    def test_web_only_mode_keeps_uvicorn_terminal_logging(self):
        server = ManagedWebServer(terminal_logging=True)

        with (
            patch("gengowatcher.web.uvicorn.Config") as config_class,
            patch("gengowatcher.web.uvicorn.Server"),
            patch("gengowatcher.web.threading.Thread") as thread_class,
        ):
            thread_class.return_value = MagicMock()
            server.start()

        assert "log_config" not in config_class.call_args.kwargs
        assert "access_log" not in config_class.call_args.kwargs


class TestWebAPIStatus:
    """Test WebAPI status retrieval."""

    def test_get_status(self, web_api):
        """Test get_status returns WatcherStatus."""
        status = web_api.get_status()
        assert isinstance(status, WatcherStatus)
        assert status.is_running is True
        assert status.websocket_status == "Live"
        assert status.rss_status == "Checking"

    def test_get_status_with_datetime_last_check(self, web_api):
        """Test get_status with datetime last_check_time."""
        import datetime

        web_api.watcher.last_check_time = datetime.datetime.fromtimestamp(1234567890.0)
        status = web_api.get_status()
        assert status.last_check_time is not None

    def test_get_status_session_stats(self, web_api):
        """Test session stats calculation."""
        import time

        web_api.watcher.start_time = time.time() - 3600  # 1 hour ago
        status = web_api.get_status()
        assert "uptime" in status.session_stats
        assert status.session_stats["uptime"] > 3500


class TestWebAPIJobRetrieval:
    """Test job retrieval from WebAPI."""

    def test_get_recent_jobs_basic(self, web_api):
        """Test basic job retrieval."""
        result = web_api.get_recent_jobs(limit=50, page=1)
        assert "jobs" in result
        assert "pagination" in result
        assert isinstance(result["jobs"], list)

    def test_get_recent_jobs_pagination(self, web_api):
        """Test pagination."""
        # Mock multiple jobs
        jobs = [
            {
                "id": str(i),
                "title": f"Job {i}",
                "reward": 10.0 * i,
                "currency": "USD",
                "url": f"http://example.com/{i}",
                "timestamp": 1234567890.0 + i,
                "source": "rss",
            }
            for i in range(100)
        ]
        web_api.state.get_recent_jobs.return_value = jobs

        result = web_api.get_recent_jobs(limit=10, page=2)
        assert result["pagination"]["page"] == 2
        assert result["pagination"]["limit"] == 10

    def test_get_recent_jobs_with_invalid_data(self, web_api):
        """Test handling of invalid job data."""
        web_api.state.get_recent_jobs.return_value = [
            {
                "id": "valid",
                "title": "Valid",
                "reward": 10.0,
                "currency": "USD",
                "url": "http://example.com",
                "timestamp": 123.0,
                "source": "rss",
            },
            {"id": "", "title": "Invalid"},  # Invalid job
        ]

        result = web_api.get_recent_jobs(limit=50, page=1)
        assert len(result["jobs"]) == 1  # Only valid job

    def test_get_recent_jobs_exception_handling(self, web_api):
        """Test exception handling in get_recent_jobs."""
        web_api.state.get_recent_jobs.side_effect = Exception("DB error")

        result = web_api.get_recent_jobs(limit=50, page=1)
        assert result["jobs"] == []
        assert result["pagination"]["total"] == 0


class TestWebAPICSVJobs:
    """Test CSV job retrieval."""

    def test_get_jobs_from_csv_file_not_found(self, web_api):
        """Test when CSV file doesn't exist."""
        web_api.config.get.side_effect = lambda s, k, **kw: (
            "/nonexistent/file.csv"
            if (s, k) == ("Paths", "all_entries_log")
            else kw.get("fallback", "")
        )

        result = web_api.get_jobs_from_csv(limit=50, page=1)
        assert result["jobs"] == []
        assert result["pagination"]["total"] == 0

    def test_get_jobs_from_csv_with_data(self, web_api):
        """Test reading jobs from CSV."""
        csv_content = """timestamp,title,reward,link,summary
2024-01-01T12:00:00,Test Job,10.50,http://example.com/jobs/details/123,Summary
2024-01-01T13:00:00,Another Job,25.00,http://example.com/jobs/details/456,Summary2
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = f.name

        try:
            web_api.config.get.side_effect = lambda s, k, **kw: (
                csv_path
                if (s, k) == ("Paths", "all_entries_log")
                else kw.get("fallback", "")
            )

            result = web_api.get_jobs_from_csv(limit=50, page=1)
            assert len(result["jobs"]) == 2
            assert result["pagination"]["total"] == 2
        finally:
            import os

            os.unlink(csv_path)

    def test_get_jobs_from_csv_with_filters(self, web_api):
        """Test CSV filtering."""
        csv_content = """timestamp,title,reward,link,summary
2024-01-01T12:00:00,Test Job,10.50,http://example.com/jobs/details/123,Summary
2024-01-01T13:00:00,Another Job,25.00,http://example.com/jobs/details/456,Summary2
2024-01-01T14:00:00,Third Job,5.00,http://example.com/jobs/details/789,Summary3
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = f.name

        try:
            web_api.config.get.side_effect = lambda s, k, **kw: (
                csv_path
                if (s, k) == ("Paths", "all_entries_log")
                else kw.get("fallback", "")
            )

            result = web_api.get_jobs_from_csv(limit=50, page=1, min_reward=10.0)
            assert len(result["jobs"]) == 2  # Should exclude 5.00 job
        finally:
            import os

            os.unlink(csv_path)


class TestWebAPIJobManagement:
    """Test job management operations."""

    def test_add_job(self, web_api):
        """Test adding a job."""
        web_api.add_job("123", "Test Job", 10.50, "http://example.com/123", "rss")
        web_api.state.add_job.assert_called_once()

    def test_add_job_exception_handling(self, web_api):
        """Test exception handling in add_job."""
        web_api.state.add_job.side_effect = Exception("State error")
        # Should not raise exception
        web_api.add_job("123", "Test", 10.0, "http://example.com", "rss")

    @pytest.mark.asyncio
    async def test_accept_job_success(self, web_api):
        """Test successful job acceptance."""
        web_api.watcher.job_acceptance_engine = MagicMock()
        web_api.watcher.job_acceptance_engine._attempt_job_acceptance = AsyncMock(
            return_value=True
        )

        result = await web_api.accept_job("123")
        assert result is True

    @pytest.mark.asyncio
    async def test_accept_job_not_found(self, web_api):
        """Test job acceptance when job not found."""
        web_api.state.get_recent_jobs.return_value = []

        result = await web_api.accept_job("999")
        assert result is False

    @pytest.mark.asyncio
    async def test_accept_job_no_engine(self, web_api):
        """Test job acceptance when engine not available."""
        del web_api.watcher.job_acceptance_engine

        result = await web_api.accept_job("123")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_current_job(self, web_api):
        """Test job cancellation."""
        web_api.watcher.cancel_current_job_async = AsyncMock(return_value=True)

        result = await web_api.cancel_current_job()
        assert result is True


class TestWebAPIConfig:
    """Test configuration management."""

    def test_get_config(self, web_api):
        """Test getting config."""
        sections = web_api.get_config()
        assert isinstance(sections, list)
        assert len(sections) > 0
        assert isinstance(sections[0], ConfigSection)

    def test_update_config_success(self, web_api):
        """Test successful config update."""
        result = web_api.update_config("Watcher", "check_interval", "120")
        assert result is True
        web_api.watcher.set_config_value.assert_called_once()

    def test_update_config_failure(self, web_api):
        """Test config update failure."""
        web_api.watcher.set_config_value.side_effect = Exception("Config error")

        result = web_api.update_config("Watcher", "check_interval", "120")
        assert result is False


class TestWebAPICommands:
    """Test command execution."""

    def test_execute_command_check(self, web_api):
        """Test check command."""
        result = web_api.execute_command("check")
        assert result["status"] == "success"
        web_api.watcher.check_now_event.set.assert_called_once()

    def test_execute_command_pause(self, web_api):
        """Test pause command."""
        result = web_api.execute_command("pause")

        assert result["status"] == "success"
        web_api.watcher.pause_monitoring.assert_called_once()

    def test_execute_command_resume(self, web_api):
        """Test resume command."""
        result = web_api.execute_command("resume")

        assert result["status"] == "success"
        web_api.watcher.resume_monitoring.assert_called_once()

    def test_execute_command_cancel(self, web_api):
        """Test cancel command."""
        web_api.watcher.cancel_current_job_sync.return_value = True

        result = web_api.execute_command("cancel")
        assert result["status"] == "success"

    def test_execute_command_cancel_failure(self, web_api):
        """Test cancel command when no job to cancel."""
        web_api.watcher.cancel_current_job_sync.return_value = False

        result = web_api.execute_command("cancel")
        assert result["status"] == "error"

    def test_execute_command_websocket_test_commands(self, web_api):
        """Test websocket diagnostic commands."""
        for command in ("ping", "notify"):
            result = web_api.execute_command(command)

            assert result["status"] == "success"
            web_api.watcher.queue_websocket_test_command.assert_called_with(command)

    def test_execute_command_unknown(self, web_api):
        """Test unknown command."""
        result = web_api.execute_command("unknown_command")
        assert result["status"] == "error"


class TestWebAPIShutdown:
    """Test shutdown."""

    def test_shutdown(self, web_api):
        """Test shutdown."""
        web_api.shutdown()
        web_api.watcher.handle_exit.assert_called_once()

    def test_shutdown_restores_previous_api_event_callback(self, web_api):
        previous = MagicMock()
        web_api._previous_api_event_callback = previous
        web_api.watcher.on_api_event_callback = web_api._api_event_callback

        web_api.shutdown()

        assert web_api.watcher.on_api_event_callback is previous


class TestBroadcastStatusUpdate:
    """Test WebSocket broadcasting."""

    @pytest.mark.asyncio
    async def test_broadcast_status_update_no_connections(self, web_api):
        """Test broadcasting with no connections."""
        # Should not raise exception
        await web_api.broadcast_status_update()

    @pytest.mark.asyncio
    async def test_broadcast_status_update_with_connections(self, web_api):
        """Test broadcasting to active connections."""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        web_api._active_connections = [mock_ws1, mock_ws2]

        await web_api.broadcast_status_update()

        mock_ws1.send_json.assert_called_once()
        mock_ws2.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_status_update_removes_disconnected(self, web_api):
        """Test removal of disconnected clients."""
        mock_ws_good = AsyncMock()
        mock_ws_bad = AsyncMock()
        mock_ws_bad.send_json.side_effect = Exception("Disconnected")

        web_api._active_connections = [mock_ws_good, mock_ws_bad]

        await web_api.broadcast_status_update()

        assert mock_ws_bad not in web_api._active_connections
        assert mock_ws_good in web_api._active_connections

    @pytest.mark.asyncio
    async def test_publish_api_event_records_and_broadcasts(self, web_api):
        """Lifecycle events should be stored and sent to websocket clients."""
        mock_ws = AsyncMock()
        web_api._active_connections = [mock_ws]
        web_api._event_loop = asyncio.get_running_loop()

        event = web_api.publish_api_event(
            "job.discovered",
            {"id": "123", "title": "JA > EN", "reward": 10.5},
        )
        await asyncio.sleep(0)

        assert event["type"] == "job.discovered"
        assert web_api.get_recent_events()[-1]["event_id"] == event["event_id"]
        mock_ws.send_json.assert_called()

    def test_watcher_api_event_acceptance_starts_user_file_wait(self, web_api):
        """Accepted jobs without a user file should move to waiting_for_file."""
        web_api.state.get_job.return_value = {
            "id": "123",
            "title": "JA > EN",
            "reward": 10.5,
            "url": "https://gengo.com/t/workbench/123",
            "timestamp": 1234567890.0,
            "source": "browser_worker",
            "accepted": True,
            "accepted_source_text": "Source from workbench JSON",
        }

        web_api._handle_watcher_api_event("job.accepted", {"id": "123"})

        event_types = [event["type"] for event in web_api.get_recent_events()]
        assert "job.accepted" in event_types
        assert "job.file_pending" in event_types
        web_api.state.update_job.assert_any_call(
            "123",
            {
                "file_state": "pending",
                "workflow_state": "waiting_for_file",
                "workflow_file_mode": "user",
            },
        )


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_get_recent_jobs_zero_total(self, web_api):
        """Test with no jobs."""
        web_api.state.get_recent_jobs.return_value = []

        result = web_api.get_recent_jobs(limit=50, page=1)
        assert result["pagination"]["total"] == 0
        assert result["pagination"]["pages"] == 0

    def test_get_recent_jobs_page_beyond_available(self, web_api):
        """Test requesting page beyond available data."""
        jobs = [
            {
                "id": str(i),
                "title": f"Job {i}",
                "reward": 10.0,
                "currency": "USD",
                "url": f"http://example.com/{i}",
                "timestamp": 123.0,
                "source": "rss",
            }
            for i in range(10)
        ]
        web_api.state.get_recent_jobs.return_value = jobs

        result = web_api.get_recent_jobs(limit=10, page=5)
        assert len(result["jobs"]) == 0  # No jobs on page 5

    def test_get_config_with_mixed_types(self, web_api):
        """Test config with different value types."""
        web_api.config.config = {
            "Section1": {
                "bool_val": True,
                "int_val": 42,
                "float_val": 3.14,
                "str_val": "text",
            }
        }

        sections = web_api.get_config()
        assert len(sections) == 1

    @pytest.mark.asyncio
    async def test_accept_job_exception_handling(self, web_api):
        """Test exception handling in accept_job."""
        web_api.watcher.job_acceptance_engine = MagicMock()
        web_api.watcher.job_acceptance_engine._attempt_job_acceptance = AsyncMock(
            side_effect=Exception("Acceptance error")
        )

        result = await web_api.accept_job("123")
        assert result is False


class TestRegressionCases:
    """Test regression cases and fixes."""

    def test_status_with_none_last_check_time(self, web_api):
        """Test status when last_check_time is None."""
        web_api.watcher.last_check_time = None

        status = web_api.get_status()
        assert status.last_check_time is None

    def test_get_jobs_from_csv_empty_file(self, web_api):
        """Test CSV with only header."""
        csv_content = """timestamp,title,reward,link,summary
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = f.name

        try:
            web_api.config.get.side_effect = lambda s, k, **kw: (
                csv_path
                if (s, k) == ("Paths", "all_entries_log")
                else kw.get("fallback", "")
            )

            result = web_api.get_jobs_from_csv(limit=50, page=1)
            assert result["pagination"]["total"] == 0
        finally:
            import os

            os.unlink(csv_path)

    def test_command_execution_with_exception(self, web_api):
        """Test command execution exception handling."""
        web_api.watcher.check_now_event.set.side_effect = Exception("Event error")

        result = web_api.execute_command("check")
        assert result["status"] == "error"

    def test_file_storage_round_trip(
        self, mock_config, mock_state, mock_logger, tmp_path
    ):
        """Uploaded files should be listed and resolved from local storage."""
        watcher = MagicMock()
        watcher.shutdown_event.is_set.return_value = False
        watcher.get_cancellation_stats.return_value = None
        watcher.start_time = 123.0
        watcher.websocket_status = "Live"
        watcher.rss_action = "Checking"
        watcher.session_new_entries = 0
        watcher.session_total_value = 0.0
        watcher.failure_count = 0
        watcher.next_check_time = 0.0
        watcher.last_check_time = None

        mock_config.get.side_effect = lambda s, k, **kw: {
            ("Paths", "file_storage_dir"): str(tmp_path / "files"),
            ("Paths", "all_entries_log"): str(tmp_path / "entries.csv"),
            ("WebServer", "auth_token"): "test_token_12345",
        }.get((s, k), kw.get("fallback", ""))

        with patch("gengowatcher.web.GengoWatcher", return_value=watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)

            entry = api.save_uploaded_file(
                "release-notes.txt",
                b"ready for release",
                content_type="text/plain",
                job_id="job-12345",
                tier="pro",
                word_count=320,
                value=16.0,
            )

            listed = api.list_files()
            resolved = api.get_file_path(entry.stored_name)

            assert listed
            assert listed[0].stored_name == entry.stored_name
            assert listed[0].original_name == "release-notes.txt"
            assert listed[0].job_id == "job-12345"
            assert listed[0].tier == "pro"
            assert listed[0].word_count == 320
            assert listed[0].value == 16.0
            assert entry.stored_name.endswith("_job-12345_pro_320w_16.00.txt")
            assert resolved is not None
            assert resolved.read_text(encoding="utf-8") == "ready for release"

    def test_file_storage_preserves_safe_spaces_and_parentheses_without_metadata(
        self, mock_config, mock_state, mock_logger, tmp_path
    ):
        """Common safe punctuation should survive filename sanitization."""
        watcher = MagicMock()
        watcher.shutdown_event.is_set.return_value = False
        watcher.get_cancellation_stats.return_value = None
        watcher.start_time = 123.0
        watcher.websocket_status = "Live"
        watcher.rss_action = "Checking"
        watcher.session_new_entries = 0
        watcher.session_total_value = 0.0
        watcher.failure_count = 0
        watcher.next_check_time = 0.0
        watcher.last_check_time = None

        mock_config.get.side_effect = lambda s, k, **kw: {
            ("Paths", "file_storage_dir"): str(tmp_path / "files"),
            ("Paths", "all_entries_log"): str(tmp_path / "entries.csv"),
            ("WebServer", "auth_token"): "test_token_12345",
        }.get((s, k), kw.get("fallback", ""))

        with patch("gengowatcher.web.GengoWatcher", return_value=watcher):
            api = WebAPI(mock_config, mock_state, mock_logger)
            entry = api.save_uploaded_file(
                "Release Notes (final).txt",
                b"ready for release",
                content_type="text/plain",
            )

            assert entry.stored_name == "Release Notes (final).txt"
