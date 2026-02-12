#!/usr/bin/env python3
"""
Gengo Job Pattern Analyzer
Analyzes job posting patterns, rates, and system behavior to determine safe automation limits.
"""

import time
import json
import asyncio
import logging
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict, deque
import websockets
import aiohttp
from pathlib import Path

from src.gengowatcher.config import AppConfig
from src.gengowatcher.state import AppState


class GengoAnalyzer:
    """Analyzes Gengo's job patterns and rate limits through passive monitoring."""

    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger

        # Data collection
        self.job_postings = []
        self.websocket_messages = []
        self.captcha_events = []
        self.acceptance_responses = []

        # Analysis data
        self.job_intervals = deque(maxlen=1000)
        self.hourly_job_counts = defaultdict(int)
        self.reward_distribution = []

        # Monitoring state
        self.start_time = time.time()
        self.session_jobs = set()

    async def monitor_websocket_traffic(self, duration_hours: int = 24):
        """
        Monitor the Gengo live WebSocket feed, record messages and job postings, and run pattern analysis.

        Connects to the live-dashboard WebSocket, authenticates with configured credentials, records incoming messages, extracts and records new job postings (including reward, language pair, word count and timestamps), computes inter-job intervals and hourly counts, and stops when the specified duration elapses; after monitoring completes, triggers analysis of the collected data. JSON decode errors are ignored and unexpected connection errors are logged.

        Parameters:
            duration_hours (int): Number of hours to monitor the WebSocket feed.
        """
        self.logger.info(f"Starting WebSocket monitoring for {duration_hours} hours")

        ws_url = "wss://live-dashboard.gengo.com"

        try:
            extra_headers = [
                (
                    "Cookie",
                    f"my_gengo_session={self.config.get('WebSocket', 'user_session')}",
                ),
                ("Origin", "https://gengo.com"),
                (
                    "User-Agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
                ),
            ]

            ws_version = getattr(websockets, "__version__", "0")
            ws_header_key = (
                "additional_headers"
                if int(ws_version.split(".")[0]) >= 12
                else "extra_headers"
            )
            header_kwargs = {ws_header_key: extra_headers}

            async with websockets.connect(
                ws_url, **header_kwargs, ping_interval=20, ping_timeout=10
            ) as websocket:
                # Authenticate
                auth_payload = {
                    "user_id": self.config.get("WebSocket", "user_id"),
                    "user_session": self.config.get("WebSocket", "user_session"),
                    "user_key": self.config.get("WebSocket", "user_key"),
                }
                await websocket.send(json.dumps(auth_payload))

                self.logger.info("WebSocket connected for analysis")
                start_time = time.time()

                async for message in websocket:
                    msg_time = time.time()
                    try:
                        data = json.loads(message)

                        # Record all messages
                        self.websocket_messages.append(
                            {
                                "timestamp": msg_time,
                                "type": data.get("type"),
                                "data": data,
                            }
                        )

                        # Track job postings
                        if data.get("type") == "available_collection":
                            job = data.get("collection", {})
                            job_id = job.get("id")

                            if job_id and job_id not in self.session_jobs:
                                self.session_jobs.add(job_id)

                                job_data = {
                                    "id": job_id,
                                    "timestamp": msg_time,
                                    "reward": float(job.get("rewards", 0)),
                                    "language_pair": f"{job.get('lc_src')}->{job.get('lc_tgt')}",
                                    "word_count": job.get("word_count", 0),
                                    "group_id": job.get("group_id"),
                                }

                                self.job_postings.append(job_data)
                                self.reward_distribution.append(job_data["reward"])

                                # Calculate interval from previous job
                                if len(self.job_postings) > 1:
                                    interval = (
                                        msg_time - self.job_postings[-2]["timestamp"]
                                    )
                                    self.job_intervals.append(interval)

                                # Track hourly distribution
                                hour_key = datetime.fromtimestamp(msg_time).strftime(
                                    "%Y-%m-%d %H:00"
                                )
                                self.hourly_job_counts[hour_key] += 1

                                self.logger.debug(
                                    f"Job posted: {job_id}, reward: ${job_data['reward']:.2f}"
                                )

                        # Check if monitoring duration reached
                        if msg_time - start_time > duration_hours * 3600:
                            break

                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            self.logger.error(f"WebSocket monitoring error: {e}")

        self._analyze_patterns()

    def _analyze_patterns(self):
        """Analyze collected job posting patterns."""
        if not self.job_postings:
            self.logger.warning("No jobs posted during monitoring period")
            return

        self.logger.info("\n=== JOB POSTING PATTERN ANALYSIS ===")

        # Basic statistics
        total_jobs = len(self.job_postings)
        monitoring_duration = time.time() - self.start_time
        jobs_per_hour = total_jobs / (monitoring_duration / 3600)

        self.logger.info(f"Total jobs monitored: {total_jobs}")
        self.logger.info(
            f"Monitoring duration: {timedelta(seconds=int(monitoring_duration))}"
        )
        self.logger.info(f"Average job rate: {jobs_per_hour:.2f} jobs/hour")

        # Interval analysis
        if self.job_intervals:
            avg_interval = statistics.mean(self.job_intervals)
            median_interval = statistics.median(self.job_intervals)
            min_interval = min(self.job_intervals)
            max_interval = max(self.job_intervals)

            self.logger.info(f"\nTime between jobs:")
            self.logger.info(f"  Average: {avg_interval:.2f} seconds")
            self.logger.info(f"  Median: {median_interval:.2f} seconds")
            self.logger.info(f"  Shortest: {min_interval:.2f} seconds")
            self.logger.info(f"  Longest: {max_interval/60:.1f} minutes")

            # Detect patterns
            if min_interval < 5:
                self.logger.warning(
                    "⚠️  Jobs posted in rapid succession (<5s) - possible batch posting"
                )

        # Reward distribution
        if self.reward_distribution:
            avg_reward = statistics.mean(self.reward_distribution)
            median_reward = statistics.median(self.reward_distribution)
            min_reward = min(self.reward_distribution)
            max_reward = max(self.reward_distribution)

            self.logger.info(f"\nReward distribution:")
            self.logger.info(f"  Average: ${avg_reward:.2f}")
            self.logger.info(f"  Median: ${median_reward:.2f}")
            self.logger.info(f"  Range: ${min_reward:.2f} - ${max_reward:.2f}")

        # Hourly patterns
        if len(self.hourly_job_counts) > 1:
            self.logger.info(f"\nHourly distribution:")
            for hour, count in sorted(self.hourly_job_counts.items())[
                -10:
            ]:  # Show last 10 hours
                self.logger.info(f"  {hour}: {count} jobs")

        # Peak hour analysis
        peak_hour = max(self.hourly_job_counts.items(), key=lambda x: x[1])
        self.logger.info(f"\nPeak hour: {peak_hour[0]} with {peak_hour[1]} jobs")

        # Save detailed data
        self._save_analysis_data()

    def _save_analysis_data(self):
        """Save analysis data to files for further review."""
        output_dir = Path("analysis")
        output_dir.mkdir(exist_ok=True)

        # Save job postings
        with open(output_dir / "job_postings.json", "w") as f:
            json.dump(self.job_postings, f, indent=2)

        # Save intervals
        with open(output_dir / "job_intervals.json", "w") as f:
            json.dump(list(self.job_intervals), f)

        # Generate report
        report = {
            "analysis_timestamp": datetime.now().isoformat(),
            "monitoring_duration_seconds": time.time() - self.start_time,
            "total_jobs_posted": len(self.job_postings),
            "jobs_per_hour": len(self.job_postings)
            / ((time.time() - self.start_time) / 3600),
            "average_interval_seconds": (
                statistics.mean(self.job_intervals) if self.job_intervals else 0
            ),
            "average_reward": (
                statistics.mean(self.reward_distribution)
                if self.reward_distribution
                else 0
            ),
            "peak_hour": (
                max(self.hourly_job_counts.items(), key=lambda x: x[1])[0]
                if self.hourly_job_counts
                else None
            ),
            "peak_hour_count": (
                max(self.hourly_job_counts.values()) if self.hourly_job_counts else 0
            ),
        }

        with open(output_dir / "analysis_report.json", "w") as f:
            json.dump(report, f, indent=2)

        self.logger.info(f"\nAnalysis data saved to {output_dir}/")

    async def test_acceptance_limits(self):
        """Test different acceptance patterns to find safe limits."""
        self.logger.info("\n=== ACCEPTANCE LIMIT TESTING ===")

        # Note: This should be done cautiously with manual review
        test_patterns = [
            {"name": "Very Conservative", "interval": 3600, "count": 1},  # 1 job/hour
            {"name": "Conservative", "interval": 1800, "count": 2},  # 2 jobs/hour
            {"name": "Moderate", "interval": 900, "count": 4},  # 4 jobs/hour
            {"name": "Aggressive", "interval": 600, "count": 6},  # 6 jobs/hour
        ]

        # This would require actual job acceptance implementation
        # For now, we'll just log the recommendations
        for pattern in test_patterns:
            jobs_per_hour = pattern["count"] * (3600 / pattern["interval"])
            self.logger.info(
                f"{pattern['name']}: {pattern['count']} jobs every {pattern['interval']/60:.0f} minutes "
                f"({jobs_per_hour:.1f} jobs/hour)"
            )

        self.logger.info(
            "\n⚠️  IMPORTANT: Actual acceptance testing should be done manually "
            "starting with the 'Very Conservative' pattern"
        )

    async def analyze_captcha_patterns(self):
        """Analyze when and how often CAPTCHAs appear."""
        self.logger.info("\n=== CAPTCHA PATTERN ANALYSIS ===")

        # This would track:
        # 1. Frequency of CAPTCHA challenges
        # 2. Types of CAPTCHAs (v2, v3, hCaptcha)
        # 3. Success rates of solving attempts
        # 4. Time taken to solve

        # Current implementation logs can be analyzed
        log_path = Path("logs/gengowatcher.log")
        if log_path.exists():
            captcha_events = []
            with open(log_path, "r") as f:
                for line in f:
                    if "captcha" in line.lower() or "recaptcha" in line.lower():
                        captcha_events.append(line.strip())

            self.logger.info(f"Found {len(captcha_events)} CAPTCHA-related log entries")

            # Analyze patterns
            recent_captchas = [
                e for e in captcha_events if "2025-09-17" in e
            ]  # Today's entries
            self.logger.info(f"Recent CAPTCHA events: {len(recent_captchas)}")

            if recent_captchas:
                self.logger.info("Sample CAPTCHA events:")
                for event in recent_captchas[-5:]:  # Show last 5
                    self.logger.info(f"  {event}")
        else:
            self.logger.info("No log file found for CAPTCHA analysis")


