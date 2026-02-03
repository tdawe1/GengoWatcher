#!/usr/bin/env python3
"""
CAPTCHA Safety Monitor for GengoWatcher
Monitors auto-captcha performance, costs, and safety metrics
"""

import time
import logging
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any
import threading


class CaptchaSafetyMonitor:
    """Monitors CAPTCHA solving safety and performance"""

    def __init__(self, log_file: str = "logs/captcha_safety.log"):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # Safety thresholds
        self.safety_thresholds = {
            "max_daily_cost": 50.0,  # Maximum $50/day
            "max_hourly_requests": 100,  # Max 100 requests/hour
            "max_failure_rate": 0.3,  # Max 30% failure rate
            "min_success_rate": 0.7,  # Minimum 70% success rate
            "max_consecutive_failures": 5,  # Max 5 consecutive failures
        }

        # Monitoring data
        self.stats = {
            "daily_stats": {},
            "hourly_stats": {},
            "alerts": [],
            "consecutive_failures": 0,
            "last_alert_time": 0,
        }

        self.lock = threading.Lock()
        self.is_monitoring = False

    def log_captcha_attempt(
        self,
        success: bool,
        captcha_type: str,
        cost: float = 0.0,
        response_time: float = 0.0,
        error: str = None,
    ):
        """Log a CAPTCHA solving attempt"""
        timestamp = time.time()
        hour_key = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d-%H")
        day_key = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")

        with self.lock:
            # Update hourly stats
            if hour_key not in self.stats["hourly_stats"]:
                self.stats["hourly_stats"][hour_key] = {
                    "requests": 0,
                    "successes": 0,
                    "failures": 0,
                    "total_cost": 0.0,
                    "total_response_time": 0.0,
                }

            hourly = self.stats["hourly_stats"][hour_key]
            hourly["requests"] += 1
            if success:
                hourly["successes"] += 1
                self.stats["consecutive_failures"] = 0
            else:
                hourly["failures"] += 1
                self.stats["consecutive_failures"] += 1

            hourly["total_cost"] += cost
            hourly["total_response_time"] += response_time

            # Update daily stats
            if day_key not in self.stats["daily_stats"]:
                self.stats["daily_stats"][day_key] = {
                    "requests": 0,
                    "successes": 0,
                    "failures": 0,
                    "total_cost": 0.0,
                    "total_response_time": 0.0,
                }

            daily = self.stats["daily_stats"][day_key]
            daily["requests"] += 1
            if success:
                daily["successes"] += 1
            else:
                daily["failures"] += 1
            daily["total_cost"] += cost
            daily["total_response_time"] += response_time

            # Check safety thresholds
            self._check_safety_thresholds(hour_key, day_key)

            # Log the attempt
            log_entry = {
                "timestamp": timestamp,
                "success": success,
                "captcha_type": captcha_type,
                "cost": cost,
                "response_time": response_time,
                "error": error,
                "consecutive_failures": self.stats["consecutive_failures"],
            }

            with open(self.log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

    def _check_safety_thresholds(self, hour_key: str, day_key: str):
        """Check if any safety thresholds have been exceeded"""
        current_time = time.time()

        # Only send alerts every 5 minutes to avoid spam
        if current_time - self.stats["last_alert_time"] < 300:
            return

        hourly = self.stats["hourly_stats"][hour_key]
        daily = self.stats["daily_stats"][day_key]

        alerts = []

        # Check daily cost limit
        if daily["total_cost"] > self.safety_thresholds["max_daily_cost"]:
            alerts.append(
                {
                    "level": "CRITICAL",
                    "message": f"Daily CAPTCHA cost exceeded: ${daily['total_cost']:.2f} > ${self.safety_thresholds['max_daily_cost']:.2f}",
                    "action": "Consider reducing automation or switching to cheaper service",
                }
            )

        # Check hourly request limit
        if hourly["requests"] > self.safety_thresholds["max_hourly_requests"]:
            alerts.append(
                {
                    "level": "WARNING",
                    "message": f"Hourly CAPTCHA requests exceeded: {hourly['requests']} > {self.safety_thresholds['max_hourly_requests']}",
                    "action": "Reduce request frequency or increase delays",
                }
            )

        # Check failure rate
        if hourly["requests"] >= 10:  # Only check after minimum sample size
            failure_rate = hourly["failures"] / hourly["requests"]
            if failure_rate > self.safety_thresholds["max_failure_rate"]:
                alerts.append(
                    {
                        "level": "ERROR",
                        "message": f"High CAPTCHA failure rate: {failure_rate:.1%} > {self.safety_thresholds['max_failure_rate']:.1%}",
                        "action": "Check API key validity or service status",
                    }
                )

            success_rate = hourly["successes"] / hourly["requests"]
            if success_rate < self.safety_thresholds["min_success_rate"]:
                alerts.append(
                    {
                        "level": "ERROR",
                        "message": f"Low CAPTCHA success rate: {success_rate:.1%} < {self.safety_thresholds['min_success_rate']:.1%}",
                        "action": "Consider switching CAPTCHA service or reducing complexity",
                    }
                )

        # Check consecutive failures
        if (
            self.stats["consecutive_failures"]
            >= self.safety_thresholds["max_consecutive_failures"]
        ):
            alerts.append(
                {
                    "level": "CRITICAL",
                    "message": f"Consecutive CAPTCHA failures: {self.stats['consecutive_failures']} >= {self.safety_thresholds['max_consecutive_failures']}",
                    "action": "Temporarily disable auto-captcha or investigate service issues",
                }
            )

        # Send alerts
        for alert in alerts:
            self.stats["alerts"].append(
                {
                    "timestamp": current_time,
                    "level": alert["level"],
                    "message": alert["message"],
                    "action": alert["action"],
                }
            )

            # Log alert
            logging.getLogger("captcha_safety").log(
                getattr(logging, alert["level"].upper(), logging.WARNING),
                f"CAPTCHA Safety Alert: {alert['message']} - {alert['action']}",
            )

        if alerts:
            self.stats["last_alert_time"] = current_time

    def get_stats_summary(self) -> Dict[str, Any]:
        """Get current statistics summary"""
        with self.lock:
            current_hour = datetime.now().strftime("%Y-%m-%d-%H")
            current_day = datetime.now().strftime("%Y-%m-%d")

            hourly = self.stats["hourly_stats"].get(current_hour, {})
            daily = self.stats["daily_stats"].get(current_day, {})

            return {
                "current_hour": {
                    "requests": hourly.get("requests", 0),
                    "successes": hourly.get("successes", 0),
                    "failures": hourly.get("failures", 0),
                    "cost": hourly.get("total_cost", 0.0),
                    "avg_response_time": (
                        hourly.get("total_response_time", 0.0)
                        / max(hourly.get("requests", 1), 1)
                    ),
                },
                "current_day": {
                    "requests": daily.get("requests", 0),
                    "successes": daily.get("successes", 0),
                    "failures": daily.get("failures", 0),
                    "cost": daily.get("total_cost", 0.0),
                    "avg_response_time": (
                        daily.get("total_response_time", 0.0)
                        / max(daily.get("requests", 1), 1)
                    ),
                },
                "consecutive_failures": self.stats["consecutive_failures"],
                "recent_alerts": (
                    self.stats["alerts"][-5:] if self.stats["alerts"] else []
                ),
            }

    def reset_stats(self, days_to_keep: int = 7):
        """Reset old statistics, keeping specified number of days"""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)

        with self.lock:
            # Clean up old hourly stats
            to_remove = []
            for hour_key in self.stats["hourly_stats"]:
                try:
                    stat_date = datetime.strptime(hour_key, "%Y-%m-%d-%H")
                    if stat_date < cutoff_date:
                        to_remove.append(hour_key)
                except ValueError:
                    to_remove.append(hour_key)

            for key in to_remove:
                del self.stats["hourly_stats"][key]

            # Clean up old daily stats
            to_remove = []
            for day_key in self.stats["daily_stats"]:
                try:
                    stat_date = datetime.strptime(day_key, "%Y-%m-%d")
                    if stat_date < cutoff_date:
                        to_remove.append(day_key)
                except ValueError:
                    to_remove.append(day_key)

            for key in to_remove:
                del self.stats["daily_stats"][key]

            # Clean up old alerts (keep last 100)
            if len(self.stats["alerts"]) > 100:
                self.stats["alerts"] = self.stats["alerts"][-100:]


def main():
    """Example usage and monitoring loop"""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("captcha_safety")

    monitor = CaptchaSafetyMonitor()

    # Example monitoring loop
    logger.info("CAPTCHA Safety Monitor started")

    while True:
        try:
            stats = monitor.get_stats_summary()
            logger.info(
                f"CAPTCHA Stats - Hourly: {stats['current_hour']['requests']} req, "
                f"${stats['current_hour']['cost']:.2f} cost, "
                f"{stats['consecutive_failures']} consecutive failures"
            )

            if stats["recent_alerts"]:
                logger.warning(f"Recent alerts: {len(stats['recent_alerts'])}")

            time.sleep(300)  # Check every 5 minutes

        except KeyboardInterrupt:
            logger.info("Stopping CAPTCHA safety monitor")
            break
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
