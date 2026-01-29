"""Historical statistics management for GengoWatcher."""

import json
import pathlib
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from collections import defaultdict
import datetime


@dataclass
class SessionStats:
    """Statistics for the current session."""

    start_time: float = field(default_factory=time.time)
    jobs_found: int = 0
    jobs_accepted: int = 0
    total_value: float = 0.0

    @property
    def duration_seconds(self) -> float:
        return time.time() - self.start_time

    @property
    def rate_per_hour(self) -> float:
        hours = self.duration_seconds / 3600
        return self.jobs_found / max(hours, 0.01)


@dataclass
class AllTimeStats:
    """Aggregate statistics across all sessions."""

    total_jobs: int = 0
    total_jobs_accepted: int = 0
    total_value: float = 0.0
    total_sessions: int = 0
    best_day_value: float = 0.0
    best_day_date: str = ""

    @property
    def avg_job_value(self) -> float:
        return self.total_value / max(self.total_jobs_accepted, 1)


@dataclass
class SourceStats:
    """Statistics broken down by job source."""

    websocket: int = 0
    email: int = 0
    website: int = 0
    rss: int = 0

    @property
    def total(self) -> int:
        return self.websocket + self.email + self.website + self.rss

    def percentages(self) -> Dict[str, float]:
        total = max(self.total, 1)
        return {
            "websocket": self.websocket / total * 100,
            "email": self.email / total * 100,
            "website": self.website / total * 100,
            "rss": self.rss / total * 100,
        }


class StatsManager:
    """Manages historical statistics persistence and calculation."""

    STATS_FILE = "stats.json"

    def __init__(self, stats_path: Optional[pathlib.Path] = None):
        self._lock = threading.RLock()
        self._stats_path = stats_path or pathlib.Path(self.STATS_FILE)

        self.session = SessionStats()
        self.all_time = AllTimeStats()
        self.by_source = SourceStats()
        self.by_language: Dict[str, int] = defaultdict(int)
        self.hourly_counts: Dict[int, int] = defaultdict(int)  # hour -> count
        self.daily_counts: Dict[str, int] = defaultdict(int)  # day_name -> count
        self.daily_earnings: Dict[str, float] = defaultdict(float)  # date -> earnings

        self._load()

    def _load(self) -> None:
        """Load stats from file."""
        try:
            if self._stats_path.exists():
                with open(self._stats_path, "r") as f:
                    data = json.load(f)
                    self.all_time = AllTimeStats(**data.get("all_time", {}))
                    src = data.get("by_source", {})
                    self.by_source = SourceStats(**src)
                    self.by_language = defaultdict(int, data.get("by_language", {}))
                    self.hourly_counts = defaultdict(
                        int,
                        {int(k): v for k, v in data.get("hourly_counts", {}).items()},
                    )
                    self.daily_counts = defaultdict(int, data.get("daily_counts", {}))
                    self.daily_earnings = defaultdict(
                        float, data.get("daily_earnings", {})
                    )
        except (json.JSONDecodeError, IOError, TypeError):
            pass  # Start fresh

    def save(self) -> None:
        """Persist stats to file."""
        with self._lock:
            data = {
                "all_time": asdict(self.all_time),
                "by_source": asdict(self.by_source),
                "by_language": dict(self.by_language),
                "hourly_counts": dict(self.hourly_counts),
                "daily_counts": dict(self.daily_counts),
                "daily_earnings": dict(self.daily_earnings),
            }
            if not self._stats_path.parent.exists():
                self._stats_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._stats_path, "w") as f:
                json.dump(data, f, indent=2)

    def record_job(
        self, reward: float, source: str, lang_pair: str, accepted: bool = False
    ) -> None:
        """Record a job detection."""
        with self._lock:
            now = datetime.datetime.now()

            # Session stats
            self.session.jobs_found += 1
            self.session.total_value += reward
            if accepted:
                self.session.jobs_accepted += 1

            # All-time stats
            self.all_time.total_jobs += 1
            if accepted:
                self.all_time.total_jobs_accepted += 1
                self.all_time.total_value += reward

            # Source stats
            source_lower = source.lower()
            if "websocket" in source_lower or "ws" in source_lower:
                self.by_source.websocket += 1
            elif "email" in source_lower:
                self.by_source.email += 1
            elif "web" in source_lower:
                self.by_source.website += 1
            elif "rss" in source_lower:
                self.by_source.rss += 1

            # Language stats
            self.by_language[lang_pair] += 1

            # Time-based stats
            self.hourly_counts[now.hour] += 1
            self.daily_counts[now.strftime("%A")] += 1

            if accepted:
                date_str = now.strftime("%Y-%m-%d")
                self.daily_earnings[date_str] += reward
                # Check for best day
                if self.daily_earnings[date_str] > self.all_time.best_day_value:
                    self.all_time.best_day_value = self.daily_earnings[date_str]
                    self.all_time.best_day_date = date_str

    def end_session(self) -> None:
        """Call when session ends to update totals."""
        with self._lock:
            self.all_time.total_sessions += 1
            self.save()

    def get_peak_hour(self) -> tuple[int, float]:
        """Return (hour, rate) for peak activity."""
        if not self.hourly_counts:
            return (12, 0.0)
        peak_hour = max(self.hourly_counts, key=lambda k: self.hourly_counts[k])
        return (peak_hour, float(self.hourly_counts[peak_hour]))

    def get_slowest_hour(self) -> tuple[int, float]:
        """Return (hour, rate) for slowest activity."""
        if not self.hourly_counts:
            return (4, 0.0)
        slow_hour = min(self.hourly_counts, key=lambda k: self.hourly_counts[k])
        return (slow_hour, float(self.hourly_counts[slow_hour]))

    def get_recent_earnings(self, days: int = 7) -> Dict[str, float]:
        """Get earnings for the last N days."""
        result = {}
        today = datetime.date.today()
        for i in range(days):
            date = today - datetime.timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            result[date.strftime("%a")] = self.daily_earnings.get(date_str, 0.0)
        return dict(reversed(list(result.items())))
