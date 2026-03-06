"""
Job Acceptance Engine for GengoWatcher
Handles automatic job acceptance based on configured criteria with rate limiting and error handling.
"""

import time
import random
import logging
import json
import aiohttp
import asyncio
import re
import threading
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from pathlib import Path

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:  # pragma: no cover - handled at runtime
    BeautifulSoup = None  # type: ignore

from .config import AppConfig


class RateLimiter:
    """Simple rate limiter using sliding window."""

    def __init__(self, max_requests: int, time_window: int):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum number of requests allowed in the time window
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self._requests: list[float] = []
        self._lock = threading.RLock()

    def _clean_old_requests(self) -> None:
        """Remove requests outside the time window."""
        now = time.time()
        self._requests = [t for t in self._requests if now - t < self.time_window]

    def can_proceed(self) -> bool:
        """Check if a new request can proceed without exceeding rate limit."""
        with self._lock:
            self._clean_old_requests()
            return len(self._requests) < self.max_requests

    def acquire(self) -> bool:
        """Try to acquire a slot. Returns True if successful, False if rate limited."""
        with self._lock:
            if self.can_proceed():
                self._requests.append(time.time())
                return True
            return False

    def wait_time(self) -> float:
        """Return seconds to wait before next request is allowed."""
        with self._lock:
            if self.max_requests <= 0:
                return 0.0
            self._clean_old_requests()
            if not self._requests or len(self._requests) < self.max_requests:
                return 0.0
            oldest = min(self._requests)
            return max(0.0, self.time_window - (time.time() - oldest))

    def record_request(self) -> None:
        """Record that a request was made."""
        with self._lock:
            self._requests.append(time.time())

    def get_current_rate(self) -> float:
        """Return current requests per time window."""
        with self._lock:
            self._clean_old_requests()
            return len(self._requests)


@dataclass
class AcceptResult:
    success: bool
    path: str
    http_status: Optional[int] = None
    redirect: bool = False
    reason: Optional[str] = None
    timings: Dict[str, Optional[float]] = field(default_factory=dict)


@dataclass
class AcceptForm:
    method: str
    url: str
    fields: Dict[str, Any] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)


