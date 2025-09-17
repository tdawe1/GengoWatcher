"""
Enhanced GengoWatcher with High-Value Job Management
This file contains patches to integrate the HighValueJobManager.
"""

import time
import threading
import asyncio
import logging
from typing import Dict, Any

from .high_value_job_manager import HighValueJobManager


def enhance_watcher_class():
    """Add high-value job management to GengoWatcher class."""

    # Store the original __init__ method
    from .watcher import GengoWatcher
    original_init = GengoWatcher.__init__

    def enhanced_init(self, config, state, logger):
        # Call original init
        original_init(self, config, state, logger)

        # Initialize high-value job manager
        from .captcha_manager import CaptchaSolverManager
        self.captcha_solver = CaptchaSolverManager(config, logger)
        self.high_value_manager = HighValueJobManager(config, logger, self.captcha_solver)

        logger.info("Enhanced GengoWatcher with High-Value Job Manager initialized")

    # Replace __init__
    GengoWatcher.__init__ = enhanced_init

    # Store the original _process_new_job method
    original_process_new_job = GengoWatcher._process_new_job

    def enhanced_process_new_job(self, job_id, title, reward, url, source):
        """Enhanced job processing with high-value job detection."""

        # Create job data dictionary
        job_data = {
            "id": str(job_id),
            "title": str(title),
            "reward": float(reward),
            "url": str(url),
            "source": source
        }

        # Check if this is a high-value job
        is_hv, category = self.high_value_manager.is_high_value(reward)

        if is_hv:
            self.logger.info(f"🔥 HIGH-VALUE JOB DETECTED via {source}: {title} (${reward:.2f}) - {category}")

            # Process high-value job asynchronously
            threading.Thread(
                target=self._async_high_value_acceptance_wrapper,
                args=(job_data,),
                daemon=True
            ).start()

        # Call original processing for all jobs
        return original_process_new_job(self, job_id, title, reward, url, source)

    # Replace _process_new_job
    GengoWatcher._process_new_job = enhanced_process_new_job

    # Add async wrapper for high-value acceptance
    def _async_high_value_acceptance_wrapper(self, job_data: Dict[str, Any]):
        """Wrapper to run async high-value job acceptance in a thread."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.high_value_manager.process_job(job_data))
        except Exception as e:
            self.logger.error(f"Error in high-value job acceptance: {e}")
        finally:
            loop.close()

    GengoWatcher._async_high_value_acceptance_wrapper = _async_high_value_acceptance_wrapper

    # Add method to get high-value stats
    def get_high_value_stats(self):
        """Get high-value job statistics."""
        return self.high_value_manager.get_stats()

    GengoWatcher.get_high_value_stats = get_high_value_stats

    # Add method to manually check high-value eligibility
    def check_high_value_eligibility(self, reward: float) -> tuple[bool, str]:
        """Check if a reward amount qualifies as high-value."""
        return self.high_value_manager.is_high_value(reward)

    GengoWatcher.check_high_value_eligibility = check_high_value_eligibility


def create_enhanced_watcher(config, state, logger):
    """Create an enhanced GengoWatcher instance."""
    # Apply enhancements
    enhance_watcher_class()

    # Import and create the enhanced watcher
    from .watcher import GengoWatcher
    return GengoWatcher(config, state, logger)