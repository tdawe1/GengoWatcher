#!/usr/bin/env python3
"""
GengoWatcher Integration Test Runner

This script provides a comprehensive test runner for the GengoWatcher
integration test suite using the mock Gengo server.
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test-runner")

class IntegrationTestRunner:
    """Runner for GengoWatcher integration tests."""

    def __init__(self, mock_host: str = "127.0.0.1", mock_port: int = 3000):
        self.mock_host = mock_host
        self.mock_port = mock_port
        self.mock_url = f"http://{mock_host}:{mock_port}"
        self.test_results: Dict[str, Dict] = {}

    def check_dependencies(self) -> bool:
        """Check if all required dependencies are available."""
        try:
            import requests
            import websockets
            logger.info("✅ All Python dependencies available")
            return True
        except ImportError as e:
            logger.error(f"❌ Missing dependency: {e}")
            return False

    def start_mock_server(self, scenario: str = "normal_flow") -> Optional[subprocess.Popen]:
        """Start the mock Gengo server."""
        try:
            cmd = [
                sys.executable,
                str(Path(__file__).parent / "mock_gengo_server.py"),
                "--host", self.mock_host,
                "--port", str(self.mock_port),
                "--scenario", scenario
            ]

            logger.info(f"Starting mock server: {' '.join(cmd)}")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Wait for server to start
            time.sleep(3)

            # Check if process is still running
            if process.poll() is None:
                logger.info("✅ Mock server started successfully")
                return process
            else:
                stdout, stderr = process.communicate()
                logger.error(f"❌ Mock server failed to start: {stderr}")
                return None

        except Exception as e:
            logger.error(f"❌ Failed to start mock server: {e}")
            return None

    def run_test_scenario(self, scenario_name: str) -> Dict:
        """Run a specific test scenario."""
        logger.info(f"🧪 Running scenario: {scenario_name}")

        start_time = time.time()
        result = {
            "scenario": scenario_name,
            "status": "running",
            "start_time": start_time,
            "end_time": None,
            "duration": None,
            "tests": {},
            "errors": []
        }

        try:
            # Import and run the test
            if scenario_name == "accept_then_cancel":
                from test_integration_scenarios import GengoIntegrationTester
                tester = GengoIntegrationTester(self.mock_url)
                success = tester.test_scenario_1_accept_then_cancel()
                result["tests"]["accept_then_cancel"] = success

            elif scenario_name == "cancellation_disabled":
                from test_integration_scenarios import GengoIntegrationTester
                tester = GengoIntegrationTester(self.mock_url)
                success = tester.test_scenario_2_cancellation_disabled()
                result["tests"]["cancellation_disabled"] = success

            elif scenario_name == "server_error":
                from test_integration_scenarios import GengoIntegrationTester
                tester = GengoIntegrationTester(self.mock_url)
                success = tester.test_scenario_3_server_error()
                result["tests"]["server_error"] = success

            else:
                result["errors"].append(f"Unknown scenario: {scenario_name}")
                result["status"] = "error"
                return result

            # Calculate results
            passed = sum(1 for test_result in result["tests"].values() if test_result)
            total = len(result["tests"])

            result["passed"] = passed
            result["total"] = total
            result["success_rate"] = (passed / total) * 100 if total > 0 else 0
            result["status"] = "passed" if passed == total else "failed"

        except Exception as e:
            logger.error(f"❌ Scenario {scenario_name} failed: {e}")
            result["status"] = "error"
            result["errors"].append(str(e))

        finally:
            end_time = time.time()
            result["end_time"] = end_time
            result["duration"] = end_time - start_time

        return result

    def run_all_scenarios(self) -> Dict:
        """Run all available test scenarios."""
        scenarios = [
            "accept_then_cancel",
            "cancellation_disabled",
            "server_error"
        ]

        overall_result = {
            "test_run": {
                "start_time": time.time(),
                "scenarios": scenarios,
                "results": {}
            },
            "summary": {
                "total_scenarios": len(scenarios),
                "passed_scenarios": 0,
                "failed_scenarios": 0,
                "total_tests": 0,
                "passed_tests": 0,
                "failed_tests": 0
            }
        }

        # Start mock server
        mock_process = self.start_mock_server()
        if not mock_process:
            logger.error("❌ Cannot run tests without mock server")
            return {"error": "Mock server failed to start"}

        try:
            for scenario in scenarios:
                result = self.run_test_scenario(scenario)
                overall_result["test_run"]["results"][scenario] = result

                # Update summary
                if result["status"] == "passed":
                    overall_result["summary"]["passed_scenarios"] += 1
                else:
                    overall_result["summary"]["failed_scenarios"] += 1

                overall_result["summary"]["total_tests"] += result.get("total", 0)
                overall_result["summary"]["passed_tests"] += result.get("passed", 0)
                overall_result["summary"]["failed_tests"] += result.get("total", 0) - result.get("passed", 0)

        finally:
            # Stop mock server
            if mock_process:
                mock_process.terminate()
                mock_process.wait()
                logger.info("✅ Mock server stopped")

        overall_result["test_run"]["end_time"] = time.time()
        overall_result["test_run"]["duration"] = (
            overall_result["test_run"]["end_time"] - overall_result["test_run"]["start_time"]
        )

        return overall_result

    def save_results(self, results: Dict, output_file: Optional[str] = None):
        """Save test results to file."""
        if not output_file:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_file = f"test_results_{timestamp}.json"

        try:
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            logger.info(f"✅ Test results saved to: {output_file}")
        except Exception as e:
            logger.error(f"❌ Failed to save results: {e}")

    def print_summary(self, results: Dict):
        """Print a summary of test results."""
        print("\n" + "="*60)
        print("🎯 GENGOWATCHER INTEGRATION TEST RESULTS")
        print("="*60)

        summary = results.get("summary", {})
        test_run = results.get("test_run", {})

        print("📊 OVERALL SUMMARY:"        print(f"   Scenarios: {summary.get('passed_scenarios', 0)}/{summary.get('total_scenarios', 0)} passed")
        print(".1f"        print(".1f"        print(".1f"
        print("
⏱️  DURATION:"        print(".1f"
        print("\n📋 SCENARIO DETAILS:")
        for scenario, result in test_run.get("results", {}).items():
            status = "✅" if result.get("status") == "passed" else "❌"
            duration = result.get("duration", 0)
            tests_passed = result.get("passed", 0)
            tests_total = result.get("total", 0)

            print(f"   {status} {scenario}")
            print(".1f"            if tests_total > 0:
                print(f"      Tests: {tests_passed}/{tests_total} passed")

            if result.get("errors"):
                print("      Errors:"                for error in result["errors"]:
                    print(f"        - {error}")

        print("\n" + "="*60)

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="GengoWatcher Integration Test Runner")
    parser.add_argument(
        "--scenario",
        choices=["accept_then_cancel", "cancellation_disabled", "server_error", "all"],
        default="all",
        help="Test scenario to run"
    )
    parser.add_argument(
        "--mock-host",
        default="127.0.0.1",
        help="Mock server host"
    )
    parser.add_argument(
        "--mock-port",
        type=int,
        default=3000,
        help="Mock server port"
    )
    parser.add_argument(
        "--output",
        help="Output file for test results"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    runner = IntegrationTestRunner(args.mock_host, args.mock_port)

    # Check dependencies
    if not runner.check_dependencies():
        sys.exit(1)

    # Run tests
    if args.scenario == "all":
        results = runner.run_all_scenarios()
    else:
        # Start mock server for single scenario
        mock_process = runner.start_mock_server()
        if not mock_process:
            logger.error("❌ Cannot run test without mock server")
            sys.exit(1)

        try:
            result = runner.run_test_scenario(args.scenario)
            results = {
                "test_run": {
                    "results": {args.scenario: result},
                    "start_time": result["start_time"],
                    "end_time": result["end_time"],
                    "duration": result["duration"]
                },
                "summary": {
                    "total_scenarios": 1,
                    "passed_scenarios": 1 if result["status"] == "passed" else 0,
                    "failed_scenarios": 1 if result["status"] != "passed" else 0,
                    "total_tests": result.get("total", 0),
                    "passed_tests": result.get("passed", 0),
                    "failed_tests": result.get("total", 0) - result.get("passed", 0)
                }
            }
        finally:
            mock_process.terminate()
            mock_process.wait()

    # Save and print results
    runner.save_results(results, args.output)
    runner.print_summary(results)

    # Exit with appropriate code
    success = results["summary"]["failed_scenarios"] == 0
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()</content>
</xai:function_call"> <parameter name="filePath">scripts/run_integration_tests.py