"""
Browser Automation Engine for GengoWatcher
Handles automatic job acceptance through browser automation with CAPTCHA solving capabilities.
"""

import os
import random
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException

try:
    from webdriver_manager.chrome import ChromeDriverManager
    try:
        # Newer webdriver-manager
        from webdriver_manager.core.utils import ChromeType  # type: ignore
    except Exception:  # pragma: no cover
        ChromeType = None  # type: ignore
    _HAS_WDM = True
except Exception:
    ChromeType = None  # type: ignore
    _HAS_WDM = False


_ACCEPT_STATUS_SCRIPT = """
return (function(){
  const tokenField = document.querySelector('textarea#g-recaptcha-response, textarea[name="g-recaptcha-response"], textarea#h-captcha-response, textarea[name="h-captcha-response"]');
  const button = document.querySelector('form[action*="/t/jobs/accept"] button[type=submit], button[data-action=accept], button[type=submit]');
  const acceptEnabled = !!(button && !button.disabled);
  const tokenPresent = !!(tokenField && tokenField.value && tokenField.value.trim().length > 0);
  return { token_present: tokenPresent, accept_enabled: acceptEnabled };
})();
"""

_POST_CLICK_STATUS_SCRIPT = """
return (function(){
  const href = window.location.href;
  const successCandidate = document.querySelector('.flash-success, .alert-success, [data-status="accepted"]');
  const bodyText = document.body ? (document.body.innerText || '') : '';
  const hasAcceptedText = /accepted|successfully accepted|success/i.test(bodyText);
  return { url: href, hasSuccess: !!successCandidate || hasAcceptedText };
})();
"""