class JobAcceptanceEngine:
    """Engine for automatically accepting Gengo jobs based on configured criteria."""

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
    ):
        """
        Initialise the JobAcceptanceEngine with configuration and logging.

        Initialises internal state including enabled flag, an hourly rate limiter (configured from the RateLimit.max_acceptances_per_hour setting, default 1800), HTTP session placeholder, retry policy and runtime counters.

        Parameters:
            config (AppConfig): Application configuration; used to read AutoAccept.enabled and RateLimit.max_acceptances_per_hour.
            logger (logging.Logger): Logger for informational and debug messages.
        """
        self.config = config
        self.logger = logger
        self._enabled = config.getboolean("AutoAccept", "enabled", fallback=False)

        if self.enabled:
            self.logger.info("Job Acceptance Engine initialized")

        # Rate limiter to prevent exceeding API limits
        # Read from config if available, otherwise default to 30/hour
        max_hourly = config.getint("RateLimit", "max_acceptances_per_hour", fallback=30)
        # RateLimiter uses a time_window (seconds) and max_requests.
        # We'll stick to a 60s window and scale the requests accordingly.
        # If user wants 15/hour, that's 0.25/min which RateLimiter (int) can't handle directly with 60s window.
        # So we set window to 3600 (1 hour) and max_requests to max_hourly.

        self.rate_limiter = RateLimiter(max_requests=max_hourly, time_window=3600)
        self.logger.debug(f"RateLimiter configured: {max_hourly} requests per 3600s")

        # Session for HTTP requests
        self.session: Optional[aiohttp.ClientSession] = None

        # Retry settings
        self.max_retries = 3
        self.retry_delay = 2  # seconds

        # Stats tracking
        self.accepted_jobs_count = 0
        self.failed_acceptances = 0
        self.rate_limited_count = 0

    async def initialize_session(self):
        """Initialize the HTTP session for API requests."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "User-Agent": "GengoWatcher/2.1.5",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            )
            self.logger.debug("HTTP session initialized for job acceptance")

    async def close_session(self):
        """Close the HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.logger.debug("HTTP session closed")

    @property
    def enabled(self):
        """Get the enabled state of auto-accept."""
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        """Set the enabled state of auto-accept."""
        self._enabled = value
        self.logger.info(f"Auto-accept {'enabled' if value else 'disabled'}")

    def is_job_eligible(self, job_data: Dict[str, Any]) -> bool:
        """
        Check if a job meets the auto-accept criteria.

        Args:
            job_data: Dictionary containing job information

        Returns:
            bool: True if job is eligible for auto-accept, False otherwise
        """
        if not self.enabled:
            return False

        # Check if job source is allowed
        allowed_sources = {
            s.strip() for s in self.config.get("AutoAccept", "job_sources").split(",")
        }
        if job_data.get("source", "").lower() not in allowed_sources:
            self.logger.debug(
                f"Job {job_data.get('id')} rejected: source {job_data.get('source')} not in {allowed_sources}"
            )
            return False

        # Check reward range
        reward = job_data.get("reward", 0.0)
        min_reward = self.config.getfloat("AutoAccept", "min_reward")
        max_reward = self.config.getfloat("AutoAccept", "max_reward")

        if not (min_reward <= reward <= max_reward):
            self.logger.debug(
                f"Job {job_data.get('id')} rejected: reward {reward} not in range [{min_reward}, {max_reward}]"
            )
            return False

        # Additional checks could be added here (e.g., language pairs, job type, etc.)

        return True

    async def accept_job(self, job_data: Dict[str, Any]) -> bool:
        """Attempt to accept a job with retry, rate limiting, and concurrent strategies."""
        if not self.enabled:
            return False

        job_id = str(job_data.get("id"))
        self.logger.info(f"Attempting to auto-accept job {job_id}")

        # Check rate limits
        if not self.rate_limiter.acquire():
            self.rate_limited_count += 1
            wait_time = self.rate_limiter.wait_time()
            self.logger.warning(
                f"Rate limit exceeded for job acceptance. Waiting {wait_time:.2f}s"
            )
            await asyncio.sleep(wait_time)
            if not self.rate_limiter.acquire():
                self.logger.error(f"Still rate limited after waiting for job {job_id}")
                return False

        # Apply configurable jitter before acceptance
        delay_min = self.config.getint("AutoAccept", "accept_delay_min")
        delay_max = self.config.getint("AutoAccept", "accept_delay_max")
        delay = max(0.0, random.uniform(delay_min, delay_max))
        if delay:
            self.logger.debug(f"Waiting {delay:.2f}s before accepting job {job_id}")
            await asyncio.sleep(delay)

        await self.initialize_session()

        attempts = self.max_retries + 1
        last_result: Optional[AcceptResult] = None

        for attempt in range(1, attempts + 1):
            try:
                result = await self._attempt_job_acceptance(job_data)
            except Exception as exc:  # pragma: no cover - defensive logging
                self.logger.exception(
                    "Unexpected error accepting job %s (attempt %s/%s): %s",
                    job_id,
                    attempt,
                    attempts,
                    exc,
                )
                result = AcceptResult(
                    success=False,
                    path="http",
                    reason=str(exc),
                    timings=self._build_timing_template(job_data),
                )

            last_result = result
            self._log_accept_attempt(job_data, result, attempt, attempts)

            if result.success:
                self.accepted_jobs_count += 1
                self.logger.info(
                    f"Successfully accepted job {job_id} via {result.path}"
                )

                if self.config.getboolean("AutoAccept", "log_acceptance"):
                    self._log_job_acceptance(job_data)

                if self.config.getboolean("AutoAccept", "notification_on_accept"):
                    self.logger.debug(
                        "Notification would be sent for accepted job %s", job_id
                    )

                return True

            self.logger.warning(
                "Failed to accept job %s via %s (attempt %s/%s). Reason: %s",
                job_id,
                result.path,
                attempt,
                attempts,
                result.reason or "unknown",
            )

            if result.reason == "captcha_required":
                self.logger.error(
                    "CAPTCHA required for job %s; stopping retries", job_id
                )
                break

            if attempt < attempts:
                backoff_time = self.retry_delay * (2 ** (attempt - 1)) + random.uniform(
                    0, 1
                )
                self.logger.info(
                    "Retrying job %s in %.2fs (attempt %s/%s)",
                    job_id,
                    backoff_time,
                    attempt + 1,
                    attempts,
                )
                await asyncio.sleep(backoff_time)

        self.failed_acceptances += 1
        self.logger.error(
            "Failed to accept job %s after %s attempts (last reason: %s)",
            job_id,
            attempts,
            (last_result.reason if last_result else "unknown"),
        )
        return False

    async def _attempt_job_acceptance(self, job_data: Dict[str, Any]) -> AcceptResult:
        """Execute HTTP-based job acceptance."""
        if not self.session:
            await self.initialize_session()

        template_timings = self._build_timing_template(job_data)
        start_monotonic = time.perf_counter()

        attempt_timeout = max(
            5.0,
            float(
                self.config.getfloat("AutoAccept", "attempt_timeout_sec", fallback=12.0)
            ),
        )

        try:
            result = await asyncio.wait_for(
                self._attempt_http_accept(
                    job_data, dict(template_timings), start_monotonic
                ),
                timeout=attempt_timeout,
            )
        except asyncio.TimeoutError:
            result = AcceptResult(
                success=False,
                path="http",
                reason="timeout",
                timings=dict(template_timings),
            )

        return result

    def _build_timing_template(
        self, job_data: Dict[str, Any]
    ) -> Dict[str, Optional[float]]:
        """Prepare a timing template anchored to the job discovery timestamp."""
        raw_ts = job_data.get("timestamp")
        try:
            seen_ts = float(raw_ts) if raw_ts is not None else time.time()
        except (TypeError, ValueError):
            seen_ts = time.time()
        seen_ms = max(0.0, (time.time() - seen_ts) * 1000.0)
        return {
            "seen_ms": seen_ms,
            "details_ms": None,
            "token_ms": None,
            "click_ms": None,
            "redirect_ms": None,
        }

    def _build_request_headers(self) -> Optional[Dict[str, str]]:
        """Construct authenticated headers for HTTP acceptance."""
        user_session = self.config.get("WebSocket", "user_session")
        user_id = self.config.get("WebSocket", "user_id")

        if not user_session or user_session == "REPLACE_WITH_YOUR_SESSION_TOKEN":
            self.logger.error("User session token not configured for job acceptance")
            return None
        if not user_id:
            self.logger.error("User ID not configured for job acceptance")
            return None

        return {
            "Cookie": f"my_gengo_session={user_session}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            "Origin": "https://gengo.com",
            "Referer": "https://gengo.com/t/jobs/status/available",
        }

    async def _attempt_http_accept(
        self,
        job_data: Dict[str, Any],
        timings: Dict[str, Optional[float]],
        start_monotonic: float,
    ) -> AcceptResult:
        job_id = str(job_data.get("id"))
        headers = self._build_request_headers()
        if headers is None:
            return AcceptResult(
                success=False,
                path="http",
                reason="missing_credentials",
                timings=timings,
            )

        details_url = (
            job_data.get("url") or f"https://gengo.com/t/jobs/details/{job_id}"
        )

        try:
            async with self.session.get(
                details_url, headers=headers, timeout=30
            ) as response:
                if response.status in {401, 403}:
                    return AcceptResult(
                        success=False,
                        path="http",
                        http_status=response.status,
                        reason="auth_failed",
                        timings=timings,
                    )
                if response.status != 200:
                    return AcceptResult(
                        success=False,
                        path="http",
                        http_status=response.status,
                        reason=f"details_status_{response.status}",
                        timings=timings,
                    )
                page_html = await response.text()
                timings["details_ms"] = (time.perf_counter() - start_monotonic) * 1000.0
        except asyncio.TimeoutError:
            return AcceptResult(
                success=False,
                path="http",
                reason="details_timeout",
                timings=timings,
            )
        except aiohttp.ClientError as error:
            return AcceptResult(
                success=False,
                path="http",
                reason=f"details_error:{error}",
                timings=timings,
            )

        accept_form = self._parse_accept_form(page_html, details_url)
        if accept_form is None:
            accept_form = AcceptForm(
                method="post",
                url=f"https://gengo.com/t/jobs/accept/{job_id}",
                fields={},
                headers={},
            )

        csrf_field, csrf_token = self._extract_csrf_token(page_html)
        if csrf_field and csrf_token and csrf_field not in accept_form.fields:
            accept_form.fields[csrf_field] = csrf_token

        submit_headers = dict(headers)
        submit_headers["Referer"] = details_url
        submit_headers.update(accept_form.headers)

        timings["click_ms"] = (time.perf_counter() - start_monotonic) * 1000.0

        if accept_form.method.lower() == "post":
            request_ctx = self.session.post(
                accept_form.url,
                headers=submit_headers,
                data=accept_form.fields or None,
                timeout=30,
            )
        else:
            request_ctx = self.session.get(
                accept_form.url,
                headers=submit_headers,
                params=accept_form.fields or None,
                timeout=30,
            )

        try:
            async with request_ctx as response:
                status = response.status
                timings["redirect_ms"] = (
                    time.perf_counter() - start_monotonic
                ) * 1000.0

                if status in {302, 303}:
                    return AcceptResult(
                        success=True,
                        path="http",
                        http_status=status,
                        redirect=True,
                        timings=timings,
                    )

                if status != 200:
                    return AcceptResult(
                        success=False,
                        path="http",
                        http_status=status,
                        reason=f"submit_status_{status}",
                        timings=timings,
                    )

                content = await response.text()
                lowered = content.lower()
                if "captcha" in lowered or "recaptcha" in lowered:
                    success = await self._handle_captcha_challenge(
                        job_id,
                        content,
                        headers,
                        timings=timings,
                        start_monotonic=start_monotonic,
                    )
                    if success:
                        timings["redirect_ms"] = (
                            time.perf_counter() - start_monotonic
                        ) * 1000.0
                        return AcceptResult(
                            success=True,
                            path="http",
                            http_status=200,
                            redirect=False,
                            timings=timings,
                        )
                    return AcceptResult(
                        success=False,
                        path="http",
                        http_status=200,
                        reason="captcha_required",
                        timings=timings,
                    )

                if "accepted" in lowered or "success" in lowered:
                    return AcceptResult(
                        success=True,
                        path="http",
                        http_status=200,
                        redirect=False,
                        timings=timings,
                    )

                return AcceptResult(
                    success=False,
                    path="http",
                    http_status=200,
                    reason="unexpected_response",
                    timings=timings,
                )
        except asyncio.TimeoutError:
            return AcceptResult(
                success=False,
                path="http",
                reason="submit_timeout",
                timings=timings,
            )
        except aiohttp.ClientError as error:
            return AcceptResult(
                success=False,
                path="http",
                reason=f"submit_error:{error}",
                timings=timings,
            )

    def _log_accept_attempt(
        self,
        job_data: Dict[str, Any],
        result: AcceptResult,
        attempt: int,
        attempts: int,
    ) -> None:
        """Append a JSONL record describing an acceptance attempt."""
        try:
            log_path = Path("logs/accept_attempts.log")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": time.time(),
                "job_id": str(job_data.get("id")),
                "source": job_data.get("source"),
                "attempt": attempt,
                "attempts": attempts,
                "path": result.path,
                "http_status": result.http_status,
                "redirect": result.redirect,
                "result": (
                    "accepted"
                    if result.success
                    else ("timeout" if result.reason == "timeout" else "failed")
                ),
                "reason": result.reason,
            }
            timings = result.timings or {}
            entry.update(
                {
                    "seen_ms": timings.get("seen_ms"),
                    "details_ms": timings.get("details_ms"),
                    "token_ms": timings.get("token_ms"),
                    "click_ms": timings.get("click_ms"),
                    "redirect_ms": timings.get("redirect_ms"),
                }
            )
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
        except Exception:  # pragma: no cover - logging must not break flow
            self.logger.debug("Failed to log accept attempt", exc_info=True)

    async def _handle_captcha_challenge(
        self,
        job_id: str,
        captcha_page_content: str,
        headers: Dict[str, str],
        timings: Optional[Dict[str, Optional[float]]] = None,
        start_monotonic: Optional[float] = None,
    ) -> bool:
        """Handle captcha challenge during job acceptance.

        Note: CAPTCHA solving has been removed. This method now logs an error and returns False.

        Args:
            job_id: The job ID being accepted
            captcha_page_content: HTML content of the captcha page
            headers: Authentication headers

        Returns:
            bool: Always False - CAPTCHA solving is not supported
        """
        self.logger.error(
            f"CAPTCHA challenge encountered for job {job_id} but CAPTCHA solving is not available"
        )
        return False

    def _extract_csrf_token(self, html: str) -> tuple[Optional[str], Optional[str]]:
        """Extract CSRF token field name and value from HTML if present"""
        try:
            if BeautifulSoup is None:
                return (None, None)
            soup = BeautifulSoup(html, "html.parser")
            # Common CSRF field names
            candidates = [
                "csrfmiddlewaretoken",
                "csrf_token",
                "authenticity_token",
                "csrf",
                "token",
            ]
            for inp in soup.find_all("input", {"type": "hidden"}):
                name = (inp.get("name") or "").lower()
                value = inp.get("value")
                if name and value and any(k in name for k in candidates):
                    return (inp.get("name"), value)
        except Exception:
            return (None, None)
        return (None, None)

    def _extract_meta_tokens(self, soup) -> Dict[str, Dict[str, str]]:
        """Extract CSRF-related tokens from meta tags for headers/fields."""
        result = {"fields": {}, "headers": {}}
        if BeautifulSoup is None:
            return result
        try:
            csrf_param_name = None
            csrf_token_val = None
            for meta in soup.find_all("meta"):
                name = (meta.get("name") or meta.get("property") or "").lower()
                content = meta.get("content") or ""
                if not name or not content:
                    continue
                if name in {"csrf-token", "csrf_token", "x-csrf-token", "x-csrf"}:
                    result["headers"].setdefault("X-CSRF-Token", content)
                    csrf_token_val = content
                elif name == "csrf-param":
                    csrf_param_name = content
                elif name in {"csrfmiddlewaretoken", "csrf"}:
                    result["fields"].setdefault(name, content)
            if csrf_param_name and csrf_token_val:
                result["fields"].setdefault(csrf_param_name, csrf_token_val)
        except Exception:
            return result
        return result

    def _parse_accept_form(self, html: str, base_url: str) -> Optional[AcceptForm]:
        """Parse accept form action/method/fields from job details HTML."""
        try:
            if BeautifulSoup is None:
                return None
            soup = BeautifulSoup(html, "html.parser")
            forms = soup.find_all("form")
            for form in forms:
                action = form.get("action") or ""
                method = (form.get("method") or "post").lower()
                has_accept_button = any(
                    "accept" in (btn.get_text() or "").strip().lower()
                    for btn in form.find_all(["button", "input"])
                )
                if "accept" not in action.lower() and not has_accept_button:
                    continue
                fields: Dict[str, Any] = {}
                for element in form.find_all(["input", "textarea"]):
                    name = element.get("name")
                    if not name:
                        continue
                    lname = name.lower()
                    if lname in {"g-recaptcha-response", "h-captcha-response"}:
                        continue
                    value = element.get("value")
                    if value is not None:
                        fields[name] = value
                    elif element.name == "textarea" and element.string:
                        fields[name] = element.string.strip()
                meta_tokens = self._extract_meta_tokens(soup)
                headers = dict(meta_tokens["headers"])
                for field_name, field_value in meta_tokens["fields"].items():
                    fields.setdefault(field_name, field_value)
                action_url = urljoin(base_url, action) if action else base_url
                return AcceptForm(
                    method=method, url=action_url, fields=fields, headers=headers
                )
        except Exception:
            return None
        return None

    def _log_job_acceptance(self, job_data: Dict[str, Any]):
        """
        Log job acceptance to a file.

        Args:
            job_data: Dictionary containing job information
        """
        try:
            log_path = Path("logs/accepted_jobs.log")
            log_path.parent.mkdir(parents=True, exist_ok=True)

            log_entry = {
                "timestamp": time.time(),
                "job_id": job_data.get("id"),
                "title": job_data.get("title"),
                "reward": job_data.get("reward"),
                "source": job_data.get("source"),
                "url": job_data.get("url"),
            }

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")

            self.logger.debug(f"Logged job acceptance for {job_data.get('id')}")
        except Exception as e:
            self.logger.exception(f"Failed to log job acceptance: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about job acceptance.

        Returns:
            Dict containing acceptance statistics
        """
        return {
            "accepted_jobs": self.accepted_jobs_count,
            "failed_acceptances": self.failed_acceptances,
            "rate_limited": self.rate_limited_count,
            "current_rate": self.rate_limiter.get_current_rate(),
            "enabled": self.enabled,
        }
