"""
Enhanced GengoWatcher with automatic job cancellation for better opportunities.
This integrates the high-value job manager with cancellation capabilities.
"""

import asyncio
import logging
import time
from typing import Dict, Any
from .config import AppConfig
from .high_value_job_manager import HighValueJobManager
from .captcha_manager import CaptchaSolverManager


class WatcherWithCancellation:
    """Enhanced watcher with automatic job cancellation."""

    def __init__(self, config_file: str = "config_high_value.ini"):
        # Load configuration
        self.config = AppConfig()
        self.config.CONFIG_FILE = config_file
        self.config.load_config()

        # Set up logging
        self.logger = logging.getLogger("WatcherWithCancellation")
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

        # Initialize components
        self.captcha_solver = None
        if self.config.get("Captcha", "enabled") and self.config.get(
            "Captcha", "service"
        ):
            self.captcha_solver = CaptchaSolverManager(
                self.config.config["Captcha"], self.logger
            )

        # High-value job manager with cancellation
        self.hv_manager = HighValueJobManager(
            self.config, self.logger, self.captcha_solver
        )

        # Track if we have a current job
        self.has_current_job = False

        self.logger.info("🔄 Enhanced Watcher with Cancellation initialized")
        self.logger.info(
            "Ready to accept high-value jobs and cancel for better opportunities"
        )

    async def process_job_opportunity(self, job_data: Dict[str, Any]) -> bool:
        """
        Process a new job opportunity with automatic cancellation logic.

        Args:
            job_data: Dictionary containing job information

        Returns:
            bool: True if job was accepted, False otherwise
        """
        job_id = job_data.get("id")
        reward = float(job_data.get("reward", 0))

        self.logger.info(f"📋 Processing job opportunity: {job_id} (${reward:.2f})")

        # Let the high-value manager handle it (includes cancellation logic)
        success = await self.hv_manager.process_job(job_data)

        if success:
            self.has_current_job = True
            self.logger.info(f"✅ Job {job_id} accepted and now being tracked")
        else:
            self.logger.debug(f"⏭️  Job {job_id} not accepted (may not be high-value)")

        return success

    def notify_job_completed(self, job_id: str):
        """Notify the watcher that a job has been completed."""
        self.logger.info(f"✅ Job {job_id} completed")
        self.hv_manager.clear_current_job()
        self.has_current_job = False

    def notify_job_failed(self, job_id: str):
        """Notify the watcher that a job has failed."""
        self.logger.warning(f"❌ Job {job_id} failed")
        self.hv_manager.clear_current_job()
        self.has_current_job = False

    def get_status(self) -> Dict[str, Any]:
        """Get current status and statistics."""
        hv_stats = self.hv_manager.get_stats()
        cancel_stats = hv_stats.get("cancellation", {})

        return {
            "has_current_job": self.has_current_job,
            "current_job": cancel_stats.get("current_job", {}),
            "high_value_stats": {
                "total_seen": hv_stats.get("total_jobs_seen", 0),
                "high_value_seen": hv_stats.get("high_value_seen", 0),
                "high_value_accepted": hv_stats.get("high_value_accepted", 0),
                "success_rate": hv_stats.get("success_rate", 0),
            },
            "cancellation_stats": {
                "total_cancellations": cancel_stats.get("cancellations_count", 0),
                "successful_cancellations": cancel_stats.get(
                    "successful_cancellations", 0
                ),
                "total_forfeited": cancel_stats.get("total_lost_rewards", 0),
            },
        }

    async def test_cancellation_scenario(self):
        """Test the cancellation system with a simulated scenario."""
        self.logger.info("🧪 Testing cancellation scenario...")

        # Simulate having a current job
        test_job = {
            "id": "test_current_123",
            "reward": 150.0,
            "url": "https://gengo.com/t/jobs/details/test_current_123",
        }

        # Process it (this will set it as current job)
        await self.process_job_opportunity(test_job)
        time.sleep(0.1)  # Small delay

        # Now a better job appears
        better_job = {
            "id": "test_better_456",
            "reward": 450.0,  # 3x better
            "url": "https://gengo.com/t/jobs/details/test_better_456",
        }

        self.logger.info("🚀 A better job opportunity appears!")
        await self.process_job_opportunity(better_job)

        # Show status
        status = self.get_status()
        self.logger.info("📊 Current Status:")
        self.logger.info(f"   Has current job: {status['has_current_job']}")
        self.logger.info(
            f"   Cancellations: {status['cancellation_stats']['total_cancellations']}"
        )


# Example usage
async def main():
    """Example of how to use the enhanced watcher."""
    print("🔄 Enhanced GengoWatcher with Job Cancellation")
    print("=" * 50)

    # Create watcher
    watcher = WatcherWithCancellation()

    # Show current status
    status = watcher.get_status()
    print(f"Initial status: {status}")

    # Test scenario
    await watcher.test_cancellation_scenario()

    # Show final status
    status = watcher.get_status()
    print(f"\nFinal status: {status}")


if __name__ == "__main__":
    asyncio.run(main())