async def main():
    """
    Initialise logging, validate required WebSocket credentials in config, run the Gengo analysis sequence, and emit final recommendations.

    This coroutine sets up the logger, ensures a valid WebSocket session token and browser user key are present in the configuration (exits early if missing), and then executes the analyzer workflow: monitor WebSocket traffic, run acceptance-limit tests, and analyse CAPTCHA patterns. It logs a short set of post-run recommendations.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger("GengoAnalyzer")

    config = AppConfig()
    state = AppState()

    analyzer = GengoAnalyzer(config, logger)

    # Check if configuration is valid
    session = config.get("WebSocket", "user_session")
    user_key = config.get("WebSocket", "user_key")
    if not session or session == "REPLACE_WITH_YOUR_SESSION_TOKEN":
        logger.error("Please configure your session token in config.ini")
        return
    if not user_key or user_key == "REPLACE_WITH_YOUR_USER_KEY":
        logger.error(
            "Please configure your browser user key (DevTools → Application → Local Storage → userKey) in config.ini"
        )
        return

    # Run analysis
    await analyzer.monitor_websocket_traffic(duration_hours=1)  # Start with 1 hour
    await analyzer.test_acceptance_limits()
    await analyzer.analyze_captcha_patterns()

    logger.info("\n=== RECOMMENDATIONS ===")
    logger.info("1. Start with Very Conservative acceptance pattern (1 job/hour)")
    logger.info("2. Monitor for CAPTCHA frequency increases")
    logger.info("3. Watch for any account warnings or unusual behavior")
    logger.info("4. Gradually increase if no issues detected")
    logger.info("5. Never exceed 10% of available jobs in any hour period")


if __name__ == "__main__":
    asyncio.run(main())
