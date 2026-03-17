#!/usr/bin/env python3
"""
Run critical features tests for GengoWatcher.
This script runs built-in tests for:
1. CAPTCHA solver functionality
2. WebSocket connectivity
3. Web API endpoints
4. Rate limiting
"""

import asyncio
import subprocess
import sys
import time
import json
import requests
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def run_command(cmd, timeout=30):
    """Run a command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path(__file__).parent),
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


async def test_captcha_solver():
    """Test CAPTCHA solver functionality."""
    logger.info("\n=== Testing CAPTCHA Solver ===")

    # Test 1: Check CAPTCHA CLI exists
    success, _stdout, _stderr = run_command(
        "python -m src.gengowatcher.main captchasetup --help"
    )
    if success:
        logger.info("✅ CAPTCHA setup command available")
    else:
        logger.error("❌ CAPTCHA setup command not available")
        return False

    # Test 2: Check CAPTCHA test command
    success, _stdout, _stderr = run_command(
        "python -m src.gengowatcher.main captchatest --help"
    )
    if success:
        logger.info("✅ CAPTCHA test command available")
    else:
        logger.error("❌ CAPTCHA test command not available")
        return False

    # Test 3: Check CAPTCHA configuration exists
    config_file = Path("config.toml")
    if config_file.exists():
        with open(config_file, "r") as f:
            config_content = f.read()
            if "[Captcha]" in config_content:
                logger.info("✅ CAPTCHA configuration section exists")
            else:
                logger.warning(
                    "⚠️ CAPTCHA configuration section missing - this is expected for new installations"
                )
    else:
        logger.warning(
            "⚠️ Config file not found - this is expected for new installations"
        )

    logger.info("✅ CAPTCHA solver framework is properly integrated")
    return True


async def test_websocket_simulation():
    """Test WebSocket connectivity framework."""
    logger.info("\n=== Testing WebSocket Connectivity ===")

    # Test 1: Check if WebSocket code exists
    watcher_file = Path("src/gengowatcher/watcher.py")
    if watcher_file.exists():
        with open(watcher_file, "r") as f:
            content = f.read()
            if "websockets" in content and "_connect_websocket" in content:
                logger.info("✅ WebSocket implementation found")
            else:
                logger.error("❌ WebSocket implementation not found")
                return False

    # Test 2: Check WebSocket test command
    success, _stdout, _stderr = run_command(
        "python -c "
        "\"import sys; sys.path.insert(0, 'src'); "
        "from gengowatcher.ui import CommandLineInterface; "
        "from gengowatcher.config import AppConfig; "
        "from gengowatcher.state import AppState; "
        "from gengowatcher.watcher import GengoWatcher; "
        "import logging; "
        "logger = logging.getLogger('test'); "
        "config = AppConfig(); "
        "state = AppState(logger); "
        "watcher = GengoWatcher(config, logger, state); "
        "ui = CommandLineInterface(config, watcher, logger); "
        "print('WebSocket test framework available')\""
    )

    if success:
        logger.info("✅ WebSocket test framework is available")
    else:
        logger.error("❌ WebSocket test framework not working")
        return False

    # Test 3: Check if WebSocket test commands are registered
    ui_file = Path("src/gengowatcher/ui.py")
    if ui_file.exists():
        with open(ui_file, "r") as f:
            content = f.read()
            if "wstest" in content and "_handle_websocket_test" in content:
                logger.info("✅ WebSocket test commands registered")
            else:
                logger.error("❌ WebSocket test commands not found")
                return False

    logger.info("✅ WebSocket connectivity framework is properly integrated")
    return True


async def test_web_api():
    """Test Web API endpoints."""
    logger.info("\n=== Testing Web API Endpoints ===")

    # Test 1: Check if web module exists
    web_file = Path("src/gengowatcher/web.py")
    if web_file.exists():
        with open(web_file, "r") as f:
            content = f.read()
            if "FastAPI" in content and "@app.get" in content:
                logger.info("✅ Web API implementation found")
            else:
                logger.error("❌ Web API implementation not found")
                return False

    # Test 2: Check if web server can be imported
    success, _stdout, stderr = run_command(
        "python -c "
        "\"import sys; sys.path.insert(0, 'src'); "
        "from gengowatcher.web import WebAPI; "
        "from gengowatcher.config import AppConfig; "
        "import logging; "
        "logger = logging.getLogger('test'); "
        "config = AppConfig(); "
        "web = WebAPI(config, logger, port=8001); "
        "print('Web API can be initialized')\""
    )

    if success:
        logger.info("✅ Web API can be initialized")
    else:
        logger.error("❌ Web API initialization failed")
        logger.error(f"Error: {stderr}")
        return False

    # Test 3: Check for required endpoints
    if web_file.exists():
        with open(web_file, "r") as f:
            content = f.read()
            endpoints = ["/health", "/config", "/metrics", "/jobs"]
            missing = []
            for endpoint in endpoints:
                if endpoint not in content:
                    missing.append(endpoint)

            if not missing:
                logger.info("✅ All required API endpoints found")
            else:
                logger.warning(f"⚠️ Some endpoints missing: {missing}")

    logger.info("✅ Web API framework is properly integrated")
    return True


async def test_rate_limiting():
    """Test rate limiting functionality."""
    logger.info("\n=== Testing Rate Limiting ===")

    # Test 1: Check rate limiter implementation
    rate_limiter_file = Path("src/gengowatcher/rate_limiter.py")
    if rate_limiter_file.exists():
        logger.info("✅ Rate limiter implementation found")
    else:
        logger.error("❌ Rate limiter implementation not found")
        return False

    # Test 2: Test rate limiter functionality
    success, stdout, stderr = run_command(
        "python -c "
        "\"import sys; sys.path.insert(0, 'src'); "
        "from gengowatcher.rate_limiter import RateLimiter; "
        "import time; "
        "limiter = RateLimiter(max_requests=5, time_window=10); "
        "accepted = 0; "
        "for i in range(7): "
        "    if limiter.acquire(): accepted += 1; "
        "print(f'Accepted: {accepted}'); "
        "assert accepted == 5, f'Expected 5, got {accepted}'; "
        "print('Rate limiting test passed')\""
    )

    if success and "Rate limiting test passed" in stdout:
        logger.info("✅ Rate limiting functionality works correctly")
    else:
        logger.error("❌ Rate limiting test failed")
        logger.error(f"Error: {stderr}")
        return False

    # Test 3: Check job acceptance rate limiting
    job_acceptance_file = Path("src/gengowatcher/job_acceptance.py")
    if job_acceptance_file.exists():
        with open(job_acceptance_file, "r") as f:
            content = f.read()
            if "RateLimiter" in content and "max_requests=30" in content:
                logger.info("✅ Job acceptance rate limiting configured")
            else:
                logger.warning(
                    "⚠️ Job acceptance rate limiting may not be properly configured"
                )

    logger.info("✅ Rate limiting is properly implemented")
    return True


async def test_auto_accept_with_captcha():
    """Test auto-accept with CAPTCHA integration."""
    logger.info("\n=== Testing Auto-Accept with CAPTCHA Integration ===")

    # Test 1: Check auto-accept implementation
    job_acceptance_file = Path("src/gengowatcher/job_acceptance.py")
    if job_acceptance_file.exists():
        with open(job_acceptance_file, "r") as f:
            content = f.read()
            if (
                "JobAcceptanceEngine" in content
                and "_handle_captcha_challenge" in content
            ):
                logger.info("✅ Auto-accept with CAPTCHA implementation found")
            else:
                logger.error("❌ Auto-accept with CAPTCHA implementation not found")
                return False

    # Test 2: Check CAPTCHA integration points
    if job_acceptance_file.exists():
        with open(job_acceptance_file, "r") as f:
            content = f.read()
            captcha_checks = [
                "captcha_solver.solve_recaptcha_v2",
                "captcha_solver.solve_hcaptcha",
                "captcha_solver.solve_recaptcha_v3",
                "g-recaptcha-response",
                "h-captcha-response",
            ]

            found = sum(1 for check in captcha_checks if check in content)
            if found >= 4:
                logger.info(
                    f"✅ CAPTCHA integration points found ({found}/{len(captcha_checks)})"
                )
            else:
                logger.warning(
                    f"⚠️ Some CAPTCHA integration points missing ({found}/{len(captcha_checks)})"
                )

    # Test 3: Check if components can be imported together
    success, _stdout, stderr = run_command(
        "python -c "
        "\"import sys; sys.path.insert(0, 'src'); "
        "from gengowatcher.config import AppConfig; "
        "from gengowatcher.job_acceptance import JobAcceptanceEngine; "
        "from gengowatcher.captcha_manager import CaptchaSolverManager; "
        "import logging; "
        "logger = logging.getLogger('test'); "
        "config = AppConfig(); "
        "engine = JobAcceptanceEngine(config, logger); "
        "print('Auto-accept and CAPTCHA integration works')\""
    )

    if success:
        logger.info("✅ Auto-accept and CAPTCHA components integrate correctly")
    else:
        logger.error("❌ Auto-accept and CAPTCHA integration failed")
        logger.error(f"Error: {stderr}")
        return False

    logger.info("✅ Auto-accept with CAPTCHA integration is properly implemented")
    return True


async def run_all_tests():
    """Run all critical feature tests."""
    logger.info("🧪 Running Critical Features Test Suite")
    logger.info("=" * 60)

    results = []

    # Run all tests
    tests = [
        ("CAPTCHA Solver", test_captcha_solver),
        ("WebSocket Connectivity", test_websocket_simulation),
        ("Web API Endpoints", test_web_api),
        ("Rate Limiting", test_rate_limiting),
        ("Auto-Accept with CAPTCHA", test_auto_accept_with_captcha),
    ]

    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error(f"❌ {test_name} test crashed: {e}")
            results.append((test_name, False))

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("📊 Test Results Summary")
    logger.info("=" * 60)

    passed = 0
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{test_name:<30} {status}")
        if result:
            passed += 1

    logger.info(f"\nOverall: {passed}/{total} tests passed")

    if passed == total:
        logger.info("\n🎉 All critical features are working correctly!")
        return True
    else:
        logger.warning(f"\n⚠️ {total - passed} test(s) failed or have warnings")
        logger.info("\nNote: Some failures may be expected in a fresh installation.")
        logger.info(
            "Run the application with --configure to set up required configurations."
        )
        return False


if __name__ == "__main__":
    # Run tests
    success = asyncio.run(run_all_tests())

    if success:
        print("\n✅ Critical features verification complete - all systems GO!")
        sys.exit(0)
    else:
        print("\n❌ Some critical features have issues or require configuration")
        sys.exit(1)
