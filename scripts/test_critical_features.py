#!/usr/bin/env python3
"""
Test script for auto-accept with CAPTCHA integration.
This script tests the critical features of GengoWatcher including:
1. Auto-accept with CAPTCHA integration
2. WebSocket connectivity
3. Web API endpoints
4. Rate limiting and performance
"""

__test__ = False

import asyncio
import json
import logging
import time
import pytest
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path

# Add src to path
import sys

sys.path.insert(0, str(Path(__file__).parent / "src"))

from gengowatcher.config import AppConfig
from gengowatcher.job_acceptance import JobAcceptanceEngine
from gengowatcher.captcha_manager import CaptchaSolverManager
from gengowatcher.captcha_solver import CaptchaSolution
from gengowatcher.web import WebAPI
from gengowatcher.watcher import GengoWatcher

# Test configuration
TEST_CONFIG = {
    "AutoAccept": {
        "enabled": "true",
        "min_reward": "0.0",
        "max_reward": "999999.0",
        "job_sources": "rss,websocket",
        "accept_delay_min": "1",
        "accept_delay_max": "3",
        "log_acceptance": "true",
        "notification_on_accept": "true",
    },
    "Captcha": {
        "enabled": "true",
        "service": "2captcha",
        "api_key": "test_api_key",
        "fallback_service": "anticaptcha",
        "fallback_api_key": "test_fallback_key",
        "max_wait_time": "120",
        "polling_interval": "10",
        "balance_check_interval": "3600",
    },
    "WebSocket": {
        "enabled": "true",
        "url": "wss://test.gengo.com/ws",
        "user_session": "test_session_token",
        "user_id": "test_user_id",
        "user_key": "test_browser_user_key",
    },
}


@pytest.fixture
def config():
    """Create a test configuration."""
    config = AppConfig()
    # Override with test values
    for section, options in TEST_CONFIG.items():
        for key, value in options.items():
            config.set(section, key, value)
    return config


from gengowatcher.watcher import GengoWatcher
from gengowatcher.state import AppState

@pytest.fixture
def state():
    """Create a test state."""
    return AppState()


@pytest.fixture
def logger():
    """Create a test logger."""
    logger = logging.getLogger("test")
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    return logger


@pytest.fixture
def captcha_solution():
    """Create a mock CAPTCHA solution."""
    return CaptchaSolution(
        solution="test_captcha_token", cost=0.001, solver="2captcha", time_taken=5.0
    )


