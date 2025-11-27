"""
Job Cancellation Manager for GengoWatcher
Handles automatic cancellation of lower-value jobs when higher-value ones become available.
"""

import logging
import json
import aiohttp
import asyncio
import time
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime


class JobCancellationManager:
    """Manages automatic job cancellation for better opportunities."""

    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.session: Optional[aiohttp.ClientSession] = None

        # Current job tracking
        self.current_job_id: Optional[str] = None
        self.current_job_reward: float = 0.0
        self.job_start_time: Optional[float] = None

        # Cancellation settings
        self.cancellation_enabled = True
        self.min_improvement_ratio = 2.0  # New job must be worth 2x more
        self.extreme_threshold = 1000.0  # Always cancel for jobs > $1000

        # Statistics
        self.stats = {
            "cancellations_count": 0,
            "total_lost_rewards": 0.0,
            "successful_cancellations": 0,
            "failed_cancellations": 0,
            "jobs_saved": [],
        }

        self.logger.info("Job Cancellation Manager initialized")

    async def initialize_session(self):
        """Initialize the HTTP session for API requests."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "User-Agent": "GengoWatcher/2.1.5",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            )
            self.logger.debug("HTTP session initialized for job cancellation")

    async def close_session(self):
        """Close the HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.logger.debug("HTTP session closed")

    def set_current_job(self, job_id: str, reward: float):
        """Track the currently accepted job."""
        self.current_job_id = job_id
        self.current_job_reward = reward
        self.job_start_time = time.time()

        self.logger.info(f"Now tracking current job: {job_id} (${reward:.2f})")

        # Log current job state
        self._save_job_state()

    def clear_current_job(self):
        """Clear current job tracking."""
        if self.current_job_id:
            job_duration = (
                time.time() - self.job_start_time if self.job_start_time else 0
            )

            self.logger.info(
                f"Clearing current job: {self.current_job_id} "
                f"(held for {job_duration:.1f}s)"
            )

        self.current_job_id = None
        self.current_job_reward = 0.0
        self.job_start_time = None

        # Clear job state
        self._save_job_state()

    def should_cancel_for_job(self, new_job_reward: float, new_job_id: str) -> bool:
        """Determine if current job should be cancelled for new opportunity."""
        if not self.cancellation_enabled:
            return False

        if not self.current_job_id:
            return False

        # Always cancel for extreme value jobs
        if new_job_reward >= self.extreme_threshold:
            self.logger.warning(
                f"🚨 EXTREME VALUE JOB DETECTED: ${new_job_reward:.2f} "
                f"- Will cancel current job!"
            )
            return True

        # Check improvement ratio
        improvement_ratio = new_job_reward / self.current_job_reward

        if improvement_ratio >= self.min_improvement_ratio:
            self.logger.info(
                f"💹 Better opportunity detected: ${new_job_reward:.2f} "
                f"vs current ${self.current_job_reward:.2f} "
                f"({improvement_ratio:.1f}x improvement)"
            )
            return True

        return False

    async def cancel_current_job(self) -> bool:
        """Cancel the currently tracked job."""
        if not self.current_job_id:
            self.logger.warning("No current job to cancel")
            return False

        self.logger.info(
            f"🔄 Cancelling job {self.current_job_id} "
            f"(${self.current_job_reward:.2f}) for better opportunity"
        )

        try:
            await self.initialize_session()

            # Get authentication credentials
            user_session = self.config.config["WebSocket"]["user_session"]

            if not user_session or user_session == "REPLACE_WITH_YOUR_SESSION_TOKEN":
                self.logger.error(
                    "User session token not configured for job cancellation"
                )
                return False

            # Set up authentication headers
            headers = {
                "Cookie": f"my_gengo_session={user_session}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
                "Origin": "https://gengo.com",
                "Referer": f"https://gengo.com/t/jobs/details/{self.current_job_id}",
                "X-Requested-With": "XMLHttpRequest",
            }

            # Step 1: Check if job is still active
            job_url = f"https://gengo.com/t/jobs/details/{self.current_job_id}"

            async with self.session.get(job_url, headers=headers) as response:
                if response.status != 200:
                    self.logger.error(f"Cannot access job page: {response.status}")
                    return False

                content = await response.text()

                # Check if job is already completed/failed
                if (
                    "job not found" in content.lower()
                    or "job completed" in content.lower()
                ):
                    self.logger.info(f"Job {self.current_job_id} is no longer active")
                    self.clear_current_job()
                    return True

            # Step 2: Submit cancellation request
            cancel_url = f"https://gengo.com/t/jobs/cancel/{self.current_job_id}"

            # The cancellation likely requires a form submission
            cancel_data = {
                "confirm": "1",
                "forfeit_reward": "1",  # Ticking the forfeit reward box
                "reason": "Cancelling for higher value opportunity",
            }

            self.logger.debug(f"Submitting cancellation for job {self.current_job_id}")

            async with self.session.post(
                cancel_url, headers=headers, data=cancel_data, timeout=30
            ) as response:
                self.logger.debug(f"Cancellation response status: {response.status}")

                if response.status == 200:
                    content = await response.text()

                    # Check for success indicators
                    if (
                        "job cancelled" in content.lower()
                        or "cancellation successful" in content.lower()
                        or "job successfully cancelled" in content.lower()
                    ):

                        self.logger.info(
                            f"✅ Successfully cancelled job {self.current_job_id}"
                        )

                        # Update stats
                        self.stats["successful_cancellations"] += 1
                        self.stats["total_lost_rewards"] += self.current_job_reward

                        # Record cancellation
                        self.stats["jobs_saved"].append(
                            {
                                "cancelled_job_id": self.current_job_id,
                                "cancelled_reward": self.current_job_reward,
                                "timestamp": datetime.now().isoformat(),
                                "job_duration": (
                                    time.time() - self.job_start_time
                                    if self.job_start_time
                                    else 0
                                ),
                            }
                        )

                        # Clear tracking
                        self.clear_current_job()
                        self._save_job_state()

                        return True
                    else:
                        self.logger.error(
                            "Cancellation may have failed - unexpected response"
                        )
                        self.stats["failed_cancellations"] += 1
                        return False

                elif response.status == 302 or response.status == 303:
                    # Redirect might indicate success
                    self.logger.info(
                        f"✅ Job {self.current_job_id} cancelled (redirect response)"
                    )

                    # Update stats
                    self.stats["successful_cancellations"] += 1
                    self.stats["total_lost_rewards"] += self.current_job_reward

                    self.clear_current_job()
                    self._save_job_state()

                    return True
                else:
                    self.logger.error(
                        f"Failed to cancel job {self.current_job_id}, "
                        f"status: {response.status}"
                    )
                    self.stats["failed_cancellations"] += 1
                    return False

        except aiohttp.ClientError as e:
            self.logger.error(f"HTTP client error cancelling job: {e}")
            self.stats["failed_cancellations"] += 1
            return False
        except asyncio.TimeoutError as e:
            self.logger.error(f"Timeout error cancelling job: {e}")
            self.stats["failed_cancellations"] += 1
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error cancelling job: {e}")
            self.stats["failed_cancellations"] += 1
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get cancellation statistics."""
        return {
            **self.stats,
            "current_job": {
                "id": self.current_job_id,
                "reward": self.current_job_reward,
                "duration": (
                    time.time() - self.job_start_time
                    if self.job_start_time and self.current_job_id
                    else 0
                ),
            },
            "settings": {
                "cancellation_enabled": self.cancellation_enabled,
                "min_improvement_ratio": self.min_improvement_ratio,
                "extreme_threshold": self.extreme_threshold,
            },
        }

    def _save_job_state(self):
        """Save current job state to file for persistence."""
        state_file = Path("logs/job_cancellation_state.json")
        state_file.parent.mkdir(exist_ok=True)

        state = {
            "current_job_id": self.current_job_id,
            "current_job_reward": self.current_job_reward,
            "job_start_time": self.job_start_time,
            "stats": self.stats,
        }

        try:
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save job state: {e}")

    def load_job_state(self):
        """Load job state from file."""
        state_file = Path("logs/job_cancellation_state.json")

        if not state_file.exists():
            return

        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)

            self.current_job_id = state.get("current_job_id")
            self.current_job_reward = state.get("current_job_reward", 0.0)
            self.job_start_time = state.get("job_start_time")

            # Load stats if available
            if "stats" in state:
                self.stats.update(state["stats"])

            self.logger.info(
                f"Loaded job state: current job {self.current_job_id} "
                f"(${self.current_job_reward:.2f})"
            )

        except Exception as e:
            self.logger.error(f"Failed to load job state: {e}")

    def update_settings(self, **kwargs):
        """Update cancellation settings."""
        if "cancellation_enabled" in kwargs:
            self.cancellation_enabled = kwargs["cancellation_enabled"]
            self.logger.info(f"Cancellation enabled: {self.cancellation_enabled}")

        if "min_improvement_ratio" in kwargs:
            self.min_improvement_ratio = kwargs["min_improvement_ratio"]
            self.logger.info(
                f"Minimum improvement ratio: {self.min_improvement_ratio}x"
            )

        if "extreme_threshold" in kwargs:
            self.extreme_threshold = kwargs["extreme_threshold"]
            self.logger.info(f"Extreme value threshold: ${self.extreme_threshold}")

        self._save_job_state()
