"""
Website Monitor - Stealth Playwright browser automation.

Monitors Gengo jobs page using human-like behavior patterns to avoid detection.
Uses randomized timing, natural mouse movements, and realistic browsing patterns.
"""

import asyncio
import random
import re
import time
import math
import logging
from typing import Optional, Callable, Awaitable, List, Tuple

from .config import AppConfig


class WebsiteMonitor:
    JOB_URL_PATTERN = re.compile(r"/t/jobs/details/(\d+)")

    TIMING = {
        "action_delay_mean": 2.5,
        "action_delay_std": 0.8,
        "scroll_pause_mean": 1.5,
        "scroll_pause_std": 0.5,
        "mouse_move_steps": 25,
        "mouse_move_duration": 0.5,
    }

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        job_callback: Callable[[str, str, float, str, str], Awaitable[None]],
        shutdown_event: asyncio.Event,
    ):
        self.config = config
        self.logger = logger
        self.job_callback = job_callback
        self.shutdown_event = shutdown_event
        self._browser = None
        self._context = None
        self._page = None
        self._seen_job_ids: set[str] = set()
        self._playwright = None
        self.status = "Disabled"  # Initializing/Scraping/Idle/Error/Disabled
        self.last_check_time: Optional[float] = None
        self.jobs_found_session = 0
        self.pages_checked_session = 0

    async def start(self):
        if not self.config.get("WebsiteMonitor", "enabled"):
            self.logger.debug("Website monitor disabled")
            return

        self.status = "Initializing"
        self.logger.info("Starting website monitor")

        try:
            await self._init_browser()
            await self._login_if_needed()
            await self._monitor_loop()
        except Exception as e:
            self.status = "Error"
            self.logger.error(f"Website monitor error: {e}")
        finally:
            await self.stop()

    async def _init_browser(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.logger.error(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )
            raise RuntimeError("Playwright not installed")

        self._playwright = await async_playwright().start()

        headless = self.config.get("WebsiteMonitor", "headless")
        if headless is None:
            headless = True

        viewport_width = 1920 + random.randint(-50, 50)
        viewport_height = 1080 + random.randint(-50, 50)

        launch_options = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        }

        browser_executable = self.config.get("WebsiteMonitor", "browser_executable")
        if browser_executable:
            from pathlib import Path

            if Path(browser_executable).is_file():
                launch_options["executable_path"] = browser_executable
                self.logger.info(f"Using custom browser: {browser_executable}")
            else:
                self.logger.warning(
                    f"Custom browser executable not found: {browser_executable}, falling back to Chromium"
                )

        self._browser = await self._playwright.chromium.launch(**launch_options)

        self._context = await self._browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
            user_agent=self._get_realistic_user_agent(),
            locale="en-US",
            timezone_id="America/New_York",
        )

        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)

        self._page = await self._context.new_page()
        self.logger.debug(
            f"Browser initialized (viewport: {viewport_width}x{viewport_height})"
        )

    def _get_realistic_user_agent(self) -> str:
        chrome_versions = ["120.0.0.0", "121.0.0.0", "122.0.0.0", "123.0.0.0"]
        version = random.choice(chrome_versions)
        return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"

    async def _login_if_needed(self):
        session_cookie = self.config.get("WebsiteMonitor", "session_cookie")
        if not session_cookie:
            self.logger.warning("No session cookie configured for website monitor")
            return

        await self._context.add_cookies(
            [
                {
                    "name": "_gengo_session",
                    "value": session_cookie,
                    "domain": ".gengo.com",
                    "path": "/",
                }
            ]
        )

        jobs_url = (
            self.config.get("WebsiteMonitor", "jobs_url") or "https://gengo.com/t/jobs/"
        )
        await self._page.goto(jobs_url)
        await self._human_delay()

        if "/sign_in" in self._page.url:
            self.logger.error(
                "Session cookie invalid or expired. Please update WebsiteMonitor.session_cookie"
            )
            return

        self.logger.info("Successfully authenticated to Gengo website")

    async def _monitor_loop(self):
        check_min = self.config.get("WebsiteMonitor", "check_interval_min") or 120
        check_max = self.config.get("WebsiteMonitor", "check_interval_max") or 300

        # Ensure min <= max
        if check_min > check_max:
            check_min, check_max = check_max, check_min
            self.logger.warning(
                f"WebsiteMonitor: Swapped min/max intervals ({check_min}s-{check_max}s)"
            )

        jobs_url = (
            self.config.get("WebsiteMonitor", "jobs_url") or "https://gengo.com/t/jobs/"
        )

        initial_jobs = await self._scrape_job_ids()
        self._seen_job_ids.update(initial_jobs)
        self.logger.debug(f"Initial scan found {len(initial_jobs)} existing jobs")

        while not self.shutdown_event.is_set():
            try:
                interval = random.uniform(check_min, check_max)
                self.logger.debug(f"Next check in {interval:.0f}s")

                await asyncio.sleep(interval)

                if self.shutdown_event.is_set():
                    break

                self.status = "Scraping"
                await self._human_mouse_wiggle()
                await self._page.goto(jobs_url)
                await self._human_delay()
                await self._human_scroll()

                current_jobs = await self._scrape_job_ids()
                new_jobs = current_jobs - self._seen_job_ids

                self.status = "Idle"
                self.last_check_time = time.time()
                self.pages_checked_session += 1

                if new_jobs:
                    self.logger.info(f"Found {len(new_jobs)} new job(s) on website")
                    self.jobs_found_session += len(new_jobs)
                    for job_id in new_jobs:
                        url = f"https://gengo.com/t/jobs/details/{job_id}"
                        await self.job_callback(
                            job_id,
                            "Job from website",
                            0.0,
                            url,
                            "website",
                        )

                self._seen_job_ids.update(current_jobs)

            except Exception as e:
                self.status = "Error"
                self.logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(60)

    async def _scrape_job_ids(self) -> set[str]:
        job_ids = set()

        try:
            content = await self._page.content()
            matches = self.JOB_URL_PATTERN.findall(content)
            job_ids.update(matches)

            links = await self._page.query_selector_all('a[href*="/jobs/details/"]')
            for link in links:
                href = await link.get_attribute("href")
                if href:
                    match = self.JOB_URL_PATTERN.search(href)
                    if match:
                        job_ids.add(match.group(1))

        except Exception as e:
            self.logger.debug(f"Scrape error: {e}")

        return job_ids

    async def _human_delay(self, multiplier: float = 1.0):
        delay = max(
            0.1,
            random.gauss(
                self.TIMING["action_delay_mean"] * multiplier,
                self.TIMING["action_delay_std"] * multiplier,
            ),
        )
        await asyncio.sleep(delay)

    async def _human_mouse_wiggle(self):
        if not self._page:
            return

        try:
            viewport = self._page.viewport_size
            if not viewport:
                return

            x = random.randint(100, viewport["width"] - 100)
            y = random.randint(100, viewport["height"] - 100)

            await self._bezier_mouse_move(x, y)
        except Exception:
            pass

    async def _bezier_mouse_move(self, target_x: int, target_y: int):
        if not self._page:
            return

        try:
            current = await self._page.evaluate("() => ({x: 0, y: 0})")
            start_x, start_y = current.get("x", 0), current.get("y", 0)
        except Exception:
            start_x, start_y = 0, 0

        ctrl1_x = start_x + random.randint(-50, 50)
        ctrl1_y = start_y + random.randint(-50, 50)
        ctrl2_x = target_x + random.randint(-50, 50)
        ctrl2_y = target_y + random.randint(-50, 50)

        steps = self.TIMING["mouse_move_steps"]
        duration = self.TIMING["mouse_move_duration"]

        for i in range(steps + 1):
            t = i / steps
            x = self._bezier_point(t, start_x, ctrl1_x, ctrl2_x, target_x)
            y = self._bezier_point(t, start_y, ctrl1_y, ctrl2_y, target_y)

            await self._page.mouse.move(x, y)
            await asyncio.sleep(duration / steps)

    def _bezier_point(
        self, t: float, p0: float, p1: float, p2: float, p3: float
    ) -> float:
        return (
            (1 - t) ** 3 * p0
            + 3 * (1 - t) ** 2 * t * p1
            + 3 * (1 - t) * t**2 * p2
            + t**3 * p3
        )

    async def _human_scroll(self):
        if not self._page:
            return

        try:
            viewport = self._page.viewport_size
            if not viewport:
                return

            scroll_amount = random.randint(200, 500)
            scroll_steps = random.randint(3, 6)
            step_amount = scroll_amount // scroll_steps

            for _ in range(scroll_steps):
                await self._page.mouse.wheel(0, step_amount)
                pause = max(
                    0.05,
                    random.gauss(
                        self.TIMING["scroll_pause_mean"] / scroll_steps,
                        self.TIMING["scroll_pause_std"] / scroll_steps,
                    ),
                )
                await asyncio.sleep(pause)

            if random.random() < 0.3:
                await asyncio.sleep(random.uniform(0.5, 1.5))
                scroll_back = random.randint(50, 150)
                await self._page.mouse.wheel(0, -scroll_back)

        except Exception:
            pass

    async def stop(self):
        self.status = "Stopped"
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None

        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        self.logger.info("Website monitor stopped")

    def get_status_info(self) -> dict:
        return {
            "status": self.status,
            "last_check": self.last_check_time,
            "jobs_found": self.jobs_found_session,
            "pages_checked": self.pages_checked_session,
        }