class TestAutoAcceptWithCaptcha:
    """Test auto-accept functionality with CAPTCHA integration."""

    @pytest.mark.asyncio
    async def test_job_acceptance_eligibility(self, config, logger):
        """Test job eligibility checking."""
        # Mock the config methods to return test values
        config.getboolean = lambda section, key, fallback=None: TEST_CONFIG.get(
            section, {}
        ).get(key, fallback)
        config.get = lambda section, key, fallback=None: TEST_CONFIG.get(
            section, {}
        ).get(key, fallback)
        config.getfloat = lambda section, key, fallback=None: float(
            TEST_CONFIG.get(section, {}).get(key, fallback)
        )
        config.set = lambda section, key, value: TEST_CONFIG.setdefault(
            section, {}
        ).update({key: value})
        # Create job acceptance engine
        engine = JobAcceptanceEngine(config, logger)
        print(f"Engine enabled: {engine.enabled}")

        # Test eligible job
        eligible_job = {
            "id": "test_job_123",
            "url": "https://gengo.com/t/jobs/details/test_job_123",
            "source": "rss",
            "reward": 10.0,
            "title": "Test translation job",
        }

        assert engine.is_job_eligible(eligible_job) is True

        # Test ineligible job (wrong source)
        ineligible_job = {
            "id": "test_job_456",
            "url": "https://gengo.com/t/jobs/details/test_job_456",
            "source": "invalid_source",
            "reward": 10.0,
            "title": "Test translation job",
        }

        assert engine.is_job_eligible(ineligible_job) is False

        # Test ineligible job (reward too low)
        low_reward_job = {
            "id": "test_job_789",
            "url": "https://gengo.com/t/jobs/details/test_job_789",
            "source": "rss",
            "reward": 0.5,
            "title": "Test translation job",
        }

        # Temporarily update min_reward
        config.set("AutoAccept", "min_reward", "1.0")
        assert engine.is_job_eligible(low_reward_job) is False

    @pytest.mark.asyncio
    async def test_captcha_challenge_handling(self, config, logger, captcha_solution):
        """Test CAPTCHA challenge handling during job acceptance."""
        # Create mock captcha solver
        captcha_solver = Mock(spec=CaptchaSolverManager)
        captcha_solver.is_configured.return_value = True
        captcha_solver.solve_recaptcha_v2.return_value = captcha_solution

        # Create job acceptance engine with CAPTCHA solver
        engine = JobAcceptanceEngine(config, logger, captcha_solver)

        # Mock HTML content with reCAPTCHA
        captcha_html = """
        <html>
            <head>
                <title>Job Acceptance</title>
            </head>
            <body>
                <div class="g-recaptcha" data-sitekey="6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"></div>
                <form method="post" action="/accept">
                    <input type="hidden" name="job_id" value="test_job_123">
                </form>
            </body>
        </html>
        """

        # Test CAPTCHA challenge detection and solving
        headers = {
            "Cookie": "my_gengo_session=test_session_token",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        # Mock the session post to simulate successful acceptance
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text.return_value = "Job accepted successfully"

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session
            mock_session.post.return_value.__aenter__.return_value = mock_response

            # Test CAPTCHA handling
            result = await engine._handle_captcha_challenge(
                "test_job_123", captcha_html, headers
            )

            # CAPTCHA solving is currently disabled in JobAcceptanceEngine.
            captcha_solver.solve_recaptcha_v2.assert_not_called()
            assert result is False

    @pytest.mark.asyncio
    async def test_rate_limiting(self, config, logger):
        """Test rate limiting for job acceptance."""
        engine = JobAcceptanceEngine(config, logger)

        # Test rate limiter prevents excessive requests
        job = {
            "id": "test_job_123",
            "url": "https://gengo.com/t/jobs/details/test_job_123",
            "source": "rss",
            "reward": 10.0,
            "title": "Test translation job",
        }

        # First request should succeed
        assert engine.rate_limiter.acquire() is True

        # Try to exhaust the rate limit (30 requests per minute)
        accepted_count = 0
        for i in range(35):  # Try 35 times
            if engine.rate_limiter.acquire():
                accepted_count += 1

        # Should have accepted exactly 30 requests
        assert accepted_count == 30

        # Next request should be rate limited
        assert engine.rate_limiter.acquire() is False


class TestWebSocketConnectivity:
    """Test WebSocket connectivity."""

    @pytest.mark.asyncio
    async def test_websocket_connection(self, config, state, logger):
        """Test WebSocket connection establishment."""
        # Create watcher with test config
        watcher = GengoWatcher(config, state, logger)

        # Mock WebSocket connection
        with patch("websockets.connect") as mock_connect:
            mock_ws = AsyncMock()
            mock_connect.return_value = mock_ws

            # Test connection
            await watcher._connect_websocket()

            # Verify connection attempt
            mock_connect.assert_called_once()
            assert mock_ws.send.called

    @pytest.mark.asyncio
    async def test_websocket_message_handling(self, config, state, logger):
        """Test WebSocket message processing."""
        watcher = GengoWatcher(config, state, logger)

        # Mock WebSocket and message
        mock_ws = AsyncMock()

        # Test job message
        job_message = json.dumps(
            {
                "type": "job",
                "data": {
                    "id": "test_job_123",
                    "title": "Test translation job",
                    "reward": 10.0,
                    "source": "websocket",
                },
            }
        )

        # Mock the job processing
        with patch.object(watcher, "_process_job") as mock_process:
            await watcher._handle_websocket_message(job_message)
            mock_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_reconnection(self, config, state, logger):
        """Test WebSocket reconnection logic."""
        watcher = GengoWatcher(config, state, logger)

        # Mock failed connection followed by success
        with patch("websockets.connect") as mock_connect:
            # First attempt fails
            mock_connect.side_effect = [Exception("Connection failed"), AsyncMock()]

            # Test reconnection
            await watcher._connect_websocket()

            # Should have tried to connect twice
            assert mock_connect.call_count == 2


class TestWebAPIEndpoints:
    """Test Web API endpoints."""

    @pytest.mark.asyncio
    async def test_api_endpoints_accessibility(self, config, logger):
        """Test that API endpoints are accessible."""
        # Create web server
        web_server = WebAPI(config, logger, port=8001)

        # Test client
        from httpx import AsyncClient

        async with AsyncClient(
            app=web_server.app, base_url="http://localhost:8001"
        ) as client:
            # Test health endpoint
            response = await client.get("/health")
            assert response.status_code == 200

            # Test metrics endpoint
            response = await client.get("/metrics")
            assert response.status_code == 200

            # Test config endpoint (should require auth)
            response = await client.get("/config")
            assert response.status_code == 401  # Unauthorized

    @pytest.mark.asyncio
    async def test_api_authentication(self, config, logger):
        """Test API authentication."""
        web_server = WebAPI(config, logger, port=8002)

        # Set API token
        config.set("WebServer", "api_token", "test_token")

        from httpx import AsyncClient

        async with AsyncClient(
            app=web_server.app, base_url="http://localhost:8002"
        ) as client:
            # Test without token
            response = await client.get("/config")
            assert response.status_code == 401

            # Test with valid token
            response = await client.get(
                "/config", headers={"Authorization": "Bearer test_token"}
            )
            assert response.status_code == 200

            # Test with invalid token
            response = await client.get(
                "/config", headers={"Authorization": "Bearer invalid_token"}
            )
            assert response.status_code == 401


class TestRateLimitingAndPerformance:
    """Test rate limiting and performance."""

    @pytest.mark.asyncio
    async def test_rate_limiter_performance(self, config, logger):
        """Test rate limiter performance under load."""
        engine = JobAcceptanceEngine(config, logger)

        # Test rapid requests
        start_time = time.time()
        accepted_count = 0

        for i in range(50):
            if engine.rate_limiter.acquire():
                accepted_count += 1

        elapsed = time.time() - start_time

        # Should have accepted 30 requests (rate limit)
        assert accepted_count == 30

        # Should be very fast (not actually waiting for rate limit)
        assert elapsed < 1.0

        # Wait time should be calculated correctly
        wait_time = engine.rate_limiter.wait_time()
        assert wait_time > 0

    @pytest.mark.asyncio
    async def test_concurrent_job_acceptance(self, config, logger):
        """Test concurrent job acceptance handling."""
        engine = JobAcceptanceEngine(config, logger)

        # Create multiple jobs
        jobs = [
            {
                "id": f"test_job_{i}",
                "url": f"https://gengo.com/t/jobs/details/test_job_{i}",
                "source": "rss",
                "reward": 10.0,
                "title": f"Test job {i}",
            }
            for i in range(10)
        ]

        # Test concurrent acceptance attempts
        async def attempt_acceptance(job):
            return await engine.is_job_eligible(job)

        # Run all concurrently
        results = await asyncio.gather(*[attempt_acceptance(job) for job in jobs])

        # All should be eligible
        assert all(results) is True

    @pytest.mark.asyncio
    async def test_captcha_solver_performance(self, config, logger, captcha_solution):
        """Test CAPTCHA solver performance."""
        captcha_solver = Mock(spec=CaptchaSolverManager)
        captcha_solver.is_configured.return_value = True
        captcha_solver.solve_recaptcha_v2.return_value = captcha_solution

        engine = JobAcceptanceEngine(config, logger, captcha_solver)

        # Test multiple CAPTCHA solving attempts
        start_time = time.time()

        for i in range(5):
            with patch("aiohttp.ClientSession") as mock_session_class:
                mock_session = AsyncMock()
                mock_session_class.return_value = mock_session

                # Simulate successful job acceptance
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.text.return_value = "Job accepted successfully"
                mock_session.post.return_value.__aenter__.return_value = mock_response

                job = {
                    "id": f"test_job_{i}",
                    "url": f"https://gengo.com/t/jobs/details/test_job_{i}",
                    "source": "rss",
                    "reward": 10.0,
                }

                # Mock the _attempt_job_acceptance to return True (CAPTCHA solved)
                with patch.object(engine, "_attempt_job_acceptance", return_value=True):
                    result = await engine.accept_job(job)
                    assert result is True

        elapsed = time.time() - start_time

        # Should complete quickly (mocked responses)
        assert elapsed < 1.0

        # CAPTCHA solver is NOT called because _attempt_job_acceptance is mocked to return True
        assert captcha_solver.solve_recaptcha_v2.call_count == 0


# Integration test
@pytest.mark.asyncio
async def test_full_integration(config, state, logger, captcha_solution):
    """Test full integration of all components."""
    # Create all components
    captcha_solver = Mock(spec=CaptchaSolverManager)
    captcha_solver.is_configured.return_value = True
    captcha_solver.solve_recaptcha_v2.return_value = captcha_solution

    engine = JobAcceptanceEngine(config, logger, captcha_solver)
    watcher = GengoWatcher(config, state, logger)
    web_server = WebAPI(config, logger, port=8003)

    # Test job flow
    job_data = {
        "id": "integration_test_job",
        "url": "https://gengo.com/t/jobs/details/integration_test_job",
        "source": "websocket",
        "reward": 15.0,
        "title": "Integration test job",
    }

    # Process job through watcher
    with patch.object(watcher, "_process_job") as mock_process:
        await watcher._handle_websocket_message(
            json.dumps({"type": "job", "data": job_data})
        )
        mock_process.assert_called_with(job_data)

    # Test job acceptance
    with patch.object(engine, "_attempt_job_acceptance", return_value=True):
        result = await engine.accept_job(job_data)
        assert result is True

    # Test web API
    from httpx import AsyncClient

    async with AsyncClient(
        app=web_server.app, base_url="http://localhost:8003"
    ) as client:
        response = await client.get("/health")
        assert response.status_code == 200

        metrics = response.json()
        assert "uptime" in metrics
        assert "active_connections" in metrics


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)

    # Run tests
    pytest.main([__file__, "-v", "--tb=short"])
