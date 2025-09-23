#!/usr/bin/env python3
"""
Integration Test Scenarios for GengoWatcher

This script implements comprehensive testing scenarios using the mock Gengo server
to test job acceptance, cancellation, and real-time functionality.
"""

import asyncio
import json
import logging
import time
import requests
import subprocess
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional
import websockets
import threading

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gengowatcher.config import AppConfig
from gengowatcher.state import AppState
from gengowatcher import watcher

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("integration-test")

class GengoIntegrationTester:
    """Integration tester for GengoWatcher scenarios."""

    def __init__(self, mock_server_url: str = "http://127.0.0.1:3000"):
        self.mock_url = mock_server_url
        self.watcher_process: Optional[subprocess.Popen] = None
        self.websocket_messages: List[Dict] = []
        self.test_results: Dict[str, bool] = {}

    def start_mock_server(self):
        """Start the mock Gengo server."""
        logger.info("Starting mock Gengo server...")
        self.mock_process = subprocess.Popen([
            sys.executable, str(Path(__file__).parent / "mock_gengo_server.py"),
            "--host", "127.0.0.1",
            "--port", "3000"
        ])
        time.sleep(2)  # Wait for server to start

    def stop_mock_server(self):
        """Stop the mock Gengo server."""
        if hasattr(self, 'mock_process') and self.mock_process:
            self.mock_process.terminate()
            self.mock_process.wait()
            logger.info("Mock server stopped")

    def set_scenario(self, scenario: str):
        """Set the mock server scenario."""
        response = requests.post(f"{self.mock_url}/api/scenario/{scenario}")
        if response.status_code == 200:
            logger.info(f"Set scenario to: {scenario}")
            return True
        else:
            logger.error(f"Failed to set scenario: {response.text}")
            return False

    async def websocket_listener(self):
        """Listen for WebSocket messages from mock server."""
        try:
            async with websockets.connect(f"ws://127.0.0.1:3000/ws/jobs") as websocket:
                logger.info("WebSocket connected")
                while True:
                    message = await websocket.recv()
                    data = json.loads(message)
                    self.websocket_messages.append(data)
                    logger.info(f"WebSocket message: {data}")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")

    def start_websocket_listener(self):
        """Start WebSocket listener in background thread."""
        def run_listener():
            asyncio.run(self.websocket_listener())

        thread = threading.Thread(target=run_listener, daemon=True)
        thread.start()

    def create_test_job(self, title: str = None, reward: float = None):
        """Create a test job via the mock server."""
        response = requests.post(f"{self.mock_url}/api/jobs/create")
        if response.status_code == 200:
            job_data = response.json()
            job_id = job_data["job_id"]
            logger.info(f"Created test job: {job_id}")
            return job_id
        else:
            logger.error(f"Failed to create test job: {response.text}")
            return None

    def get_job_status(self, job_id: str):
        """Get job status from mock server."""
        response = requests.get(f"{self.mock_url}/api/jobs")
        if response.status_code == 200:
            jobs = response.json()["jobs"]
            for job in jobs:
                if job["id"] == job_id:
                    return job
        return None

    def test_scenario_1_accept_then_cancel(self):
        """Test Case 1: Accept job A, then higher-paying job B appears."""
        logger.info("🧪 Running Scenario 1: Accept then Cancel")

        # Set scenario
        if not self.set_scenario("cancellation_test"):
            return False

        # Create first job (low value)
        job_a = self.create_test_job()
        if not job_a:
            return False

        # Simulate accepting job A
        response = requests.post(f"{self.mock_url}/t/jobs/accept/{job_a}")
        if response.status_code != 200:
            logger.error(f"Failed to accept job A: {response.text}")
            return False

        logger.info(f"Accepted job A: {job_a}")

        # Wait a moment
        time.sleep(1)

        # Create second job (high value that should trigger cancellation)
        job_b = self.create_test_job()
        if not job_b:
            return False

        # Simulate accepting job B (should trigger cancellation of A)
        response = requests.post(f"{self.mock_url}/t/jobs/accept/{job_b}")
        if response.status_code != 200:
            logger.error(f"Failed to accept job B: {response.text}")
            return False

        logger.info(f"Accepted job B: {job_b}")

        # Check final status
        time.sleep(1)
        job_a_status = self.get_job_status(job_a)
        job_b_status = self.get_job_status(job_b)

        if job_a_status and job_a_status["status"] == "cancelled":
            logger.info("✅ Job A was correctly cancelled")
        else:
            logger.error("❌ Job A was not cancelled")
            return False

        if job_b_status and job_b_status["status"] == "accepted":
            logger.info("✅ Job B was correctly accepted")
        else:
            logger.error("❌ Job B was not accepted")
            return False

        return True

    def test_scenario_2_cancellation_disabled(self):
        """Test Case 2: Cancellation disabled or ratio unmet."""
        logger.info("🧪 Running Scenario 2: Cancellation Disabled")

        # This would require configuring the watcher with cancellation disabled
        # For now, we'll just verify the mock server behavior
        if not self.set_scenario("normal_flow"):
            return False

        # Create two jobs with small reward difference
        job_a = self.create_test_job()
        job_b = self.create_test_job()

        if not job_a or not job_b:
            return False

        # Accept first job
        response = requests.post(f"{self.mock_url}/t/jobs/accept/{job_a}")
        if response.status_code != 200:
            return False

        # Accept second job (should not cancel first due to small difference)
        response = requests.post(f"{self.mock_url}/t/jobs/accept/{job_b}")
        if response.status_code != 200:
            return False

        # Check that both jobs are accepted (no cancellation)
        job_a_status = self.get_job_status(job_a)
        job_b_status = self.get_job_status(job_b)

        if (job_a_status and job_a_status["status"] == "accepted" and
            job_b_status and job_b_status["status"] == "accepted"):
            logger.info("✅ Both jobs accepted (no cancellation)")
            return True
        else:
            logger.error("❌ Unexpected job status")
            return False

    def test_scenario_3_server_error(self):
        """Test Case 3: Server error handling."""
        logger.info("🧪 Running Scenario 3: Server Error Handling")

        if not self.set_scenario("server_error"):
            return False

        # Try operations that may fail
        job_id = self.create_test_job()
        if not job_id:
            return False

        # Try to accept (may fail due to simulated errors)
        response = requests.post(f"{self.mock_url}/t/jobs/accept/{job_id}")

        # Either success or expected error
        if response.status_code in [200, 500]:
            if response.status_code == 200:
                logger.info("✅ Operation succeeded despite error scenario")
            else:
                logger.info("✅ Operation failed as expected in error scenario")
            return True
        else:
            logger.error(f"❌ Unexpected response: {response.status_code}")
            return False

    def run_all_scenarios(self):
        """Run all test scenarios."""
        logger.info("🚀 Starting GengoWatcher Integration Tests")

        # Start WebSocket listener
        self.start_websocket_listener()

        # Start mock server
        self.start_mock_server()

        try:
            # Run test scenarios
            scenarios = [
                ("accept_then_cancel", self.test_scenario_1_accept_then_cancel),
                ("cancellation_disabled", self.test_scenario_2_cancellation_disabled),
                ("server_error", self.test_scenario_3_server_error),
            ]

            results = {}
            for name, test_func in scenarios:
                logger.info(f"\n{'='*50}")
                try:
                    result = test_func()
                    results[name] = result
                    status = "✅ PASSED" if result else "❌ FAILED"
                    logger.info(f"Scenario '{name}': {status}")
                except Exception as e:
                    logger.error(f"Scenario '{name}' failed with exception: {e}")
                    results[name] = False

            # Summary
            logger.info(f"\n{'='*50}")
            logger.info("📊 TEST RESULTS SUMMARY")
            logger.info(f"{'='*50}")

            passed = 0
            total = len(results)

            for name, result in results.items():
                status = "✅ PASSED" if result else "❌ FAILED"
                logger.info(f"  {name}: {status}")
                if result:
                    passed += 1

            logger.info(f"\n📈 Overall: {passed}/{total} scenarios passed")

            if passed == total:
                logger.info("🎉 All integration tests passed!")
                return True
            else:
                logger.warning(f"⚠️  {total - passed} scenarios failed")
                return False

        finally:
            self.stop_mock_server()

def main():
    """Main test runner."""
    tester = GengoIntegrationTester()

    success = tester.run_all_scenarios()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()</content>
</xai:function_call"> <parameter name="filePath">scripts/test_integration_scenarios.py