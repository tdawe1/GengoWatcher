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
import threading
import re
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urljoin
from pathlib import Path

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:  # pragma: no cover - handled at runtime
    BeautifulSoup = None  # type: ignore

from .rate_limiter import RateLimiter
from .config import AppConfig
from .captcha_manager import CaptchaSolverManager


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
        captcha_solver: Optional[CaptchaSolverManager] = None,
        browser_engine=None,
    ):
        """
        Initialize the JobAcceptanceEngine.

        Args:
            config (AppConfig): The application configuration object.
            logger (logging.Logger): Logger instance for logging messages.
            captcha_solver (Optional[CaptchaSolverManager]): Optional captcha solver manager.
            browser_engine: Optional browser automation engine for fallback submissions.
        """
        self.config = config
        self.logger = logger
        self.captcha_solver = captcha_solver
        self.browser_automation_engine = browser_engine
        self._enabled = config.getboolean("AutoAccept", "enabled", fallback=False)
        
        if self.enabled:
            self.logger.info("Job Acceptance Engine initialized")
            
        # Rate limiter to prevent exceeding API limits
        self.rate_limiter = RateLimiter(
            max_requests=30,  # Max 30 job acceptances per minute
            time_window=60    # 1 minute window
        )
        
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
                timeout=aiohttp.ClientTimeout(total=30)
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
        allowed_sources = {s.strip() for s in self.config.get("AutoAccept", "job_sources").split(",")}
        if job_data.get("source", "").lower() not in allowed_sources:
            self.logger.debug(f"Job {job_data.get('id')} rejected: source {job_data.get('source')} not in {allowed_sources}")
            return False

        # Check reward range
        reward = job_data.get("reward", 0.0)
        min_reward = self.config.getfloat("AutoAccept", "min_reward")
        max_reward = self.config.getfloat("AutoAccept", "max_reward")
        
        if not (min_reward <= reward <= max_reward):
            self.logger.debug(f"Job {job_data.get('id')} rejected: reward {reward} not in range [{min_reward}, {max_reward}]")
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
                self.logger.info(f"Successfully accepted job {job_id} via {result.path}")

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

            if attempt < attempts:
                backoff_time = self.retry_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
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
        """Execute HTTP and Selenium job acceptance in a race and return the first success."""
        if not self.session:
            await self.initialize_session()

        template_timings = self._build_timing_template(job_data)
        start_monotonic = time.perf_counter()

        http_task = asyncio.create_task(
            self._attempt_http_accept(job_data, dict(template_timings), start_monotonic)
        )
        tasks = [http_task]

        cancel_event: Optional[threading.Event] = None
        selenium_task: Optional[asyncio.Task[AcceptResult]] = None
        if self.browser_automation_engine and self.config.getboolean(
            "AutoAccept", "concurrent_submission", fallback=True
        ):
            cancel_event = threading.Event()
            selenium_task = asyncio.create_task(
                self._attempt_selenium_accept(
                    job_data,
                    dict(template_timings),
                    start_monotonic,
                    cancel_event,
                )
            )
            tasks.append(selenium_task)

        attempt_timeout = max(
            5.0,
            float(
                self.config.getfloat(
                    "AutoAccept", "attempt_timeout_sec", fallback=12.0
                )
            ),
        )

        result = await self._wait_for_winner(tasks, cancel_event, attempt_timeout, template_timings)

        # Ensure all tasks are settled to avoid warnings
        await asyncio.gather(*tasks, return_exceptions=True)

        return result

    def _build_timing_template(self, job_data: Dict[str, Any]) -> Dict[str, Optional[float]]:
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

        details_url = job_data.get("url") or f"https://gengo.com/t/jobs/details/{job_id}"

        try:
            async with self.session.get(details_url, headers=headers, timeout=30) as response:
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

        try:
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

        async with request_ctx as response:
            status = response.status
            timings["redirect_ms"] = (time.perf_counter() - start_monotonic) * 1000.0

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
                    timings["redirect_ms"] = (time.perf_counter() - start_monotonic) * 1000.0
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

    async def _attempt_selenium_accept(
        self,
        job_data: Dict[str, Any],
        timings: Dict[str, Optional[float]],
        start_monotonic: float,
        cancel_event: threading.Event,
    ) -> AcceptResult:
        if not self.browser_automation_engine:
            return AcceptResult(
                success=False,
                path="selenium",
                reason="selenium_disabled",
                timings=timings,
            )

        loop = asyncio.get_running_loop()
        probe_ms = self.config.getint("AutoAccept", "accept_click_probe_ms", fallback=75)
        per_attempt_timeout = max(
            3.0,
            float(
                self.config.getfloat(
                    "AutoAccept", "selenium_attempt_timeout_sec", fallback=8.0
                )
            ),
        )

        result = await loop.run_in_executor(
            None,
            self.browser_automation_engine.attempt_accept_via_browser,
            job_data,
            probe_ms,
            per_attempt_timeout,
            cancel_event,
            timings,
            start_monotonic,
        )

        if isinstance(result, AcceptResult):
            return result

        # Backward compatibility in case engine returns dict
        success = bool(result.get("success"))
        reason = result.get("reason")
        redirect = bool(result.get("redirect"))
        http_status = result.get("http_status")
        timing_updates = result.get("timings") or {}
        timings.update({k: v for k, v in timing_updates.items() if v is not None})

        return AcceptResult(
            success=success,
            path="selenium",
            reason=reason,
            redirect=redirect,
            http_status=http_status,
            timings=timings,
        )

    async def _wait_for_winner(
        self,
        tasks: list[asyncio.Task[AcceptResult]],
        cancel_event: Optional[threading.Event],
        timeout: float,
        template_timings: Dict[str, Optional[float]],
    ) -> AcceptResult:
        deadline = time.perf_counter() + timeout
        pending = set(tasks)
        winner: Optional[AcceptResult] = None
        last_result: Optional[AcceptResult] = None

        while pending and time.perf_counter() < deadline:
            remaining = max(0.0, deadline - time.perf_counter())
            done, pending = await asyncio.wait(
                pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                break
            for task in done:
                try:
                    result = task.result()
                except asyncio.CancelledError:
                    continue
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.debug("Acceptance task raised", exc_info=exc)
                    result = AcceptResult(
                        success=False,
                        path="internal",
                        reason=str(exc),
                        timings=dict(template_timings),
                    )
                last_result = result
                if result.success and not winner:
                    winner = result
                    for pending_task in pending:
                        pending_task.cancel()
                    if cancel_event:
                        cancel_event.set()
                    break
            if winner:
                break

        if not winner:
            if cancel_event:
                cancel_event.set()
            for task in pending:
                task.cancel()

        if winner:
            return winner

        return last_result or AcceptResult(
            success=False,
            path="race",
            reason="timeout",
            timings=dict(template_timings),
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
                "result": "accepted" if result.success else ("timeout" if result.reason == "timeout" else "failed"),
                "reason": result.reason,
            }
            timings = result.timings or {}
            entry.update({
                "seen_ms": timings.get("seen_ms"),
                "details_ms": timings.get("details_ms"),
                "token_ms": timings.get("token_ms"),
                "click_ms": timings.get("click_ms"),
                "redirect_ms": timings.get("redirect_ms"),
            })
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
        
        Args:
            job_id: The job ID being accepted
            captcha_page_content: HTML content of the captcha page
            headers: Authentication headers
            
        Returns:
            bool: True if captcha was solved and job accepted, False otherwise
        """
        def mark_timing(key: str) -> None:
            if timings is None or start_monotonic is None:
                return
            if timings.get(key) is None:
                timings[key] = (time.perf_counter() - start_monotonic) * 1000.0

        try:
            # Check if captcha solver is configured
            if not self.captcha_solver or not self.captcha_solver.is_configured():
                self.logger.error("Captcha solver not configured - cannot solve captcha challenge")
                return False
                
            self.logger.info(f"Attempting to solve captcha for job {job_id}")
            
            # Extract captcha information from the page
            # We need to parse the HTML to find the specific captcha elements
            if BeautifulSoup is None:
                self.logger.error(
                    "beautifulsoup4 is required to parse CAPTCHA challenge pages. Install it to enable CAPTCHA handling."
                )
                return False

            soup = BeautifulSoup(captcha_page_content, 'html.parser')
            
            # Check for reCAPTCHA v2
            recaptcha_div = soup.find('div', class_='g-recaptcha')
            if recaptcha_div:
                site_key = recaptcha_div.get('data-sitekey')
                if site_key:
                    page_url = f"https://gengo.com/t/jobs/accept/{job_id}"
                    # Preload browser concurrently while solving
                    if self.browser_automation_engine:
                        asyncio.get_event_loop().run_in_executor(
                            None, self.browser_automation_engine.preload_page, page_url
                        )
                    
                    # Solve the reCAPTCHA using the configured solver
                    self.logger.debug(f"Found reCAPTCHA v2 with site key: {site_key}")
                    try:
                        solution = await asyncio.get_event_loop().run_in_executor(
                            None, 
                            self.captcha_solver.solve_recaptcha_v2, 
                            site_key, 
                            page_url
                        )
                        
                        if not solution:
                            self.logger.error(f"Failed to solve reCAPTCHA for job {job_id}")
                            return False
                            
                        self.logger.info(f"Successfully solved reCAPTCHA for job {job_id}")
                        mark_timing("token_ms")
                        
                        # Submit the solved captcha along with the job acceptance request
                        captcha_data = {
                            "g-recaptcha-response": solution.solution,
                            "job_id": job_id
                        }
                        
                        # Submit the captcha solution
                        # Include CSRF if available
                        csrf_field, csrf_token = self._extract_csrf_token(captcha_page_content)
                        if csrf_field and csrf_token:
                            captcha_data[csrf_field] = csrf_token
                        async with self.session.post(
                            f"https://gengo.com/t/jobs/accept/{job_id}",
                            headers=headers,
                            data=captcha_data,
                            timeout=30
                        ) as response:
                            if response.status == 200:
                                content = await response.text()
                                if "accepted" in content.lower() or "success" in content.lower():
                                    self.logger.info(f"Successfully accepted job {job_id} after solving reCAPTCHA")
                                    mark_timing("redirect_ms")
                                    return True
                                else:
                                    self.logger.warning(f"Job {job_id} acceptance may have failed after reCAPTCHA - unexpected response")
                                    # Try browser fallback submission if enabled
                                    if self.config.getboolean("Captcha", "enable_browser_automation_fallback", True) and self.browser_automation_engine:
                                        try:
                                            ok = self.browser_automation_engine.submit_recaptcha_v2_with_token(
                                                page_url,
                                                captcha_data.get("g-recaptcha-response", "")
                                            )
                                            if ok:
                                                self.logger.info(f"Browser fallback submission appears successful for job {job_id}")
                                                mark_timing("redirect_ms")
                                                return True
                                        except Exception as be:
                                            self.logger.warning(f"Browser fallback failed: {be}")
                                    return False
                            else:
                                self.logger.error(f"Failed to accept job {job_id} after reCAPTCHA solving, status: {response.status}")
                                # Try browser fallback submission if enabled
                                if self.config.getboolean("Captcha", "enable_browser_automation_fallback", True) and self.browser_automation_engine:
                                    try:
                                        ok = self.browser_automation_engine.submit_recaptcha_v2_with_token(
                                            page_url,
                                            captcha_data.get("g-recaptcha-response", "")
                                        )
                                        if ok:
                                            self.logger.info(f"Browser fallback submission appears successful for job {job_id}")
                                            mark_timing("redirect_ms")
                                            return True
                                    except Exception as be:
                                        self.logger.warning(f"Browser fallback failed: {be}")
                                return False
                    except Exception as e:
                        self.logger.error(f"Error solving reCAPTCHA for job {job_id}: {e}")
                        return False
            
            # Check for hCaptcha
            hcaptcha_div = soup.find('div', class_='h-captcha')
            if hcaptcha_div:
                site_key = hcaptcha_div.get('data-sitekey')
                if site_key:
                    page_url = f"https://gengo.com/t/jobs/accept/{job_id}"
                    # Preload browser concurrently while solving
                    if self.browser_automation_engine:
                        asyncio.get_event_loop().run_in_executor(
                            None, self.browser_automation_engine.preload_page, page_url
                        )
                    
                    # Solve the hCaptcha using the configured solver
                    self.logger.debug(f"Found hCaptcha with site key: {site_key}")
                    try:
                        solution = await asyncio.get_event_loop().run_in_executor(
                            None, 
                            self.captcha_solver.solve_hcaptcha, 
                            site_key, 
                            page_url
                        )
                        
                        if not solution:
                            self.logger.error(f"Failed to solve hCaptcha for job {job_id}")
                            return False
                            
                        self.logger.info(f"Successfully solved hCaptcha for job {job_id}")
                        mark_timing("token_ms")
                        
                        # Submit the solved captcha along with the job acceptance request
                        captcha_data = {
                            "h-captcha-response": solution.solution,
                            "job_id": job_id
                        }
                        
                        # Submit the captcha solution
                        async with self.session.post(
                            f"https://gengo.com/t/jobs/accept/{job_id}",
                            headers=headers,
                            data=captcha_data,
                            timeout=30
                        ) as response:
                            if response.status == 200:
                                content = await response.text()
                                if "accepted" in content.lower() or "success" in content.lower():
                                    self.logger.info(f"Successfully accepted job {job_id} after solving hCaptcha")
                                    return True
                                else:
                                    self.logger.warning(f"Job {job_id} acceptance may have failed after hCaptcha - unexpected response")
                                    # Try browser fallback submission if enabled
                                    if self.config.getboolean("Captcha", "enable_browser_automation_fallback", True) and self.browser_automation_engine:
                                        try:
                                            ok = self.browser_automation_engine.submit_hcaptcha_with_token(
                                                page_url,
                                                captcha_data.get("h-captcha-response", "")
                                            )
                                            if ok:
                                                self.logger.info(f"Browser fallback submission appears successful for job {job_id}")
                                                mark_timing("redirect_ms")
                                                return True
                                        except Exception as be:
                                            self.logger.warning(f"Browser fallback failed: {be}")
                                    return False
                            else:
                                self.logger.error(f"Failed to accept job {job_id} after hCaptcha solving, status: {response.status}")
                                # Try browser fallback submission if enabled
                                if self.config.getboolean("Captcha", "enable_browser_automation_fallback", True) and self.browser_automation_engine:
                                    try:
                                        ok = self.browser_automation_engine.submit_hcaptcha_with_token(
                                            page_url,
                                            captcha_data.get("h-captcha-response", "")
                                        )
                                        if ok:
                                            self.logger.info(f"Browser fallback submission appears successful for job {job_id}")
                                            mark_timing("redirect_ms")
                                            return True
                                    except Exception as be:
                                        self.logger.warning(f"Browser fallback failed: {be}")
                                return False
                    except Exception as e:
                        self.logger.error(f"Error solving hCaptcha for job {job_id}: {e}")
                        return False
            
            # Check for reCAPTCHA v3 (invisible)
            recaptcha_v3_scripts = soup.find_all('script', src=lambda x: x and 'recaptcha' in x)
            if recaptcha_v3_scripts:
                # For reCAPTCHA v3, we need to extract the site key from the script
                page_url = f"https://gengo.com/t/jobs/accept/{job_id}"
                
                # Extract site key and action from the page
                site_key = self._extract_recaptcha_v3_site_key(soup)
                action = self._extract_recaptcha_v3_action(soup)
                
                if not site_key:
                    self.logger.warning(f"Failed to extract reCAPTCHA v3 site key for job {job_id}")
                    # Check if we should skip or use fallback behavior
                    if self.config.getboolean("Captcha", "skip_on_v3_extraction_failure", True):
                        self.logger.info(f"Skipping reCAPTCHA v3 solving for job {job_id} due to extraction failure")
                        return False
                    else:
                        # Try browser automation fallback if enabled
                        if self.config.getboolean("Captcha", "enable_browser_automation_fallback", False):
                            self.logger.info(f"Attempting browser automation fallback for reCAPTCHA v3 for job {job_id}")
                            # Note: This would require integration with the browser automation engine
                            # For now, we'll use the fallback site key
                            site_key = self.config.get("Captcha", "recaptcha_v3_fallback_site_key", "6Lc6BAAAAAAAAAChqR2QwNcAAAAA")
                            self.logger.warning(f"Using fallback reCAPTCHA v3 site key for job {job_id}")
                        else:
                            # Use fallback site key
                            site_key = self.config.get("Captcha", "recaptcha_v3_fallback_site_key", "6Lc6BAAAAAAAAAChqR2QwNcAAAAA")
                            self.logger.warning(f"Using fallback reCAPTCHA v3 site key for job {job_id}")

                if not action:
                    # Use default action if not found
                    action = self.config.get("Captcha", "recaptcha_v3_default_action", "job_acceptance")
                    self.logger.debug(f"Using default reCAPTCHA v3 action for job {job_id}: {action}")
                
                # Solve the reCAPTCHA v3 using the configured solver
                self.logger.debug(f"Attempting to solve reCAPTCHA v3 for job {job_id} with site key: {site_key}, action: {action}")
                try:
                    solution = await asyncio.get_event_loop().run_in_executor(
                        None, 
                        self.captcha_solver.solve_recaptcha_v3, 
                        site_key,
                        page_url,
                        action
                    )
                    
                    if not solution:
                        self.logger.error(f"Failed to solve reCAPTCHA v3 for job {job_id}")
                        return False
                        
                    self.logger.info(f"Successfully solved reCAPTCHA v3 for job {job_id}")
                    mark_timing("token_ms")
                    
                    # Submit the solved captcha along with the job acceptance request
                    captcha_data = {
                        "g-recaptcha-response": solution.solution,
                        "job_id": job_id
                    }
                    
                    # Submit the captcha solution
                    async with self.session.post(
                        f"https://gengo.com/t/jobs/accept/{job_id}",
                        headers=headers,
                        data=captcha_data,
                        timeout=30
                    ) as response:
                        if response.status == 200:
                            content = await response.text()
                            if "accepted" in content.lower() or "success" in content.lower():
                                self.logger.info(f"Successfully accepted job {job_id} after solving reCAPTCHA v3")
                                mark_timing("redirect_ms")
                                return True
                            else:
                                self.logger.warning(f"Job {job_id} acceptance may have failed after reCAPTCHA v3 - unexpected response")
                                return False
                        else:
                            self.logger.error(f"Failed to accept job {job_id} after reCAPTCHA v3 solving, status: {response.status}")
                            return False
                except Exception as e:
                    self.logger.error(f"Error solving reCAPTCHA v3 for job {job_id}: {e}")
                    return False
            
            # If we can't identify the captcha type, log the issue
            self.logger.error(f"Unable to identify captcha type for job {job_id}")
            return False
                    
        except Exception as e:
            self.logger.exception(f"Error handling captcha challenge for job {job_id}: {e}")
            return False
    
    def _extract_csrf_token(self, html: str) -> tuple[Optional[str], Optional[str]]:
        """Extract CSRF token field name and value from HTML if present"""
        try:
            if BeautifulSoup is None:
                return (None, None)
            soup = BeautifulSoup(html, 'html.parser')
            # Common CSRF field names
            candidates = [
                'csrfmiddlewaretoken', 'csrf_token', 'authenticity_token', 'csrf', 'token'
            ]
            for inp in soup.find_all('input', {"type": "hidden"}):
                name = (inp.get('name') or '').lower()
                value = inp.get('value')
                if name and value and any(k in name for k in candidates):
                    return (inp.get('name'), value)
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
            for meta in soup.find_all('meta'):
                name = (meta.get('name') or meta.get('property') or '').lower()
                content = meta.get('content') or ''
                if not name or not content:
                    continue
                if name in {'csrf-token', 'csrf_token', 'x-csrf-token', 'x-csrf'}:
                    result['headers'].setdefault('X-CSRF-Token', content)
                    csrf_token_val = content
                elif name == 'csrf-param':
                    csrf_param_name = content
                elif name in {'csrfmiddlewaretoken', 'csrf'}:
                    result['fields'].setdefault(name, content)
            if csrf_param_name and csrf_token_val:
                result['fields'].setdefault(csrf_param_name, csrf_token_val)
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
                return AcceptForm(method=method, url=action_url, fields=fields, headers=headers)
        except Exception:
            return None
        return None

    def _extract_recaptcha_v3_site_key(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract reCAPTCHA v3 site key from HTML content.
        
        Args:
            soup: BeautifulSoup object containing parsed HTML
            
        Returns:
            str: Site key if found, None otherwise
        """
        # Try to extract from data attributes
        recaptcha_elements = soup.find_all(attrs={"data-sitekey": True})
        for element in recaptcha_elements:
            site_key = element.get("data-sitekey")
            if site_key and len(site_key) > 10:  # Basic validation
                self.logger.debug(f"Found reCAPTCHA v3 site key in data attribute: {site_key[:10]}...")
                return site_key
        
        # Try to extract from inline scripts
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                self.logger.debug(f"Examining script content: {script.string[:100]}...")
                # Look for common reCAPTCHA v3 patterns
                # Pattern for grecaptcha.execute('site_key', ...)
                pattern1 = r"grecaptcha\.execute\s*\(\s*['\"]([A-Za-z0-9_-]{25,})['\"]"
                match1 = re.search(pattern1, script.string, re.DOTALL)
                if match1:
                    site_key = match1.group(1)
                    self.logger.debug(f"Found reCAPTCHA v3 site key in script (execute): {site_key[:10]}...")
                    return site_key
                
                # Pattern for grecaptcha.ready(function() { grecaptcha.execute('site_key', ...)
                pattern2 = r"grecaptcha\.ready\s*\(\s*function\s*\(\s*\)\s*\{\s*grecaptcha\.execute\s*\(\s*['\"]([A-Za-z0-9_-]{25,})['\"]"
                match2 = re.search(pattern2, script.string, re.DOTALL)
                if match2:
                    site_key = match2.group(1)
                    self.logger.debug(f"Found reCAPTCHA v3 site key in script (ready): {site_key[:10]}...")
                    return site_key
                
                # Pattern for reCAPTCHA rendering parameters
                pattern3 = r"recaptcha_site_key\s*[:=]\s*['\"]([A-Za-z0-9_-]{25,})['\"]"
                match3 = re.search(pattern3, script.string, re.IGNORECASE | re.DOTALL)
                if match3:
                    site_key = match3.group(1)
                    self.logger.debug(f"Found reCAPTCHA v3 site key in script (site_key var): {site_key[:10]}...")
                    return site_key
        
        self.logger.warning("Failed to extract reCAPTCHA v3 site key from page content")
        return None
    
    def _extract_recaptcha_v3_action(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract reCAPTCHA v3 action from HTML content.
        
        Args:
            soup: BeautifulSoup object containing parsed HTML
            
        Returns:
            str: Action if found, None otherwise
        """
        # Try to extract from inline scripts
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                # Look for common reCAPTCHA v3 action patterns
                import re
                # Pattern for action parameter in grecaptcha.execute
                pattern1 = r"grecaptcha\.execute\s*\(\s*['\"][A-Za-z0-9_-]{30,}['\"]\s*,\s*\{\s*action\s*:\s*['\"]([^'\"]+)['\"]"
                match1 = re.search(pattern1, script.string)
                if match1:
                    action = match1.group(1)
                    self.logger.debug(f"Found reCAPTCHA v3 action in script: {action}")
                    return action
                
                # Pattern for action in object
                pattern2 = r"action\s*:\s*['\"]([^'\"]+)['\"]"
                match2 = re.search(pattern2, script.string)
                if match2:
                    action = match2.group(1)
                    # Basic validation to avoid false positives
                    if action and len(action) > 2 and not action.startswith('http'):
                        self.logger.debug(f"Found reCAPTCHA v3 action in script (generic): {action}")
                        return action
        
        self.logger.warning("Failed to extract reCAPTCHA v3 action from page content")
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
                "url": job_data.get("url")
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
            "enabled": self.enabled
        }