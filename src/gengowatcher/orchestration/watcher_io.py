"""I/O and shutdown helpers extracted from GengoWatcher.

Owns two distinct side-effect helpers that the orchestrator's main
loop calls into:

* fetch_rss(watcher)        -- HTTP fetch + parse of the Gengo RSS
                                feed, with a thread-pool executor
                                + bounded timeout to avoid blocking
                                the watcher loop.
* handle_exit(watcher)      -- SIGINT/SIGTERM-friendly shutdown
                                sequence: flip shutdown_event, close
                                the RSS executor, save state, stop
                                the job acceptance and cancellation
                                engines, and emit the
                                'shutdown' API event.

The watcher keeps thin delegator methods on the class so existing
call sites (runtime.py:264, web.py:1388, watcher_feed.py, the test
suite) keep resolving ``watcher.fetch_rss`` and ``watcher.handle_exit``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from typing import TYPE_CHECKING

import feedparser

from ..browser_detector import get_preferred_browser_user_agent

if TYPE_CHECKING:
    pass


def fetch_rss(watcher):
    """Fetch and parse the RSS feed from Gengo.

    Retrieves the RSS feed using feedparser with an optional browser-like user agent.
    Handles various error conditions and logs appropriate messages.

    Returns:
        feedparser.FeedParserDict: Parsed RSS feed object, or None if fetch failed.

    Raises:
        Exception: For network or parsing errors (logged internally).
    """
    headers = {}
    if watcher.config.get("Watcher", "use_custom_user_agent"):
        headers["User-Agent"] = get_preferred_browser_user_agent(
            watcher.config, watcher.logger
        )
    watcher.logger.debug(
        f"Fetching RSS feed: {watcher.config.get('Watcher', 'feed_url')} with headers: {headers}"
    )
    try:
        feed_url = watcher.config.get("Watcher", "feed_url")
        # Wrap feedparser in thread with timeout to prevent blocking
        if watcher._rss_executor is None:
            watcher._rss_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=1
            )
        if watcher._rss_future is not None:
            if not watcher._rss_future.done():
                elapsed = (
                    time.monotonic() - watcher._rss_future_started_at
                    if watcher._rss_future_started_at is not None
                    else 0.0
                )
                watcher.logger.warning(
                    f"Skipping RSS fetch: previous fetch still running ({elapsed:.1f}s elapsed)"
                )
                return None
            watcher._rss_future = None
            watcher._rss_future_started_at = None
        future = watcher._rss_executor.submit(
            feedparser.parse,
            feed_url,
            request_headers=headers,
        )
        watcher._rss_future = future
        watcher._rss_future_started_at = time.monotonic()
        try:
            feed = future.result(timeout=30)
        except concurrent.futures.TimeoutError:
            cancel_success = future.cancel()
            watcher.logger.warning("RSS feed fetch timed out after 30 seconds")
            watcher.logger.info(f"RSS fetch future cancelled: {cancel_success}")
            return None
        finally:
            if future.done():
                watcher._rss_future = None
                watcher._rss_future_started_at = None
        # Check HTTP status first (feedparser stores it in feed.status)
        http_status = getattr(feed, "status", None)
        if http_status == 429:
            watcher.logger.warning(
                "RSS rate limited (HTTP 429). Gengo limits requests to once per 60s. "
                "Consider increasing check_interval in config."
            )
            return None
        if http_status and http_status >= 400:
            watcher.logger.error(f"RSS HTTP Error: {http_status}")
            return None

        if feed.bozo:
            # Check if it's a parsing error due to HTML response (rate limit page)
            exc_str = str(feed.bozo_exception).lower()
            if "mismatched tag" in exc_str or "not well-formed" in exc_str:
                # Likely an HTML error page instead of RSS/XML
                watcher.logger.warning(
                    "RSS feed returned invalid XML (likely rate-limited or error page). "
                    "Will retry after backoff."
                )
            else:
                watcher.logger.error(f"Feed Parse Error: {feed.bozo_exception}")
            return None
        watcher.logger.debug(
            f"RSS feed fetched successfully. Entries: {len(feed.entries)}"
        )
        return feed
    except Exception as e:
        watcher.logger.error(f"RSS Error: {e}")
        return None


def handle_exit(watcher):
    """Handle application exit"""
    if getattr(watcher, "_shutdown_initiated", False):
        return

    watcher._shutdown_initiated = True
    watcher.logger.info("GengoWatcher shutting down...")
    watcher.shutdown_event.set()
    watcher.check_now_event.set()
    watcher._emit_api_event("shutdown", {"status": "shutdown"})

    def _run_coro_safely(coro, description):
        try:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(coro)
            finally:
                asyncio.set_event_loop(None)
                loop.close()
        except Exception as error:
            watcher.logger.exception(
                "Failed to %s during shutdown: %s", description, error
            )

    if getattr(watcher, "job_acceptance_engine", None) and hasattr(
        watcher.job_acceptance_engine, "close_session"
    ):
        _run_coro_safely(
            watcher.job_acceptance_engine.close_session(),
            "close job acceptance session",
        )

    if getattr(watcher, "cancellation_manager", None) and hasattr(
        watcher.cancellation_manager, "close_session"
    ):
        _run_coro_safely(
            watcher.cancellation_manager.close_session(),
            "close cancellation session",
        )

    if watcher._all_entries_log_file:
        try:
            watcher._all_entries_log_file.flush()
            watcher._all_entries_log_file.close()
        except Exception as error:
            watcher.logger.exception("Failed to close CSV log file: %s", error)
        finally:
            watcher._all_entries_log_file = None
            watcher._csv_writer = None
    if watcher._rss_executor is not None:
        try:
            watcher._rss_executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            watcher._rss_executor.shutdown(wait=False)
        watcher._rss_executor = None
    watcher._rss_future = None
    watcher._rss_future_started_at = None

    try:
        watcher.state.save_state()
    except Exception as error:
        watcher.logger.exception("Failed to save state during shutdown: %s", error)

    watcher.logger.info("GengoWatcher shutdown complete")


__all__ = ["fetch_rss", "handle_exit"]
