#!/usr/bin/env python3
"""Import historical job data from CSV files and log files into stats.json."""

import csv
import glob
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# CSV files to import
CSV_FILES = [
    Path("archives/logs-2026-01-22/all_entries.csv"),  # 34k rows, has header
    Path("logs/all_entries.csv"),  # 564 rows, no header
]

# Log files to import (contain job data not in CSV)
LOG_PATTERNS = [
    "archives/logs-2026-01-22/gengowatcher.log",
    "archives/logs-2026-01-22/gengowatcher.log.*",
    "logs/gengowatcher.log",
    "logs/gengowatcher.log.*",
]

STATS_FILE = Path("stats.json")

# Pre-compiled regex patterns for performance
SUPPORTED_LANGUAGES = "Japanese|English|Chinese|Korean|Spanish|French|German|Portuguese|Italian|Dutch|Russian"
LANG_PAIR_RE = re.compile(rf"({SUPPORTED_LANGUAGES})/({SUPPORTED_LANGUAGES})")
LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*"
    r"Processing new job: (?P<job_id>\d+), (?P<title>.+?), "
    r"(?P<reward>\d+\.?\d*), https://gengo\.com"
)


def parse_lang_pair(title: str) -> str:
    """Extract language pair from title like 'Japanese/English'."""
    match = LANG_PAIR_RE.search(title)
    if match:
        return f"{match.group(1)[:2]}→{match.group(2)[:2]}"
    return "Unknown"


def parse_csv_row(row: list) -> dict | None:
    """Parse a CSV row into structured data."""
    try:
        # Format: timestamp,title,reward,link,summary
        if len(row) < 4:
            return None

        timestamp_str = row[0].strip()
        title = row[1].strip()
        reward_str = row[2].strip()
        link = row[3].strip()

        # Parse timestamp
        try:
            dt = datetime.fromisoformat(timestamp_str)
        except ValueError:
            return None

        # Parse reward
        try:
            reward = float(reward_str)
        except ValueError:
            return None

        # Extract job ID from link for deduplication
        job_id = link.split("/")[-1].split("?")[0] if link else None

        return {
            "timestamp": dt,
            "title": title,
            "reward": reward,
            "link": link,
            "job_id": job_id,
            "lang_pair": parse_lang_pair(title),
        }
    except Exception:
        return None


def import_csv(csv_path: Path, has_header: bool = False) -> list[dict]:
    """Import jobs from a CSV file."""
    jobs = []

    if not csv_path.exists():
        print(f"  Skipping {csv_path} (not found)")
        return jobs

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)

        if has_header:
            next(reader, None)  # Skip header

        for row in reader:
            job = parse_csv_row(row)
            if job:
                jobs.append(job)

    return jobs


def parse_log_line(line: str) -> dict | None:
    """Parse a log line for job data.

    Format: 2025-09-14 10:30:46,951 - DEBUG - Processing new job: 33879119, (Standard) | ... | Reward: US$12.66 | Japanese/English, 12.66, https://gengo.com/t/jobs/details/33879119?referral=rss, RSS
    """
    if "Processing new job:" not in line:
        return None

    try:
        match = LOG_LINE_RE.match(line)
        if not match:
            return None

        dt = datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S")
        job_id = match.group("job_id")
        title = match.group("title")
        reward = float(match.group("reward"))

        return {
            "timestamp": dt,
            "title": title,
            "reward": reward,
            "link": f"https://gengo.com/t/jobs/details/{job_id}",
            "job_id": job_id,
            "lang_pair": parse_lang_pair(title),
        }
    except Exception:
        return None


def import_logs(log_pattern: str) -> list[dict]:
    """Import jobs from log files matching pattern."""
    jobs = []

    for log_path in sorted(glob.glob(log_pattern)):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    job = parse_log_line(line)
                    if job:
                        jobs.append(job)
        except Exception as e:
            print(f"  Error reading {log_path}: {e}")

    return jobs


def main():
    print("Importing historical data from CSV and log files...\n")

    all_jobs = []

    # Import archived CSV (has header)
    print(f"Reading {CSV_FILES[0]}...")
    jobs = import_csv(CSV_FILES[0], has_header=True)
    print(f"  Found {len(jobs)} valid rows")
    all_jobs.extend(jobs)

    # Import current CSV (no header)
    print(f"Reading {CSV_FILES[1]}...")
    jobs = import_csv(CSV_FILES[1], has_header=False)
    print(f"  Found {len(jobs)} valid rows")
    all_jobs.extend(jobs)

    # Import from log files
    for pattern in LOG_PATTERNS:
        print(f"Reading logs matching {pattern}...")
        jobs = import_logs(pattern)
        print(f"  Found {len(jobs)} jobs from logs")
        all_jobs.extend(jobs)

    print(f"\nTotal jobs from all sources: {len(all_jobs)}")

    # Deduplicate by job_id (same job logged multiple times from RSS polling)
    seen = set()
    unique_jobs = []
    for job in all_jobs:
        job_id = job.get("job_id")
        if job_id and job_id not in seen:
            seen.add(job_id)
            unique_jobs.append(job)
        elif not job_id:
            # No job_id, use link as fallback
            link = job.get("link", "")
            if link and link not in seen:
                seen.add(link)
                unique_jobs.append(job)

    print(f"After deduplication: {len(unique_jobs)} unique jobs")

    # Aggregate stats
    hourly_counts = defaultdict(int)
    daily_counts = defaultdict(int)
    daily_earnings = defaultdict(float)
    by_language = defaultdict(int)
    total_value = 0.0

    for job in unique_jobs:
        dt = job["timestamp"]
        reward = job["reward"]
        lang = job["lang_pair"]

        hourly_counts[dt.hour] += 1
        daily_counts[dt.strftime("%A")] += 1
        daily_earnings[dt.strftime("%Y-%m-%d")] += reward
        by_language[lang] += 1
        total_value += reward

    # Find best day
    best_day_date = ""
    best_day_value = 0.0
    for date_str, value in daily_earnings.items():
        if value > best_day_value:
            best_day_value = value
            best_day_date = date_str

    # Build stats structure
    stats = {
        "all_time": {
            "total_jobs": len(unique_jobs),
            "total_value": round(total_value, 2),
            "total_sessions": 0,  # Can't determine from CSV
            "best_day_value": round(best_day_value, 2),
            "best_day_date": best_day_date,
        },
        "by_source": {
            "websocket": 0,  # Can't determine from CSV
            "email": 0,
            "website": 0,
        },
        "by_language": dict(by_language),
        "hourly_counts": dict(hourly_counts),
        "daily_counts": dict(daily_counts),
        "daily_earnings": {k: round(v, 2) for k, v in daily_earnings.items()},
    }

    # Print summary
    print("\n--- Summary ---")
    print(f"Total jobs: {stats['all_time']['total_jobs']}")
    print(f"Total value: ${stats['all_time']['total_value']:.2f}")
    print(f"Best day: {best_day_date} (${best_day_value:.2f})")
    print("\nLanguage breakdown:")
    for lang, count in sorted(by_language.items(), key=lambda x: -x[1])[:5]:
        print(f"  {lang}: {count}")
    print("\nPeak hours:")
    peak_hours = sorted(hourly_counts.items(), key=lambda x: -x[1])[:3]
    for hour, count in peak_hours:
        print(f"  {hour:02d}:00 - {count} jobs")

    # Save to stats.json
    print(f"\nSaving to {STATS_FILE}...")
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)

    print("Done!")


if __name__ == "__main__":
    main()
