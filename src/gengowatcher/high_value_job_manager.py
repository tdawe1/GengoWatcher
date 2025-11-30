"""
High-Value Job Manager for GengoWatcher
Optimized for MAXIMUM SPEED response to high-value jobs.
"""

import time
import asyncio
import logging
import json
import random
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

from .job_acceptance import JobAcceptanceEngine
from .config import AppConfig
from .captcha_manager import CaptchaSolverManager
from .job_cancellation_manager import JobCancellationManager


@dataclass
class JobStats:
    """Statistics for tracking job patterns."""
    total_seen: int = 0
    high_value_seen: int = 0
    high_value_accepted: int = 0
    high_value_missed: int = 0
    last_high_value: Optional[datetime] = None
    acceptance_times: List[float] = None

    def __post_init__(self):
        if self.acceptance_times is None:
            self.acceptance_times = []


class HighValueJobManager:
    """Specialized manager for high-value jobs - OPTIMIZED FOR SPEED."""

    def __init__(self, config: AppConfig, logger: logging.Logger,
                 captcha_solver: Optional[CaptchaSolverManager] = None):
        self.config = config
        self.logger = logger
        self.captcha_solver = captcha_solver

        # High-value thresholds
        self.high_value_threshold = float(config.get("HighValue", "threshold"))
        self.very_high_value_threshold = float(config.get("HighValue", "very_high_threshold"))
        self.extreme_value_threshold = float(config.get("HighValue", "extreme_threshold"))

        # SPEED SETTINGS - MINIMUM DELAYS
        self.immediate_response = True  # No waiting for high-value jobs
        self.min_processing_delay = 0.001  # 1ms minimum processing time

        # Safety limits (set high or disable)
        self.max_high_value_per_day = int(config.get("HighValue", "max_per_day"))
        self.min_interval_between = int(config.get("HighValue", "min_interval_seconds"))  # 1 second minimum

        # Statistics
        self.stats = JobStats()
        self.last_acceptance_time = 0
        self.daily_acceptances = []

        # Job acceptance engine - configure for speed
        self.acceptance_engine = JobAcceptanceEngine(config, logger, captcha_solver)
        # Override acceptance engine delays for maximum speed
        self.acceptance_engine.max_retries = 10  # More retries for high-value
        self.acceptance_engine.retry_delay = 0.5  # Faster retry

        # Job cancellation manager
        self.cancellation_manager = JobCancellationManager(config, logger)
        # Update settings from config
        self.cancellation_manager.update_settings(
            cancellation_enabled=config.get("Cancellation", "enabled"),
            min_improvement_ratio=float(config.get("Cancellation", "min_improvement_ratio")),
            extreme_threshold=float(config.get("Cancellation", "extreme_threshold"))
        )
        # Load any existing job state
        self.cancellation_manager.load_job_state()

        # History tracking
        self.job_history_file = Path("logs/high_value_jobs.json")
        self._load_job_history()

        self.logger.info("⚡ HIGH-SPEED High-Value Job Manager initialized")
        self.logger.info(f"Thresholds: High=${self.high_value_threshold}, "
                        f"Very High=${self.very_high_value_threshold}, "
                        f"Extreme=${self.extreme_value_threshold}")
        self.logger.info("⚠️  MAXIMUM SPEED MODE ENABLED - No artificial delays")

    def _load_job_history(self):
        """Load historical high-value job data."""
        if self.job_history_file.exists():
            try:
                with open(self.job_history_file, 'r') as f:
                    data = json.load(f)
                    self.daily_acceptances = data.get('daily_acceptances', [])
                    self.stats.total_seen = data.get('total_seen', 0)
                    self.stats.high_value_seen = data.get('high_value_seen', 0)
                    self.stats.high_value_accepted = data.get('high_value_accepted', 0)
                    self.stats.high_value_missed = data.get('high_value_missed', 0)
            except Exception as e:
                self.logger.error(f"Failed to load job history: {e}")

    def _save_job_history(self):
        """Save historical high-value job data."""
        try:
            self.job_history_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                'daily_acceptances': self.daily_acceptances[-30:],
                'total_seen': self.stats.total_seen,
                'high_value_seen': self.stats.high_value_seen,
                'high_value_accepted': self.stats.high_value_accepted,
                'high_value_missed': self.stats.high_value_missed,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.job_history_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save job history: {e}")

    def is_high_value(self, reward: float) -> tuple[bool, str]:
        """Check if a job qualifies as high-value and return its category."""
        if reward >= self.extreme_value_threshold:
            return True, "EXTREME"
        elif reward >= self.very_high_value_threshold:
            return True, "VERY_HIGH"
        elif reward >= self.high_value_threshold:
            return True, "HIGH"
        return False, ""

    def can_accept_high_value(self, reward: float, category: str) -> tuple[bool, str]:
        """Check if we can accept a high-value job."""
        current_time = time.time()

        # For extreme values, always accept
        if category == "EXTREME":
            return True, "EXTREME value - INSTANT ACCEPT"

        # Minimal checks for other high-value jobs
        if current_time - self.last_acceptance_time < self.min_interval_between:
            wait_time = self.min_interval_between - (current_time - self.last_acceptance_time)
            return False, f"Minimum interval not met (wait {wait_time:.3f}s)"

        return True, "ACCEPT"

    def calculate_response_time(self, reward: float, category: str) -> float:
        """Calculate response time - ABSOLUTE MINIMUM."""
        # Immediate response for all high-value jobs
        if self.immediate_response:
            # Only minimum processing delay
            return self.min_processing_delay
        else:
            # Fallback to very fast response
            return random.uniform(0.001, 0.01)  # 1-10ms maximum

    async def process_job(self, job_data: Dict[str, Any]) -> bool:
        """Process a high-value job with MAXIMUM SPEED."""
        job_id = job_data.get("id")
        reward = float(job_data.get("reward", 0))
        self.stats.total_seen += 1

        # Check if we should cancel current job for this one
        if self.cancellation_manager.should_cancel_for_job(reward, job_id):
            self.logger.warning("🔄 CANCELLING CURRENT JOB FOR BETTER OPPORTUNITY!")

            # Attempt cancellation
            cancel_success = await self.cancellation_manager.cancel_current_job()
            if cancel_success:
                self.logger.info(f"✅ Current job cancelled, now accepting {job_id} (${reward:.2f})")
            else:
                self.logger.error(f"❌ Failed to cancel current job - may not be able to accept {job_id}")
                # Continue anyway - might still be able to accept

        # Check if it's high-value
        is_hv, category = self.is_high_value(reward)
        if not is_hv:
            return False

        self.stats.high_value_seen += 1
        self.logger.info(f"🚀 HIGH-VALUE JOB! Job {job_id}, Reward: ${reward:.2f} ({category})")
        self.logger.info("⚡ INITIATING INSTANT ACCEPTANCE SEQUENCE")

        # Check if we can accept
        can_accept, reason = self.can_accept_high_value(reward, category)
        if not can_accept:
            self.logger.warning(f"Cannot accept high-value job {job_id}: {reason}")
            self.stats.high_value_missed += 1
            self._notify_missed_opportunity(job_data, category, reason)
            return False

        # Calculate minimal response time
        response_time = self.calculate_response_time(reward, category)
        if response_time > 0.01:  # Only wait if absolutely necessary
            self.logger.debug(f"Minimal delay: {response_time*1000:.1f}ms")
            await asyncio.sleep(response_time)

        # ATTEMPT IMMEDIATE ACCEPTANCE
        start_time = time.time()
        success = await self.acceptance_engine.accept_job(job_data)
        acceptance_time = time.time() - start_time

        # Record results
        if success:
            self.stats.high_value_accepted += 1
            self.last_acceptance_time = time.time()
            self.stats.acceptance_times.append(acceptance_time)

            # Track current job for potential cancellation
            self.cancellation_manager.set_current_job(job_id, reward)

            # Record in daily log
            self.daily_acceptances.append({
                'job_id': job_id,
                'reward': reward,
                'category': category,
                'time': datetime.now().isoformat(),
                'response_time': response_time,
                'acceptance_time': acceptance_time
            })

            self.logger.info(f"✅ ACCEPTED HIGH-VALUE JOB {job_id} in {acceptance_time:.3f}s!")
            self._notify_success(job_data, category, response_time, acceptance_time)
        else:
            self.stats.high_value_missed += 1
            self.logger.error(f"❌ FAILED TO ACCEPT HIGH-VALUE JOB {job_id}")
            self._notify_failure(job_data, category)

        # Save history
        self._save_job_history()

        return success

    def _notify_success(self, job_data: Dict[str, Any], category: str,
                       response_time: float, acceptance_time: float):
        """Send notification for successful high-value job acceptance."""
        # Play sound if enabled
        if self.config.get("Paths", "enable_sound"):
            from .ui import play_sound
            play_sound(self.config.get("Paths", "sound_file"))

        # Send desktop notification
        if self.config.get("HighValue", "desktop_notifications"):
            try:
                import subprocess
                title = "🎉 HIGH-VALUE JOB ACCEPTED!"
                message = (f"${job_data.get('reward', 0):.2f} - {category}\n"
                          f"Acceptance time: {acceptance_time:.3f}s")

                # Try different notification methods
                if subprocess.run(['which', 'notify-send'], capture_output=True).returncode == 0:
                    subprocess.run(['notify-send', '-u', 'critical', title, message])
                elif subprocess.run(['which', 'osascript'], capture_output=True).returncode == 0:
                    script = f'display notification "{message}" with title "{title}" sound name "Glass"'
                    subprocess.run(['osascript', '-e', script])
            except Exception as e:
                self.logger.error(f"Failed to send desktop notification: {e}")

    def _notify_missed_opportunity(self, job_data: Dict[str, Any], category: str, reason: str):
        """Notify about missed high-value opportunities."""
        if self.config.get("HighValue", "notify_on_missed"):
            self.logger.warning(f"💔 MISSED HIGH-VALUE: ${job_data.get('reward', 0):.2f} - {reason}")

    def _notify_failure(self, job_data: Dict[str, Any], category: str):
        """Notify about failed acceptance attempts."""
        self.logger.error(f"💥 ACCEPTANCE FAILED: ${job_data.get('reward', 0):.2f}")

    def clear_current_job(self):
        """Clear current job tracking (call when job is completed/failed)."""
        self.cancellation_manager.clear_current_job()

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics."""
        success_rate = 0
        if self.stats.high_value_seen > 0:
            success_rate = (self.stats.high_value_accepted / self.stats.high_value_seen) * 100

        avg_response_time = 0
        if self.stats.acceptance_times:
            avg_response_time = sum(self.stats.acceptance_times) / len(self.stats.acceptance_times)

        # Today's stats
        today = datetime.now().date()
        today_count = len([a for a in self.daily_acceptances
                          if datetime.fromisoformat(a['time']).date() == today])

        return {
            'total_jobs_seen': self.stats.total_seen,
            'high_value_seen': self.stats.high_value_seen,
            'high_value_accepted': self.stats.high_value_accepted,
            'high_value_missed': self.stats.high_value_missed,
            'success_rate': success_rate,
            'average_response_time': avg_response_time,
            'today_accepted': today_count,
            'last_high_value': self.stats.last_high_value.isoformat() if self.stats.last_high_value else None,
            'thresholds': {
                'high': self.high_value_threshold,
                'very_high': self.very_high_value_threshold,
                'extreme': self.extreme_value_threshold
            },
            'speed_mode': 'MAXIMUM - No artificial delays',
            'cancellation': self.cancellation_manager.get_stats()
        }

    def should_auto_accept(self, job_data: Dict[str, Any]) -> bool:
        """Quick check if job should be considered for auto-acceptance."""
        reward = float(job_data.get("reward", 0))
        is_hv, _ = self.is_high_value(reward)
        return is_hv