class BrowserAutomationEngine:
    """Browser automation engine for job acceptance"""
    def __init__(self, config, logger, captcha_solver=None):
        self.config = config
        self.logger = logger
        self.captcha_solver = captcha_solver
        self.driver: Optional[webdriver.Chrome] = None
        self._driver_lock = threading.RLock()
        self._monitor_threads: Set[threading.Thread] = set()
        self._seen_live_ids: Set[str] = set()
        self._seen_list_ids: Set[str] = set()
        self._accept_cancel_flags: Dict[str, threading.Event] = {}
        self._tabs: Dict[str, str] = {}
        self._suspend_event = threading.Event()
        self._manual_login_override = False
        self.logger.info("BrowserAutomationEngine initialized")

    def _safe_submit_first_form(self, driver: webdriver.Chrome) -> bool:
        """Try multiple strategies to submit the primary accept control."""
        try:
            for selector in [
                "button[type=submit]",
                "input[type=submit]",
                "button[data-action=accept]",
            ]:
                try:
                    btn = driver.find_element(By.CSS_SELECTOR, selector)
                    if btn.is_displayed():
                        btn.click()
                        return True
                except Exception:
                    continue
            try:
                btn = driver.find_element(By.XPATH, "//button[contains(., 'Accept')]")
                if btn.is_displayed():
                    btn.click()
                    return True
            except Exception:
                pass
            forms = driver.find_elements(By.TAG_NAME, "form")
            if forms:
                driver.execute_script("arguments[0].submit();", forms[0])
                return True
        except Exception as exc:
            self.logger.debug(f"Form submission attempt failed: {exc}")
        return False

    def submit_recaptcha_v2_with_token(self, page_url: str, token: str) -> bool:
        """Open page, inject g-recaptcha-response token and submit the form."""
        if not token:
            return False
        try:
            driver = self._initialize_driver()
            driver.get(page_url)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            # Ensure the response textarea exists or create one
            self.logger.debug("Injecting reCAPTCHA v2 token via DOM")
            self.driver.execute_script(
                """
                (function(t){
                  var areas = document.querySelectorAll('textarea#g-recaptcha-response, textarea[name="g-recaptcha-response"]');
                  if(areas.length===0){
                    var ta = document.createElement('textarea');
                    ta.id='g-recaptcha-response';
                    ta.name='g-recaptcha-response';
                    ta.style.display='block';
                    ta.style.width='1px';ta.style.height='1px'; ta.style.opacity='0.01';
                    document.body.appendChild(ta);
                    areas=[ta];
                  }
                  areas.forEach(function(a){ a.value=t; });
                })(arguments[0]);
                """,
                token,
            )
            submitted = self._safe_submit_first_form(driver)
            if not submitted:
                self.logger.debug("No form/button found to submit after token injection")
            WebDriverWait(driver, 5).until(lambda d: True)
            return submitted
        except Exception as e:
            self.logger.error(f"Error submitting reCAPTCHA v2 with browser automation: {e}")
            return False

    def submit_hcaptcha_with_token(self, page_url: str, token: str) -> bool:
        """Open page, inject h-captcha-response token and submit the form."""
        if not token:
            return False
        try:
            driver = self._initialize_driver()
            driver.get(page_url)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            self.logger.debug("Injecting hCaptcha token via DOM")
            self.driver.execute_script(
                """
                (function(t){
                  var areas = document.querySelectorAll('textarea#h-captcha-response, textarea[name="h-captcha-response"]');
                  if(areas.length===0){
                    var ta = document.createElement('textarea');
                    ta.id='h-captcha-response';
                    ta.name='h-captcha-response';
                    ta.style.display='block';
                    ta.style.width='1px';ta.style.height='1px'; ta.style.opacity='0.01';
                    document.body.appendChild(ta);
                    areas=[ta];
                  }
                  areas.forEach(function(a){ a.value=t; });
                })(arguments[0]);
                """,
                token,
            )
            submitted = self._safe_submit_first_form(driver)
            if not submitted:
                self.logger.debug("No form/button found to submit after token injection")
            WebDriverWait(driver, 5).until(lambda d: True)
            return submitted
        except Exception as e:
            self.logger.error(f"Error submitting hCaptcha with browser automation: {e}")
            return False
    
    def preload_page(self, page_url: str) -> bool:
        """Warm up the browser by navigating to a page in advance"""
        try:
            driver = self._initialize_driver()
            driver.get(page_url)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            return True
        except Exception as e:
            self.logger.debug(f"Preload failed: {e}")
            return False

    def open_job_details_and_arm_accept(self, page_url: str, probe_ms: int = 75, timeout_sec: int = 30) -> None:
        """Open details page and repeatedly try to submit acceptance ASAP."""
        def worker():
            try:
                d = self._initialize_driver()
                d.get(page_url)
                WebDriverWait(d, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                start = time.time()
                while time.time() - start < timeout_sec:
                    try:
                        token_any = d.execute_script(
                            "return (document.querySelector('textarea#g-recaptcha-response,textarea[name=\\'g-recaptcha-response\\']')||{value:''}).value ||" \
                            "(document.querySelector('textarea#h-captcha-response,textarea[name=\\'h-captcha-response\\']')||{value:''}).value;"
                        )
                    except Exception:
                        token_any = ""
                    if token_any:
                        if self._safe_submit_first_form(d):
                            self.logger.debug("Clicked accept after token present.")
                            time.sleep(0.8)
                            return
                    # Try clicking accept proactively
                    _ = self._safe_submit_first_form(d)
                    time.sleep(max(0.02, probe_ms / 1000.0))
            except Exception as e:
                self.logger.debug(f"Accept watcher error: {e}")
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        self._monitor_threads.add(t)

    def login_with_session(self, session_token: str) -> bool:
        """Set session cookie and verify a protected page loads as logged in.

        Optimization: after setting the cookie, immediately visit the realtime
        dashboard and the available-jobs list to warm caches and establish any
        ancillary cookies used by the site.
        """
        try:
            d = self._initialize_driver()
            d.get("https://gengo.com/")
            try:
                d.delete_cookie("my_gengo_session")
            except Exception:
                pass
            d.add_cookie({
                'name': 'my_gengo_session',
                'value': session_token,
                # Domain cookie so it applies to subdomains as well
                'domain': '.gengo.com',
                'path': '/',
                'secure': True
            })
            # Preflight realtime dashboard (websocket UI) then jobs list
            d.get("https://gengo.com/t/jobs/status/available/realtime")
            WebDriverWait(d, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            d.get("https://gengo.com/t/jobs/status/available")
            WebDriverWait(d, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            # Optionally pin tabs for realtime + list
            pin_tabs = False
            try:
                pin_tabs = self.config.getboolean("SeleniumMonitoring", "pin_tabs", fallback=True)
            except Exception:
                pin_tabs = True
            if pin_tabs:
                try:
                    self.ensure_pinned_tabs()
                except Exception as _e:
                    self.logger.debug(f"Pin tabs skipped: {_e}")
            self.logger.info("Selenium session cookie set; jobs page reachable.")
            return True
        except Exception as e:
            self.logger.error(f"Failed to set Selenium session: {e}")
            return False

    def start_live_dashboard_monitor(self, on_new_job: Callable[[str, str], None], interval_sec: float = 0.75) -> None:
        """Monitor the realtime view for new job links and invoke callback(job_id, url).

        Injects a MutationObserver into the page to collect newly-added job links
        without refreshing the page. The worker polls a small in-page queue.
        """
        def worker():
            try:
                d = self._initialize_driver()
                # Use a dedicated tab if available
                with self._driver_lock:
                    handle = self._tabs.get("realtime")
                    if handle and handle in d.window_handles:
                        d.switch_to.window(handle)
                    else:
                        d.get("https://gengo.com/t/jobs/status/available/realtime")
                        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                        # Track this tab
                        try:
                            self._tabs["realtime"] = d.current_window_handle
                        except Exception:
                            pass
                # Install observer and seed queue with existing links
                try:
                    with self._driver_lock:
                        d.execute_script(
                            """
                            (function(){
                              try {
                                if (!window._GW) window._GW = {};
                                if (!window._GW.newJobs) window._GW.newJobs = [];
                                if (!window._GW._observerAttached) {
                                  const pushJob = href => {
                                    try { if (href && href.indexOf('/t/jobs/details/') !== -1) { window._GW.newJobs.push(href); } } catch(e){}
                                  };
                                  // Seed existing links
                                  try { document.querySelectorAll("a[href*='/t/jobs/details/']").forEach(a => pushJob(a.href)); } catch(e){}
                                  const obs = new MutationObserver(muts => {
                                    muts.forEach(m => {
                                      if (m.addedNodes) {
                                        m.addedNodes.forEach(node => {
                                          if (node && node.nodeType === 1) {
                                            try { node.querySelectorAll("a[href*='/t/jobs/details/']").forEach(a => pushJob(a.href)); } catch(e){}
                                          }
                                        });
                                      }
                                    });
                                  });
                                  obs.observe(document.body || document.documentElement, { childList: true, subtree: true });
                                  window._GW._observerAttached = true;
                                  window._GW._observer = obs;
                                }
                              } catch(e){}
                            })();
                            """
                        )
                except Exception:
                    pass
                # Humanized periodic refresh window (disabled if min<=0)
                try:
                    rr_min = int(self.config.getint("SeleniumMonitoring", "realtime_refresh_min_sec", fallback=120))
                except Exception:
                    rr_min = 120
                try:
                    rr_max = int(self.config.getint("SeleniumMonitoring", "realtime_refresh_max_sec", fallback=300))
                except Exception:
                    rr_max = 300
                if rr_max < rr_min:
                    rr_max = rr_min
                def _next_refresh_from(now: float) -> float:
                    if rr_min <= 0:
                        return float('inf')
                    return now + random.uniform(max(1.0, float(rr_min)), max(1.0, float(rr_max)))

                next_refresh = _next_refresh_from(time.time())

                while True:
                    try:
                        if self._suspend_event.is_set():
                            time.sleep(0.25)
                            continue
                        # Ensure we're in the correct tab
                        with self._driver_lock:
                            h = self._tabs.get("realtime")
                            if h and h in d.window_handles:
                                d.switch_to.window(h)
                            # Pop queued links from the page
                            try:
                                links = d.execute_script(
                                    "var q=(window._GW&&window._GW.newJobs)?window._GW.newJobs.slice():[]; if(window._GW) window._GW.newJobs=[]; return q;"
                                ) or []
                            except Exception:
                                links = []
                        # Process newly observed links
                        for href in links:
                            try:
                                if not href or '/t/jobs/details/' not in href:
                                    continue
                                job_id = href.split('/details/')[-1].split('?')[0]
                                if job_id and job_id not in self._seen_live_ids:
                                    self._seen_live_ids.add(job_id)
                                    on_new_job(job_id, href)
                            except Exception:
                                continue
                        # Humanized occasional refresh of realtime page
                        now = time.time()
                        if now >= next_refresh:
                            try:
                                with self._driver_lock:
                                    d.refresh()
                                    # Reinstall observer after refresh
                                    d.execute_script(
                                        """
                                        (function(){
                                          try {
                                            if (!window._GW) window._GW = {};
                                            window._GW.newJobs = [];
                                            const pushJob = href => { try { if (href && href.indexOf('/t/jobs/details/') !== -1) { window._GW.newJobs.push(href); } } catch(e){} };
                                            try { document.querySelectorAll("a[href*='/t/jobs/details/']").forEach(a => pushJob(a.href)); } catch(e){}
                                            const obs = new MutationObserver(muts => {
                                              muts.forEach(m => {
                                                if (m.addedNodes) {
                                                  m.addedNodes.forEach(node => {
                                                    if (node && node.nodeType === 1) {
                                                      try { node.querySelectorAll("a[href*='/t/jobs/details/']").forEach(a => pushJob(a.href)); } catch(e){}
                                                    }
                                                  });
                                                }
                                              });
                                            });
                                            obs.observe(document.body || document.documentElement, { childList: true, subtree: true });
                                            window._GW._observerAttached = true;
                                            window._GW._observer = obs;
                                          } catch(e){}
                                        })();
                                        """
                                    )
                            except Exception:
                                pass
                            next_refresh = _next_refresh_from(now)
                    except Exception:
                        pass
                    time.sleep(interval_sec)
            except Exception as e:
                self.logger.error(f"Live dashboard monitor error: {e}")
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        self._monitor_threads.add(t)

    def start_jobs_page_refresher(self, on_new_job: Callable[[str, str], None], interval_sec: float = 1.5) -> None:
        """Refresh the jobs list periodically and invoke callback(job_id, url) for new rows."""
        def worker():
            try:
                d = self._initialize_driver()
                with self._driver_lock:
                    handle = self._tabs.get("list")
                    if handle and handle in d.window_handles:
                        d.switch_to.window(handle)
                    else:
                        d.get("https://gengo.com/t/jobs/status/available")
                        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                        try:
                            self._tabs["list"] = d.current_window_handle
                        except Exception:
                            pass
                while True:
                    try:
                        if self._suspend_event.is_set():
                            time.sleep(0.25)
                            continue
                        # Ensure correct tab and probe links
                        with self._driver_lock:
                            h = self._tabs.get("list")
                            if h and h in d.window_handles:
                                d.switch_to.window(h)
                            links = d.find_elements(By.CSS_SELECTOR, "a[href*='/t/jobs/details/']")
                        new_found = False
                        for a in links:
                            href = a.get_attribute("href") or ""
                            if "/t/jobs/details/" in href:
                                job_id = href.split("/details/")[-1].split("?")[0]
                                if job_id and job_id not in self._seen_list_ids:
                                    self._seen_list_ids.add(job_id)
                                    on_new_job(job_id, href)
                                    new_found = True
                        time.sleep(interval_sec)
                        if not new_found:
                            with self._driver_lock:
                                d.refresh()
                    except Exception:
                        time.sleep(interval_sec)
                        with self._driver_lock:
                            d.refresh()
            except Exception as e:
                self.logger.error(f"Jobs refresher error: {e}")
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        self._monitor_threads.add(t)

    def ensure_pinned_tabs(self) -> bool:
        """Open and remember dedicated tabs for realtime and list views.

        Returns True if tabs exist or were created.
        """
        try:
            d = self._initialize_driver()
            with self._driver_lock:
                # Realtime tab
                handle = self._tabs.get("realtime")
                if not (handle and handle in d.window_handles):
                    d.execute_script("window.open('https://gengo.com/t/jobs/status/available/realtime','_blank');")
                    self._tabs["realtime"] = d.window_handles[-1]
                # List tab
                handle = self._tabs.get("list")
                if not (handle and handle in d.window_handles):
                    d.execute_script("window.open('https://gengo.com/t/jobs/status/available','_blank');")
                    self._tabs["list"] = d.window_handles[-1]
            return True
        except Exception as e:
            self.logger.debug(f"ensure_pinned_tabs failed: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Return a snapshot of Selenium/monitoring status for UI display."""
        status: Dict[str, Any] = {
            "driver_initialized": bool(self.driver),
            "tabs": {"realtime": False, "list": False},
            "monitor_threads": 0,
        }
        try:
            with self._driver_lock:
                if self.driver:
                    handles = set(self.driver.window_handles)
                    status["tabs"]["realtime"] = (
                        (self._tabs.get("realtime") or "") in handles
                    )
                    status["tabs"]["list"] = (
                        (self._tabs.get("list") or "") in handles
                    )
        except Exception:
            pass
        try:
            status["monitor_threads"] = sum(1 for t in self._monitor_threads if t.is_alive())
        except Exception:
            status["monitor_threads"] = 0
        status["suspended"] = self._suspend_event.is_set()
        return status

    def _check_session_cookie(self) -> bool:
        """Return True if my_gengo_session cookie exists and is non-empty for gengo.com."""
        try:
            with self._driver_lock:
                d = self._initialize_driver()
                # Must be on the correct domain to read cookie
                d.get("https://gengo.com/")
                WebDriverWait(d, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                c = d.get_cookie("my_gengo_session")
                return bool(c and c.get("value"))
        except Exception:
            return False

    def is_logged_in(self) -> bool:
        """Public helper to determine if Selenium currently has a valid session."""
        if self._manual_login_override:
            return True
        return self._check_session_cookie()

    def set_manual_login_override(self, value: bool = True) -> None:
        self._manual_login_override = bool(value)
        self.logger.info("Manual login override set to %s", self._manual_login_override)

    def open_login_assist(self, timeout_sec: float = 120.0) -> bool:
        """Open the jobs pages and wait until the user completes login.

        - Opens both: 
          • https://gengo.com/t/jobs/status/available
          • https://gengo.com/t/jobs/status/available/realtime
        - Waits up to timeout_sec for a valid session cookie
        - On success, keeps tabs pinned and returns True
        """
        try:
            with self._driver_lock:
                d = self._initialize_driver()
                self.logger.info("Login Assist: opening jobs list and realtime dashboard — complete login in the opened window(s).")
                # Ensure pinned tabs to both targets
                self.ensure_pinned_tabs()
                # Focus list tab, ensure body loaded
                handle = self._tabs.get("list")
                if handle and handle in d.window_handles:
                    d.switch_to.window(handle)
                else:
                    d.get("https://gengo.com/t/jobs/status/available")
                WebDriverWait(d, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                # Also load realtime tab
                handle_rt = self._tabs.get("realtime")
                if handle_rt and handle_rt in d.window_handles:
                    d.switch_to.window(handle_rt)
                else:
                    d.get("https://gengo.com/t/jobs/status/available/realtime")
                WebDriverWait(d, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except Exception as e:
            self.logger.error(f"Login Assist: failed to open auth form: {e}")
            return False

        deadline = time.time() + max(5.0, float(timeout_sec))
        last_ping = 0.0
        while time.time() < deadline:
            if self._check_session_cookie():
                try:
                    self.ensure_pinned_tabs()
                except Exception:
                    pass
                self.logger.info("Login Assist: login detected; proceeding with monitors.")
                return True
            # Throttle status logging
            now = time.time()
            if now - last_ping > 5.0:
                self.logger.info("Login Assist: waiting for login to complete...")
                last_ping = now
            time.sleep(0.5)

        self.logger.warning("Login Assist: timed out waiting for login.")
        return False

    # Monitor control API
    def suspend_monitors(self) -> None:
        self._suspend_event.set()
        self.logger.info("Selenium monitors suspended (waiting for manual login)")

    def resume_monitors(self) -> None:
        if self._suspend_event.is_set():
            self._suspend_event.clear()
            self.logger.info("Selenium monitors resumed")

    def _initialize_driver(self) -> webdriver.Chrome:
        """Initialize Chrome WebDriver with appropriate options

        Honors these config options when available:
        - [SeleniumMonitoring] headless: bool
        - [SeleniumMonitoring] chrome_binary_path: str (binary path)
        - [AutoAccept] browser_profile_path: str (existing Chrome user-data-dir for persisted login)
        """
        if self.driver:
            return self.driver
            
        chrome_options = Options()
        # Headless toggle from config
        headless = False
        try:
            headless = self.config.getboolean("SeleniumMonitoring", "headless", fallback=False)
        except Exception:
            headless = False
        if headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # Optional Chrome/Chromium binary path from config
        try:
            binary_path = self.config.get("SeleniumMonitoring", "chrome_binary_path")
        except Exception:
            binary_path = None
        if not binary_path:
            try:
                candidate = self.config.get("Paths", "browser_path")
                if candidate:
                    binary_path = candidate
            except Exception:
                binary_path = None
        if binary_path and Path(str(binary_path)).is_file():
            chrome_options.binary_location = str(binary_path)
            self.logger.info(f"Selenium Chrome binary set to: {binary_path}")
        
        # Add user agent if configured
        user_agent = None
        if hasattr(self.config, "get"):
            try:
                user_agent = self.config.get("Watcher", "user_agent")
            except Exception:
                user_agent = None
        if user_agent:
            chrome_options.add_argument(f"--user-agent={user_agent}")
        # Use basic password store to avoid keyring prompts; helps persist logins
        try:
            force_basic_pw = self.config.getboolean("SeleniumMonitoring", "force_basic_password_store", fallback=True)
        except Exception:
            force_basic_pw = True
        if force_basic_pw:
            chrome_options.add_argument("--password-store=basic")
        
        # Use existing Chrome user data dir to reuse login/cookies if configured
        try:
            profile_path = None
            try:
                profile_path = self.config.get("AutoAccept", "browser_profile_path")
            except Exception:
                profile_path = None
            if profile_path:
                pp = Path(str(profile_path))
                if pp.exists():
                    chrome_options.add_argument(f"--user-data-dir={pp}")
                    self.logger.info(f"Using Chrome user-data-dir for Selenium: {pp}\n")
        except Exception:
            # Non-fatal; proceed without profile
            pass
        
        try:
            if _HAS_WDM:
                # Choose driver type based on binary path (Chromium vs Google Chrome)
                mgr_kwargs = {}
                try:
                    if chrome_options.binary_location and 'chromium' in chrome_options.binary_location.lower() and ChromeType:
                        mgr_kwargs = {"chrome_type": ChromeType.CHROMIUM}
                except Exception:
                    mgr_kwargs = {}
                try:
                    # First, try webdriver-manager install (may fail in restricted environments)
                    install_path = ChromeDriverManager(**mgr_kwargs).install()
                    self.driver = webdriver.Chrome(
                        service=Service(install_path),
                        options=chrome_options,
                    )
                except Exception as e:
                    # Fallback to system chromedriver on PATH or Selenium-managed discovery
                    self.logger.warning(
                        f"WebDriverManager install failed ({e}); trying system ChromeDriver"
                    )
                    self.driver = webdriver.Chrome(options=chrome_options)
            else:
                # No webdriver-manager; rely on system chromedriver
                self.driver = webdriver.Chrome(options=chrome_options)
            self.logger.info("Chrome WebDriver initialized successfully")
            return self.driver
        except Exception as e:
            self.logger.error(f"Failed to initialize Chrome WebDriver: {e}")
            raise

    def attempt_accept_via_browser(
        self,
        job_data: Dict[str, Any],
        probe_ms: int,
        timeout_sec: float,
        cancel_event: threading.Event,
        timings: Dict[str, Optional[float]],
        start_monotonic: Optional[float],
    ) -> Dict[str, Any]:
        """Synchronously attempt to accept a job using Selenium, respecting cancellation."""
        result_timings: Dict[str, Optional[float]] = dict(timings or {})
        job_id = str(job_data.get("id"))
        page_url = job_data.get("url") or f"https://gengo.com/t/jobs/details/{job_id}"
        outcome: Dict[str, Any] = {
            "success": False,
            "redirect": False,
            "reason": "timeout",
            "timings": result_timings,
        }

        try:
            driver = self._initialize_driver()
        except Exception as exc:  # pragma: no cover - initialization failure
            outcome["reason"] = f"init_error:{exc}"
            return outcome

        start_time = time.perf_counter()
        poll_interval = max(0.02, probe_ms / 1000.0)

        try:
            with self._driver_lock:
                driver.get(page_url)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            if start_monotonic:
                result_timings.setdefault(
                    "details_ms", (time.perf_counter() - start_monotonic) * 1000.0
                )
            baseline_url = driver.current_url

            while time.perf_counter() - start_time < timeout_sec:
                if cancel_event.is_set():
                    outcome["reason"] = "cancelled"
                    break

                with self._driver_lock:
                    status = driver.execute_script(_ACCEPT_STATUS_SCRIPT)
                token_present = bool(status.get("token_present"))
                accept_enabled = bool(status.get("accept_enabled"))

                if token_present and start_monotonic and result_timings.get("token_ms") is None:
                    result_timings["token_ms"] = (
                        time.perf_counter() - start_monotonic
                    ) * 1000.0

                if token_present or accept_enabled:
                    with self._driver_lock:
                        clicked = self._safe_submit_first_form(driver)
                    if clicked:
                        if start_monotonic and result_timings.get("click_ms") is None:
                            result_timings["click_ms"] = (
                                time.perf_counter() - start_monotonic
                            ) * 1000.0
                        completion = self._await_post_click(
                            driver, baseline_url, cancel_event, start_monotonic
                        )
                        if completion.get("success"):
                            if (
                                start_monotonic
                                and completion.get("redirect_ms") is not None
                                and result_timings.get("redirect_ms") is None
                            ):
                                result_timings["redirect_ms"] = completion["redirect_ms"]
                            outcome.update(completion)
                            outcome["timings"] = result_timings
                            return outcome
                time.sleep(poll_interval)

            if not outcome["success"] and not cancel_event.is_set():
                outcome["reason"] = "timeout"
        except WebDriverException as exc:
            outcome["reason"] = f"webdriver_error:{exc}"
            self.logger.debug(
                "Selenium accept attempt failed for job %s: %s", job_id, exc
            )
            self._capture_screenshot(job_id, driver)
        except Exception as exc:  # pragma: no cover - defensive
            outcome["reason"] = f"error:{exc}"
            self.logger.debug(
                "Unexpected browser error while accepting job %s", job_id, exc_info=True
            )
            self._capture_screenshot(job_id, driver)

        outcome["timings"] = result_timings
        return outcome

    def _await_post_click(
        self,
        driver: webdriver.Chrome,
        baseline_url: str,
        cancel_event: threading.Event,
        start_monotonic: Optional[float],
        wait_timeout: float = 4.0,
    ) -> Dict[str, Any]:
        deadline = time.perf_counter() + wait_timeout
        while time.perf_counter() < deadline:
            if cancel_event.is_set():
                return {"success": False, "redirect": False, "reason": "cancelled"}
            with self._driver_lock:
                status = driver.execute_script(_POST_CLICK_STATUS_SCRIPT)
            current_url = status.get("url") or ""
            has_success = bool(status.get("hasSuccess"))
            if current_url and current_url != baseline_url:
                redirect_ms = None
                if start_monotonic:
                    redirect_ms = (time.perf_counter() - start_monotonic) * 1000.0
                return {
                    "success": True,
                    "redirect": True,
                    "reason": "accepted",
                    "redirect_ms": redirect_ms,
                }
            if has_success:
                redirect_ms = None
                if start_monotonic:
                    redirect_ms = (time.perf_counter() - start_monotonic) * 1000.0
                return {
                    "success": True,
                    "redirect": False,
                    "reason": "accepted",
                    "redirect_ms": redirect_ms,
                }
            time.sleep(0.05)
        return {"success": False, "redirect": False, "reason": "timeout"}

    def _capture_screenshot(
        self, job_id: str, driver: webdriver.Chrome
    ) -> Optional[Path]:
        try:
            output_dir = Path("logs/screenshots")
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = output_dir / f"job_{job_id}_{int(time.time() * 1000)}.png"
            driver.get_screenshot_as_file(str(filename))
            self.logger.debug("Saved failure screenshot to %s", filename)
            return filename
        except Exception:
            self.logger.debug("Failed to capture screenshot for job %s", job_id, exc_info=True)
            return None
    
    def solve_recaptcha_v3_with_browser(
        self, site_key: str, page_url: str, action: str = "job_acceptance"
    ) -> Optional[str]:
        """
        Solve reCAPTCHA v3 using browser automation to execute the challenge.
        
        Args:
            site_key: reCAPTCHA v3 site key
            page_url: URL of the page where reCAPTCHA is used
            action: Action name for reCAPTCHA v3
            
        Returns:
            str: reCAPTCHA v3 token if successful, None otherwise
        """
        enable_fallback = False
        if hasattr(self.config, "getboolean"):
            try:
                enable_fallback = self.config.getboolean(
                    "Captcha", "enable_browser_automation_fallback", fallback=False
                )
            except Exception:
                enable_fallback = False
        if not enable_fallback:
            self.logger.debug("Browser automation fallback is disabled")
            return None
            
        try:
            driver = self._initialize_driver()
            
            # Navigate to the page
            self.logger.debug(f"Navigating to page: {page_url}")
            driver.get(page_url)
            
            # Wait for page to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Execute reCAPTCHA v3 challenge using JavaScript
            script = f"""
            return new Promise((resolve, reject) => {{
                try {{
                    grecaptcha.ready(function() {{
                        grecaptcha.execute('{site_key}', {{action: '{action}'}}).then(function(token) {{
                            resolve(token);
                        }}).catch(function(error) {{
                            reject(error.message);
                        }});
                    }});
                }} catch (error) {{
                    reject(error.message);
                }}
            }});
            """
            
            self.logger.debug("Executing reCAPTCHA v3 challenge")
            token = driver.execute_script(script)
            
            if token:
                self.logger.info("Successfully obtained reCAPTCHA v3 token using browser automation")
                return token
            else:
                self.logger.warning("Failed to obtain reCAPTCHA v3 token using browser automation")
                return None
                
        except Exception as e:
            self.logger.error(f"Error solving reCAPTCHA v3 with browser automation: {e}")
            return None
    
    def close(self):
        """Close the browser driver and clean up resources"""
        if self.driver:
            try:
                self.driver.quit()
                self.logger.debug("Browser driver closed successfully")
            except Exception as e:
                self.logger.warning(f"Error closing browser driver: {e}")
            finally:
                self.driver = None
