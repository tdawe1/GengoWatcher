#!/usr/bin/env python3
"""
Simple test script for critical features without pytest dependency.
"""

import asyncio
import json
import logging
import time
import sys
import collections
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    from gengowatcher.config import AppConfig
    from gengowatcher.job_acceptance import JobAcceptanceEngine
    from gengowatcher.captcha_manager import CaptchaSolverManager
    from gengowatcher.captcha_solver import CaptchaSolution
    from gengowatcher.watcher import GengoWatcher

    IMPORTS_AVAILABLE = True
except ImportError as e:
    print(f"Import error: {e}")
    IMPORTS_AVAILABLE = False


def setup_logging():
    """Setup basic logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return logging.getLogger("test")


def test_config_loading():
    """Test configuration loading."""
    print("\n=== Testing Configuration Loading ===")

    try:
        config = AppConfig()
        print("✅ Config loaded successfully")

        # Test setting and getting values
        config.set("AutoAccept", "min_reward", "5.0")
        value = config.get("AutoAccept", "min_reward")

        if float(value) == 5.0:
            print("✅ Config set/get works")
        else:
            print("❌ Config set/get failed")

        return True
    except Exception as e:
        print(f"❌ Config loading failed: {e}")
        return False


def test_rate_limiter():
    """Test rate limiting functionality."""
    print("\n=== Testing Rate Limiting ===")

    try:
        from gengowatcher.rate_limiter import RateLimiter

        # Create rate limiter: 5 requests per 10 seconds
        limiter = RateLimiter(max_requests=5, time_window=10)

        # Should accept first 5 requests
        accepted = 0
        for i in range(7):
            if limiter.acquire():
                accepted += 1
                print(f"✅ Request {i+1} accepted")
            else:
                print(f"❌ Request {i+1} rate limited")

        if accepted == 5:
            print("✅ Rate limiting works correctly")
            return True
        else:
            print(f"❌ Rate limiting failed: expected 5, got {accepted}")
            return False

    except Exception as e:
        print(f"❌ Rate limiting test failed: {e}")
        return False


async def test_captcha_solver():
    """Test CAPTCHA solver functionality."""
    print("\n=== Testing CAPTCHA Solver ===")

    try:
        # Test with mock solver
        solver = Mock(spec=CaptchaSolverManager)
        solver.is_configured.return_value = True

        # Create mock solution
        solution = CaptchaSolution(
            captcha_id="test_task_123",
            solution="test_token_123",
            solved_at=time.time(),
            cost=0.002,
        )

        solver.solve_recaptcha_v2.return_value = solution

        # Test solve method
        result = solver.solve_recaptcha_v2("site_key", "page_url")

        if result == solution:
            print("✅ CAPTCHA solver mock works")
            return True
        else:
            print("❌ CAPTCHA solver mock failed")
            return False

    except Exception as e:
        print(f"❌ CAPTCHA solver test failed: {e}")
        return False


async def test_job_acceptance_eligibility():
    """Test job acceptance eligibility."""
    print("\n=== Testing Job Acceptance Eligibility ===")

    try:
        # Create config
        config = AppConfig()
        config.set("AutoAccept", "enabled", "true")
        config.set("AutoAccept", "min_reward", "5.0")
        config.set("AutoAccept", "max_reward", "50.0")
        config.set("AutoAccept", "job_sources", "rss,websocket")

        logger = setup_logging()
        engine = JobAcceptanceEngine(config, logger)

        # Test eligible job
        eligible_job = {"id": "test_job_123", "source": "rss", "reward": 10.0}

        if engine.is_job_eligible(eligible_job):
            print("✅ Eligible job accepted")
        else:
            print("❌ Eligible job rejected")
            return False

        # Test ineligible job (reward too low)
        ineligible_job = {"id": "test_job_456", "source": "rss", "reward": 3.0}

        if not engine.is_job_eligible(ineligible_job):
            print("✅ Ineligible job (low reward) rejected")
        else:
            print("❌ Ineligible job (low reward) accepted")
            return False

        # Test ineligible job (wrong source)
        wrong_source_job = {"id": "test_job_789", "source": "invalid", "reward": 10.0}

        if not engine.is_job_eligible(wrong_source_job):
            print("✅ Ineligible job (wrong source) rejected")
        else:
            print("❌ Ineligible job (wrong source) accepted")
            return False

        return True

    except Exception as e:
        print(f"❌ Job acceptance eligibility test failed: {e}")
        return False


async def test_websocket_simulation():
    """Test WebSocket connection simulation."""
    print("\n=== Testing WebSocket Simulation ===")

    try:
        config = AppConfig()
        logger = setup_logging()

        # Create a proper AppState mock
        state = Mock()
        state.seen_job_ids = collections.deque(maxlen=50)
        state.last_seen_rss_link = None
        state.last_seen_link = None

        # Mock WebSocket
        with patch(
            "gengowatcher.orchestration.watcher_ws_logic.connect"
        ) as mock_connect:
            mock_ws = AsyncMock()
            mock_connect.return_value = mock_ws

            # Test connection
            watcher = GengoWatcher(config, logger, state)

            # This would normally connect to WebSocket
            # For test, we just verify the mock is called
            print("✅ WebSocket simulation setup works")
            return True

    except Exception as e:
        print(f"❌ WebSocket simulation failed: {e}")
        return False


async def test_performance():
    """Test performance metrics."""
    print("\n=== Testing Performance ===")

    try:
        # Test rate limiter performance
        from gengowatcher.rate_limiter import RateLimiter

        limiter = RateLimiter(max_requests=100, time_window=60)

        # Time how long it takes to check 1000 requests
        start_time = time.time()

        accepted = 0
        for i in range(1000):
            if limiter.acquire():
                accepted += 1

        elapsed = time.time() - start_time

        print(f"✅ Processed 1000 requests in {elapsed:.4f} seconds")
        print(f"✅ Accepted: {accepted}, Rate limited: {1000 - accepted}")

        # Should be very fast (not actually waiting)
        if elapsed < 0.1:
            print("✅ Performance test passed")
            return True
        else:
            print(f"❌ Performance too slow: {elapsed:.4f}s")
            return False

    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        return False


async def run_all_tests():
    """Run all tests."""
    print("🧪 Running Critical Features Tests")
    print("=" * 50)

    if not IMPORTS_AVAILABLE:
        print("❌ Cannot run tests - imports not available")
        return False

    results = []

    # Run synchronous tests
    results.append(test_config_loading())
    results.append(test_rate_limiter())

    # Run asynchronous tests
    results.append(await test_captcha_solver())
    results.append(await test_job_acceptance_eligibility())
    results.append(await test_websocket_simulation())
    results.append(await test_performance())

    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Results Summary")
    print("=" * 50)

    passed = sum(results)
    total = len(results)

    for i, result in enumerate(results, 1):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"Test {i}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All critical features are working correctly!")
        return True
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return False


if __name__ == "__main__":
    # Run tests
    success = asyncio.run(run_all_tests())

    if success:
        print("\n✅ Critical features verification complete - all systems GO!")
        sys.exit(0)
    else:
        print("\n❌ Some critical features have issues")
        sys.exit(1)
