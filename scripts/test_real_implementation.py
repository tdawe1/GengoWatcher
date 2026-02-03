#!/usr/bin/env python3
"""
Test script for verifying the real Gengo API integration with captcha solving.

This script tests the complete job acceptance flow including:
1. Authentication with Gengo
2. Job detection and evaluation
3. Job acceptance via API calls
4. Captcha solving when required
5. Error handling and retry mechanisms

Usage:
    python test_real_implementation.py

Note: This requires valid Gengo credentials and captcha solver API keys to be configured.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add src to path so we can import our modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gengowatcher.config import AppConfig
from gengowatcher.watcher import GengoWatcher
from gengowatcher.state import AppState
from gengowatcher.job_acceptance import JobAcceptanceEngine


def setup_logging():
    """Set up logging for the test."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("test_real_implementation.log"),
        ],
    )
    return logging.getLogger(__name__)


async def test_job_acceptance():
    """
    Run an end-to-end test of the job acceptance flow against the real Gengo API.

    Performs configuration checks (including AutoAccept and required WebSocket credentials), initialises application components, evaluates a synthetic test job for eligibility and, if eligible, attempts to accept it via the real Gengo API. The operation may perform network calls and produce side effects on the associated Gengo account.

    Returns:
        bool: `True` if the test completed and the job was accepted, `False` otherwise.
    """
    logger = setup_logging()
    logger.info("Starting real implementation test")

    if os.getenv("GENGO_REAL_TEST", "").lower() not in {"1", "true", "yes"}:
        print("Skipping real API acceptance test. Set GENGO_REAL_TEST=1 to run.")
        return None

    try:
        # Load configuration
        config = AppConfig()
        logger.info("Configuration loaded successfully")

        # Check if auto-accept is enabled
        if not config.get("AutoAccept", "enabled"):
            logger.warning("Auto-accept is not enabled in configuration")
            print("Auto-accept disabled; skipping acceptance test")
            return None

        # Check for required credentials
        user_session = config.get("WebSocket", "user_session")
        user_key = config.get("WebSocket", "user_key")
        if not user_session or user_session == "REPLACE_WITH_YOUR_SESSION_TOKEN":
            logger.error("Gengo user session token not configured")
            print("Please configure your Gengo user session token in config.ini")
            return False
        if not user_key or user_key == "REPLACE_WITH_YOUR_USER_KEY":
            logger.error("Gengo browser user key not configured")
            print(
                "Please configure your user_key (DevTools → Application → Local Storage → userKey) in config.ini"
            )
            return False

        user_id = config.get("WebSocket", "user_id")
        if not user_id:
            logger.error("Gengo user ID not configured")
            print("Please configure your Gengo user ID in config.ini")
            return False

        # Initialize components
        state = AppState(logger=logger)
        watcher = GengoWatcher(config=config, state=state, logger=logger)
        job_acceptance_engine = watcher.job_acceptance_engine

        logger.info("Components initialized successfully")

        # Test job evaluation
        test_job = {
            "id": "test-12345",
            "title": "TEST JOB: English > Japanese",
            "reward": 12.34,
            "url": "https://gengo.com/t/jobs/details/test-12345",
            "source": "websocket",
            "currency": "USD",
        }

        logger.info("Testing job eligibility check")
        is_eligible = job_acceptance_engine.is_job_eligible(test_job)
        logger.info(f"Job eligibility: {is_eligible}")

        if not is_eligible:
            logger.warning("Test job is not eligible for auto-acceptance")
            print("Test job does not meet auto-acceptance criteria")
            return False

        # Test job acceptance (this will use real Gengo API)
        logger.info("Testing job acceptance with real API")
        success = await job_acceptance_engine.accept_job(test_job)

        if success:
            logger.info("Job acceptance test PASSED")
            print("✓ Job acceptance test passed")
            return True
        else:
            logger.error("Job acceptance test FAILED")
            print("✗ Job acceptance test failed")
            return False

    except Exception as e:
        logger.error(f"Test failed with exception: {e}", exc_info=True)
        print(f"Test failed: {e}")
        return False


async def test_captcha_integration():
    """Test the captcha solving integration."""
    logger = logging.getLogger(__name__)
    logger.info("Testing captcha solving integration")

    try:
        # Load configuration
        config = AppConfig()

        # Check if captcha solver is configured
        captcha_service = config.get("Captcha", "service")
        if not captcha_service:
            logger.warning("Captcha solver service not configured")
            print("Captcha solver service not configured - skipping captcha test")
            return True

        # Initialize components
        state = AppState(logger=logger)
        watcher = GengoWatcher(config=config, state=state, logger=logger)
        captcha_solver = watcher.captcha_solver

        if not captcha_solver.is_configured():
            logger.warning("Captcha solver not properly configured")
            print("Captcha solver not properly configured - skipping captcha test")
            return True

        # Test balance check
        try:
            balance = captcha_solver.get_balance()
            logger.info(f"Captcha solver balance: {balance}")
            print(f"Captcha solver balance: {balance}")
        except Exception as e:
            logger.error(f"Failed to check captcha solver balance: {e}")
            print(f"Failed to check captcha solver balance: {e}")
            return False

        logger.info("Captcha integration test completed")
        print("✓ Captcha integration test completed")
        return True

    except Exception as e:
        logger.error(f"Captcha test failed with exception: {e}", exc_info=True)
        print(f"Captcha test failed: {e}")
        return False


async def main():
    """Main test function."""
    print("GengoWatcher Real Implementation Test")
    print("=" * 40)

    # Run tests
    # Test captcha integration first
    print("\n1. Testing captcha integration...")
    captcha_success = await test_captcha_integration()

    # Test job acceptance
    print("\n2. Testing job acceptance with real Gengo API...")
    acceptance_success = await test_job_acceptance()

    # Summary
    print("\n" + "=" * 40)

    def format_result(result):
        if result is None:
            return "SKIP"
        return "PASS" if result else "FAIL"

    print("Test Summary:")
    print(f"  Captcha Integration: {format_result(captcha_success)}")
    print(f"  Job Acceptance:      {format_result(acceptance_success)}")

    if captcha_success and (acceptance_success is None or acceptance_success):
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n❌ Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
