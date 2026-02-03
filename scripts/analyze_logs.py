#!/usr/bin/env python3
"""
Analyze existing GengoWatcher logs to understand patterns and detection triggers.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, Counter
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns


class LogAnalyzer:
    """Analyzes GengoWatcher logs for patterns and insights."""

    def __init__(self, log_path: str = "logs/gengowatcher.log"):
        self.log_path = Path(log_path)
        self.log_entries = []
        self.job_events = []
        self.acceptance_events = []
        self.captcha_events = []
        self.error_events = []

    def parse_logs(self):
        """Parse log file and categorize events."""
        if not self.log_path.exists():
            print(f"Log file not found: {self.log_path}")
            return

        print(f"Parsing log file: {self.log_path}")

        log_pattern = re.compile(
            r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - "
            r"(?P<logger>\w+) - (?P<level>\w+) - (?P<message>.*)"
        )

        with open(self.log_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                match = log_pattern.match(line)
                if match:
                    entry = {
                        "timestamp": datetime.strptime(
                            match.group("timestamp"), "%Y-%m-%d %H:%M:%S,%f"
                        ),
                        "logger": match.group("logger"),
                        "level": match.group("level"),
                        "message": match.group("message"),
                        "line_num": line_num,
                    }
                    self.log_entries.append(entry)

                    # Categorize events
                    message = entry["message"].lower()

                    if "job" in message and any(
                        word in message for word in ["found", "detected", "available"]
                    ):
                        self.job_events.append(entry)
                    elif "accept" in message and any(
                        word in message
                        for word in ["auto", "attempting", "successfully"]
                    ):
                        self.acceptance_events.append(entry)
                    elif any(
                        word in message for word in ["captcha", "recaptcha", "hcaptcha"]
                    ):
                        self.captcha_events.append(entry)
                    elif entry["level"] == "ERROR":
                        self.error_events.append(entry)

        print(f"Parsed {len(self.log_entries)} log entries")
        print(f"Found {len(self.job_events)} job events")
        print(f"Found {len(self.acceptance_events)} acceptance events")
        print(f"Found {len(self.captcha_events)} CAPTCHA events")
        print(f"Found {len(self.error_events)} error events")

    def analyze_job_patterns(self):
        """Analyze job detection patterns."""
        print("\n=== JOB PATTERN ANALYSIS ===")

        if not self.job_events:
            print("No job events found")
            return

        # Time between job detections
        intervals = []
        for i in range(1, len(self.job_events)):
            interval = (
                self.job_events[i]["timestamp"] - self.job_events[i - 1]["timestamp"]
            ).total_seconds()
            intervals.append(interval)

        if intervals:
            print(
                f"Average time between jobs: {sum(intervals)/len(intervals):.2f} seconds"
            )
            print(f"Shortest interval: {min(intervals):.2f} seconds")
            print(f"Longest interval: {max(intervals)/60:.1f} minutes")

            # Distribution of intervals
            short_intervals = [i for i in intervals if i < 60]
            print(
                f"Jobs posted < 60s apart: {len(short_intervals)} ({len(short_intervals)/len(intervals)*100:.1f}%)"
            )

        # Hourly distribution
        hourly_counts = defaultdict(int)
        for event in self.job_events:
            hour = event["timestamp"].hour
            hourly_counts[hour] += 1

        print("\nJobs by hour of day:")
        for hour in sorted(hourly_counts.keys()):
            print(f"  {hour:02d}:00 - {hourly_counts[hour]:2d} jobs")

    def analyze_acceptance_patterns(self):
        """Analyze job acceptance patterns and success rates."""
        print("\n=== ACCEPTANCE PATTERN ANALYSIS ===")

        if not self.acceptance_events:
            print("No acceptance events found")
            return

        # Count successful vs failed
        successful = [
            e for e in self.acceptance_events if "successfully" in e["message"].lower()
        ]
        failed = [
            e
            for e in self.acceptance_events
            if any(
                word in e["message"].lower() for word in ["failed", "error", "timeout"]
            )
        ]

        print(f"Successful acceptances: {len(successful)}")
        print(f"Failed acceptances: {len(failed)}")
        if len(self.acceptance_events) > 0:
            success_rate = len(successful) / len(self.acceptance_events) * 100
            print(f"Success rate: {success_rate:.1f}%")

        # Rate limiting detection
        rate_limited = [
            e for e in self.acceptance_events if "rate limit" in e["message"].lower()
        ]
        if rate_limited:
            print(f"\nRate limiting events: {len(rate_limited)}")
            for event in rate_limited[-5:]:  # Show last 5
                print(f"  {event['timestamp']} - {event['message']}")

        # Acceptance frequency
        if len(successful) > 1:
            acceptance_times = [e["timestamp"] for e in successful]
            intervals = [
                (acceptance_times[i] - acceptance_times[i - 1]).total_seconds()
                for i in range(1, len(acceptance_times))
            ]

            if intervals:
                avg_acceptance_interval = sum(intervals) / len(intervals)
                print(
                    f"\nAverage time between successful acceptances: {avg_acceptance_interval/60:.1f} minutes"
                )

    def analyze_captcha_patterns(self):
        """Analyze CAPTCHA challenge patterns."""
        print("\n=== CAPTCHA PATTERN ANALYSIS ===")

        if not self.captcha_events:
            print("No CAPTCHA events found")
            return

        # CAPTCHA types
        recaptcha_v2 = [
            e for e in self.captcha_events if "recaptcha.*v2" in e["message"].lower()
        ]
        recaptcha_v3 = [
            e for e in self.captcha_events if "recaptcha.*v3" in e["message"].lower()
        ]
        hcaptcha = [
            e for e in self.captcha_events if "hcaptcha" in e["message"].lower()
        ]

        print(f"reCAPTCHA v2: {len(recaptcha_v2)} events")
        print(f"reCAPTCHA v3: {len(recaptcha_v3)} events")
        print(f"hCaptcha: {len(hcaptcha)} events")

        # Solution attempts
        solved = [
            e
            for e in self.captcha_events
            if "successfully solved" in e["message"].lower()
        ]
        failed_solve = [
            e
            for e in self.captcha_events
            if any(
                word in e["message"].lower()
                for word in ["failed to solve", "solve error"]
            )
        ]

        print(f"\nSuccessful solutions: {len(solved)}")
        print(f"Failed solutions: {len(failed_solve)}")

        # Time patterns
        if len(self.captcha_events) > 1:
            captcha_times = [e["timestamp"] for e in self.captcha_events]
            intervals = [
                (captcha_times[i] - captcha_times[i - 1]).total_seconds()
                for i in range(1, len(captcha_times))
            ]

            if intervals:
                avg_interval = sum(intervals) / len(intervals)
                print(f"\nAverage time between CAPTCHAs: {avg_interval/60:.1f} minutes")

                # Detect increasing frequency
                recent_interval = intervals[-10:] if len(intervals) > 10 else intervals
                recent_avg = sum(recent_interval) / len(recent_interval)
                if recent_avg < avg_interval * 0.8:
                    print("⚠️  CAPTCHA frequency appears to be increasing!")

    def analyze_error_patterns(self):
        """Analyze error patterns that might indicate detection."""
        print("\n=== ERROR PATTERN ANALYSIS ===")

        if not self.error_events:
            print("No error events found")
            return

        # Error categorization
        error_types = Counter()
        for event in self.error_events:
            message = event["message"].lower()
            if "403" in message or "forbidden" in message:
                error_types["Forbidden"] += 1
            elif "401" in message or "unauthorized" in message:
                error_types["Unauthorized"] += 1
            elif "timeout" in message:
                error_types["Timeout"] += 1
            elif "connection" in message:
                error_types["Connection"] += 1
            elif "rate" in message and "limit" in message:
                error_types["Rate Limit"] += 1
            else:
                error_types["Other"] += 1

        print("Error types:")
        for error_type, count in error_types.most_common():
            print(f"  {error_type}: {count}")

        # Recent errors (last hour)
        one_hour_ago = datetime.now() - timedelta(hours=1)
        recent_errors = [e for e in self.error_events if e["timestamp"] > one_hour_ago]
        if recent_errors:
            print(f"\nRecent errors (last hour): {len(recent_errors)}")
            for error in recent_errors[-3:]:  # Show last 3
                print(
                    f"  {error['timestamp'].strftime('%H:%M:%S')} - {error['message']}"
                )

    def generate_report(self):
        """Generate a comprehensive analysis report."""
        print("\n" + "=" * 50)
        print("GENGO ANALYSIS REPORT")
        print("=" * 50)

        # Summary statistics
        if self.log_entries:
            start_time = self.log_entries[0]["timestamp"]
            end_time = self.log_entries[-1]["timestamp"]
            duration = end_time - start_time

            print(f"\nAnalysis Period: {start_time.date()} to {end_time.date()}")
            print(f"Duration: {duration.days} days")

            if duration.total_seconds() > 0:
                jobs_per_hour = len(self.job_events) / (duration.total_seconds() / 3600)
                acceptances_per_hour = len(self.acceptance_events) / (
                    duration.total_seconds() / 3600
                )
                captchas_per_hour = len(self.captcha_events) / (
                    duration.total_seconds() / 3600
                )

                print(f"\nHourly averages:")
                print(f"  Jobs detected: {jobs_per_hour:.2f}/hour")
                print(f"  Jobs accepted: {acceptances_per_hour:.2f}/hour")
                print(f"  CAPTCHAs: {captchas_per_hour:.2f}/hour")

        # Risk indicators
        print("\nRISK INDICATORS:")
        risk_level = 0

        # High acceptance rate
        if len(self.acceptance_events) > len(self.job_events) * 0.8:
            print("⚠️  High acceptance rate (>80%)")
            risk_level += 1

        # Many CAPTCHAs
        if len(self.captcha_events) > 10:
            print("⚠️  High number of CAPTCHA challenges")
            risk_level += 1

        # Rate limiting
        rate_limit_events = [
            e for e in self.error_events if "rate limit" in e["message"].lower()
        ]
        if rate_limit_events:
            print("⚠️  Rate limiting detected")
            risk_level += 2

        # Authorization errors
        auth_errors = [
            e
            for e in self.error_events
            if "403" in e["message"] or "401" in e["message"]
        ]
        if auth_errors:
            print("⚠️  Authorization/Forbidden errors detected")
            risk_level += 3

        # Overall risk assessment
        print(
            f"\nRISK LEVEL: {'LOW' if risk_level == 0 else 'MEDIUM' if risk_level <= 3 else 'HIGH'}"
        )

        # Recommendations
        print("\nRECOMMENDATIONS:")
        if risk_level >= 3:
            print("1. STOP auto-acceptance immediately")
            print("2. Wait 24-48 hours before any activity")
            print("3. Reduce acceptance rate to <1 job/hour")
        elif risk_level >= 1:
            print("1. Reduce acceptance frequency")
            print("2. Add longer delays between actions")
            print("3. Monitor for increased CAPTCHAs")
        else:
            print("1. Current patterns appear safe")
            print("2. Continue monitoring")
            print("3. Consider reducing rate for extra safety")

        # Save detailed data
        self._save_analysis_data()

    def _save_analysis_data(self):
        """Save analysis data for further review."""
        output_dir = Path("analysis")
        output_dir.mkdir(exist_ok=True)

        # Save events
        events_data = {
            "job_events": self.job_events,
            "acceptance_events": self.acceptance_events,
            "captcha_events": self.captcha_events,
            "error_events": self.error_events,
        }

        with open(output_dir / "log_analysis_events.json", "w") as f:
            # Convert datetime objects to strings
            serializable_events = {}
            for key, events in events_data.items():
                serializable_events[key] = [
                    {**event, "timestamp": event["timestamp"].isoformat()}
                    for event in events
                ]
            json.dump(serializable_events, f, indent=2)

        print(f"\nDetailed analysis saved to {output_dir}/")


def main():
    """Run log analysis."""
    analyzer = LogAnalyzer()
    analyzer.parse_logs()
    analyzer.analyze_job_patterns()
    analyzer.analyze_acceptance_patterns()
    analyzer.analyze_captcha_patterns()
    analyzer.analyze_error_patterns()
    analyzer.generate_report()


if __name__ == "__main__":
    main()
