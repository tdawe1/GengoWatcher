import logging
import threading
import time
from typing import Optional, Dict, Any
from .captcha_solver import (
    BaseCaptchaSolver, 
    TwoCaptchaSolver, 
    AntiCaptchaSolver, 
    CaptchaServiceType,
    CaptchaSolution,
    CaptchaSolverError,
    CaptchaSolverBalanceError,
    CaptchaSolverTimeoutError
)
from .secure_storage import SecureKeyStorage
from .rate_limiter import RateLimiter


class CaptchaSolverManager:
    """Manages CAPTCHA solving services and integration with GengoWatcher"""
    
    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.solver: Optional[BaseCaptchaSolver] = None
        self._lock = threading.RLock()
        self._stats = {
            'solved_count': 0,
            'failed_count': 0,
            'total_cost': 0.0,
            'last_solved_at': None
        }
        self._rate_limiter = RateLimiter(
            max_requests=config.get('Captcha', {}).get('rate_limit', 60),
            time_window=config.get('Captcha', {}).get('rate_limit_window', 60)
        )
        self._storage = SecureKeyStorage(logger=self.logger)
        self._initialize_solver()
    
    def close(self):
        """Close the CAPTCHA solver and clean up resources"""
        if self.solver:
            try:
                self.solver.close()
                self.logger.debug("CAPTCHA solver closed successfully")
            except Exception as e:
                self.logger.warning(f"Error closing CAPTCHA solver: {e}")
            finally:
                self.solver = None
    
    def _initialize_solver(self):
        """Initialize the CAPTCHA solver based on configuration"""
        try:
            # Check if CAPTCHA solving is enabled
            enabled = self.config.get('Captcha', {}).get('enabled', True)
            if not enabled:
                self.logger.info("CAPTCHA solving is disabled")
                self.solver = None
                return

            service_type = self.config.get('Captcha', {}).get('service', '').lower()

            if not service_type:
                self.logger.info("CAPTCHA solver not configured")
                return
            
            # Retrieve API key from secure storage
            api_key = self._storage.retrieve_api_key(service_type)
            
            if not api_key:
                self.logger.warning(f"API key for {service_type} not found in secure storage")
                return
            
            if service_type == CaptchaServiceType.TWO_CAPTCHA.value:
                self.solver = TwoCaptchaSolver(api_key, self.logger)
                self.logger.info("Initialized 2Captcha solver")
            elif service_type == CaptchaServiceType.ANTI_CAPTCHA.value:
                self.solver = AntiCaptchaSolver(api_key, self.logger)
                self.logger.info("Initialized Anti-Captcha solver")
            else:
                self.logger.warning(f"Unknown CAPTCHA service: {service_type}")
                return
                
        except Exception as e:
            self.logger.error(f"Failed to initialize CAPTCHA solver: {e}")
            self.solver = None
    
    def is_configured(self) -> bool:
        """Check if CAPTCHA solver is properly configured and enabled"""
        # Check if CAPTCHA solving is enabled
        enabled = self.config.get('Captcha', {}).get('enabled', True)
        if not enabled:
            return False

        return self.solver is not None
    
    def get_balance(self) -> float:
        """Get current account balance"""
        if not self.is_configured():
            return 0.0
        
        try:
            return self.solver.get_balance()
        except Exception as e:
            self.logger.error(f"Failed to get balance: {e}")
            return 0.0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get CAPTCHA solving statistics"""
        with self._lock:
            # Return a copy of stats with computed values
            stats = self._stats.copy()
            # Add current rate information
            stats['current_rate'] = self._rate_limiter.get_current_rate()
            return stats
    
    def _wait_for_rate_limit(self) -> bool:
        """Wait for rate limit clearance"""
        wait_time = self._rate_limiter.wait_time()
        if wait_time > 0:
            self.logger.warning(f"Rate limit reached, waiting {wait_time:.2f} seconds")
            time.sleep(wait_time)
        
        return self._rate_limiter.acquire()
    
    def solve_recaptcha_v2(self, site_key: str, page_url: str, **kwargs) -> Optional[CaptchaSolution]:
        """Solve reCAPTCHA v2 with error handling and retry logic"""
        if not self.is_configured():
            self.logger.warning("CAPTCHA solver not configured")
            return None
        
        # Check rate limit
        if not self._wait_for_rate_limit():
            self.logger.error("Failed to acquire rate limit permission")
            return None
        
        max_retries = self.config.get('Captcha', {}).get('max_retries', 3)
        retry_delay = self.config.get('Captcha', {}).get('retry_delay', 5)
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Solving reCAPTCHA v2 (attempt {attempt + 1}/{max_retries})")
                solution = self.solver.solve_recaptcha_v2(site_key, page_url, **kwargs)
                
                with self._lock:
                    self._stats['solved_count'] += 1
                    self._stats['last_solved_at'] = time.time()
                    # Add cost if available
                    if solution.cost is not None:
                        self._stats['total_cost'] += solution.cost
                
                self.logger.info("CAPTCHA solved successfully")
                return solution
                
            except CaptchaSolverBalanceError:
                self.logger.error("Insufficient balance for CAPTCHA solving")
                with self._lock:
                    self._stats['failed_count'] += 1
                return None
                
            except CaptchaSolverTimeoutError as e:
                self.logger.warning(f"CAPTCHA solving timed out (attempt {attempt + 1}): {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    self.logger.error("All CAPTCHA solving attempts timed out")
                    return None
                    
            except CaptchaSolverError as e:
                self.logger.warning(f"CAPTCHA solving failed (attempt {attempt + 1}): {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    self.logger.error("All CAPTCHA solving attempts failed")
                    return None
                    
            except Exception as e:
                self.logger.error(f"Unexpected error during CAPTCHA solving: {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                return None
        
        return None
    
    def solve_recaptcha_v3(self, site_key: str, page_url: str, action: str = "verify", **kwargs) -> Optional[CaptchaSolution]:
        """Solve reCAPTCHA v3 with error handling and retry logic"""
        if not self.is_configured():
            self.logger.warning("CAPTCHA solver not configured")
            return None
        
        # Check rate limit
        if not self._wait_for_rate_limit():
            self.logger.error("Failed to acquire rate limit permission")
            return None
        
        max_retries = self.config.get('Captcha', {}).get('max_retries', 3)
        retry_delay = self.config.get('Captcha', {}).get('retry_delay', 5)
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Solving reCAPTCHA v3 (attempt {attempt + 1}/{max_retries})")
                solution = self.solver.solve_recaptcha_v3(site_key, page_url, action, **kwargs)
                
                with self._lock:
                    self._stats['solved_count'] += 1
                    self._stats['last_solved_at'] = time.time()
                    # Add cost if available
                    if solution.cost is not None:
                        self._stats['total_cost'] += solution.cost
                
                self.logger.info("CAPTCHA solved successfully")
                return solution
                
            except CaptchaSolverBalanceError:
                self.logger.error("Insufficient balance for CAPTCHA solving")
                with self._lock:
                    self._stats['failed_count'] += 1
                return None
                
            except CaptchaSolverTimeoutError as e:
                self.logger.warning(f"CAPTCHA solving timed out (attempt {attempt + 1}): {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    self.logger.error("All CAPTCHA solving attempts timed out")
                    return None
                    
            except CaptchaSolverError as e:
                self.logger.warning(f"CAPTCHA solving failed (attempt {attempt + 1}): {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    self.logger.error("All CAPTCHA solving attempts failed")
                    return None
                    
            except Exception as e:
                self.logger.error(f"Unexpected error during CAPTCHA solving: {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                return None
        
        return None
    
    def solve_hcaptcha(self, site_key: str, page_url: str, **kwargs) -> Optional[CaptchaSolution]:
        """Solve hCaptcha with error handling and retry logic"""
        if not self.is_configured():
            self.logger.warning("CAPTCHA solver not configured")
            return None
        
        # Check rate limit
        if not self._wait_for_rate_limit():
            self.logger.error("Failed to acquire rate limit permission")
            return None
        
        max_retries = self.config.get('Captcha', {}).get('max_retries', 3)
        retry_delay = self.config.get('Captcha', {}).get('retry_delay', 5)
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Solving hCaptcha (attempt {attempt + 1}/{max_retries})")
                solution = self.solver.solve_hcaptcha(site_key, page_url, **kwargs)
                
                with self._lock:
                    self._stats['solved_count'] += 1
                    self._stats['last_solved_at'] = time.time()
                    # Add cost if available
                    if solution.cost is not None:
                        self._stats['total_cost'] += solution.cost
                
                self.logger.info("CAPTCHA solved successfully")
                return solution
                
            except CaptchaSolverBalanceError:
                self.logger.error("Insufficient balance for CAPTCHA solving")
                with self._lock:
                    self._stats['failed_count'] += 1
                return None
                
            except CaptchaSolverTimeoutError as e:
                self.logger.warning(f"CAPTCHA solving timed out (attempt {attempt + 1}): {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    self.logger.error("All CAPTCHA solving attempts timed out")
                    return None
                    
            except CaptchaSolverError as e:
                self.logger.warning(f"CAPTCHA solving failed (attempt {attempt + 1}): {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    self.logger.error("All CAPTCHA solving attempts failed")
                    return None
                    
            except Exception as e:
                self.logger.error(f"Unexpected error during CAPTCHA solving: {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                return None
        
        return None
    
    def handle_job_rejection(self, job_data: Dict[str, Any]) -> bool:
        """Handle job rejection workflow that might require CAPTCHA solving"""
        if not self.is_configured():
            self.logger.warning("CAPTCHA solver not configured, cannot handle job rejection")
            return False
        
        # Check if this job type requires CAPTCHA solving
        rejection_reason = job_data.get('rejection_reason', '').lower()
        if 'captcha' not in rejection_reason and 'verification' not in rejection_reason:
            return False
        
        self.logger.info(f"Handling job rejection that requires CAPTCHA solving: {job_data.get('id')}")
        
        # Extract CAPTCHA details from job data
        captcha_type = job_data.get('captcha_type', 'recaptcha_v2').lower()
        site_key = job_data.get('site_key')
        page_url = job_data.get('page_url')
        
        if not site_key or not page_url:
            self.logger.error("Missing CAPTCHA details in job data")
            return False
        
        # Solve the CAPTCHA
        solution = None
        if captcha_type in ['recaptcha_v2', 'recaptcha']:
            solution = self.solve_recaptcha_v2(site_key, page_url)
        elif captcha_type in ['recaptcha_v3']:
            action = job_data.get('captcha_action', 'verify')
            solution = self.solve_recaptcha_v3(site_key, page_url, action)
        elif captcha_type in ['hcaptcha']:
            solution = self.solve_hcaptcha(site_key, page_url)
        else:
            self.logger.warning(f"Unsupported CAPTCHA type: {captcha_type}")
            return False
        
        if solution is None:
            self.logger.error("Failed to solve CAPTCHA for job rejection")
            return False
        
        # Submit the solution back to the job system
        # This would be implemented based on the specific job system API
        try:
            self._submit_captcha_solution(job_data, solution)
            self.logger.info("CAPTCHA solution submitted successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to submit CAPTCHA solution: {e}")
            return False
    
    def _submit_captcha_solution(self, job_data: Dict[str, Any], solution: CaptchaSolution):
        """Submit CAPTCHA solution to the job system (to be implemented based on API)"""
        # This is a placeholder implementation
        # In a real implementation, this would make API calls to submit the solution
        job_id = job_data.get('id')
        self.logger.info(f"Submitting CAPTCHA solution for job {job_id}")
        
        # Example API call (uncomment and modify as needed):
        # response = requests.post(
        #     f"https://api.gengo.com/jobs/{job_id}/captcha",
        #     headers={"Authorization": f"Bearer {self.api_token}"},
        #     json={"solution": solution.solution}
        # )
        # response.raise_for_status()

    def _ensure_solver(self):
        """Ensure the solver is initialized (alias for _initialize_solver)"""
        if self.solver is None:
            self._initialize_solver()

    def log_stats(self):
        """Log CAPTCHA solving statistics"""
        stats = self.get_stats()
        self.logger.info("CAPTCHA solver statistics:")
        self.logger.info(f"  Solved: {stats['solved_count']}")
        self.logger.info(f"  Failed: {stats['failed_count']}")
        self.logger.info(f"  Total cost: ${stats['total_cost']:.2f}")
        self.logger.info(f"  Success rate: {stats['solved_count'] / max(1, stats['solved_count'] + stats['failed_count']) * 100:.1f}%")
        if stats['last_solved_at']:
            self.logger.info(f"  Last solved: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stats['last_solved_at']))}")