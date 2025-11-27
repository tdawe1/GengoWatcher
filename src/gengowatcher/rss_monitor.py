"""
RSS Monitor for GengoWatcher.
Handles fetching and parsing of RSS feeds to detect new jobs.
"""

import logging
import re
import datetime
import feedparser
from typing import Optional, List, Dict, Any

from .config import AppConfig
from .state import AppState


class RssMonitor:
    """Monitor for checking Gengo RSS feeds."""

    def __init__(self, config: AppConfig, state: AppState, logger: logging.Logger):
        self.config = config
        self.state = state
        self.logger = logger
        self.logger.info("RssMonitor initialized")

    def fetch_rss(self) -> Optional[feedparser.FeedParserDict]:
        """Fetch and parse the RSS feed from Gengo.

        Retrieves the RSS feed using feedparser with optional custom user agent.
        Handles various error conditions and logs appropriate messages.

        Returns:
            feedparser.FeedParserDict: Parsed RSS feed object, or None if fetch failed.
        """
        headers = {}
        if self.config.get("Watcher", "use_custom_user_agent"):
            email = self.config.get("Network", "user_agent_email")
            headers["User-Agent"] = f"GengoWatcher/2.1.5 ({email})"

        feed_url = self.config.get("Watcher", "feed_url")
        self.logger.debug(f"Fetching RSS feed: {feed_url} with headers: {headers}")

        try:
            feed = feedparser.parse(feed_url, request_headers=headers)
            if feed.bozo:
                self.logger.error(f"Feed Error: {feed.bozo_exception}")
                return None
            self.logger.debug(
                f"RSS feed fetched successfully. Entries: {len(feed.entries)}"
            )
            return feed
        except Exception as e:
            self.logger.error(f"RSS Error: {e}")
            return None

    def extract_reward(self, entry: Dict[str, Any]) -> float:
        """Extract the reward amount from an RSS feed entry.

        Parses the title and summary of an RSS entry to find reward information
        using a regular expression pattern.

        Args:
            entry: Dictionary containing RSS entry data with 'title' and 'summary' keys.

        Returns:
            float: The extracted reward amount, or 0.0 if not found or invalid.
        """
        text = entry.get("title", "") + " | " + entry.get("summary", "")
        # self.logger.debug(f"Extracting reward from entry: {text}")
        match = re.search(r"Reward:\s*(?:US\$|\$)?\s*(\d+\.?\d*)", text, re.IGNORECASE)
        try:
            return float(match.group(1)) if match else 0.0
        except (ValueError, IndexError):
            return 0.0

    def process_feed_entries(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process RSS feed entries to identify new jobs.

        Filters entries to find only new ones since the last check.
        Updates the last seen RSS link to avoid duplicate processing.

        Args:
            entries: List of RSS entry dictionaries from the feed parser.

        Returns:
            List[Dict[str, Any]]: A list of processed job dictionaries (id, title, reward, url, source).
        """
        self.logger.debug(f"Processing {len(entries) if entries else 0} RSS entries.")
        if not entries:
            return []

        new_entries = []
        for entry in entries:
            link = entry.get("link")
            if not link:
                continue
            if link == self.state.last_seen_rss_link:
                break
            new_entries.append(entry)

        self.logger.debug(f"Found {len(new_entries)} new RSS entries.")
        if not new_entries:
            return []

        # Update state with the latest link
        latest_link = new_entries[0].get("link")
        self.state.last_seen_rss_link = latest_link
        self.state.last_seen_link = latest_link

        processed_jobs = []

        # Process from oldest to newest
        for entry in reversed(new_entries):
            title = entry.get("title", "No Title")
            url = entry.get("link")
            self.logger.debug(f"Processing new RSS entry: {title} {url}")
            try:
                match = re.search(r"/jobs/(?:details/)?(\d+)", url)
                if not match:
                    self.logger.warning(f"Could not parse job ID from RSS link: {url}")
                    continue
                job_id = int(match.group(1))
                reward = self.extract_reward(entry)

                processed_jobs.append({
                    "job_id": job_id,
                    "title": title,
                    "reward": reward,
                    "url": url,
                    "source": "RSS",
                    "entry": entry # Keep original entry for logging purposes if needed
                })

            except (ValueError, IndexError) as e:
                self.logger.warning(f"Error processing RSS entry {url}: {e}")

        return processed_jobs
