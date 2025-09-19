import logging
import threading
import time
from typing import Optional, Dict, Any
from .captcha_plugin import CaptchaServicePluginFactory
from .captcha_solver import (
    BaseCaptchaSolver, 
    CaptchaServiceType,
    CaptchaSolution,
    CaptchaSolverError,
    CaptchaSolverBalanceError,
    CaptchaSolverTimeoutError
)
from .secure_storage import SecureKeyStorage
from .rate_limiter import RateLimiter
from .captcha_monitor import CAPTCHAServiceMonitor


class CaptchaSolverManager:
    """Manages CAPTCHA solving services and integration with GengoWatcher"""
    
    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """Initializes the CaptchaSolverManager.

        Args:
            config (Dict[str, Any]): Configuration dictionary containing CAPTCHA settings.
            logger (logging.Logger): Logger instance for logging messages.
        """
        self.config = config
        self.logger = logger
        self.solver: Optional[BaseCaptchaSolver] = None
        self._lock = threading.RLock()
        self._stats = {
            'solved_count': 0,
            'failed_count': 0,
            'total_cost': 0.0,
            'last_solved_at': None,
            'captcha_type_stats': {
                'recaptcha_v2': {'solved': 0, 'failed': 0, 'total_cost': 0.0},
                'recaptcha_v3': {'solved': 0, 'failed': 0, 'total_cost': 0.0},
                'hcaptcha': {'solved': 0, 'failed': 0, 'total_cost': 0.0}
            },
            'service_stats': {},  # Will be populated with service-specific stats
            'solve_times': [],  # Store recent solve times for performance tracking
            'error_stats': {}  # Track error types and frequencies
        }
        self._rate_limiter = RateLimiter(
            max_requests=config.get('Captcha', {}).get('rate_limit', 60),
            time_window=config.get('Captcha', {}).get('rate_limit_window', 60)
        )
        self._storage = SecureKeyStorage(logger=self.logger)
        self.monitor = CAPTCHAServiceMonitor(logger=self.logger)
        self._initialize_solver()
    
    def reinitialize(self):
        """Reinitialize the CAPTCHA solver with current configuration"""
        self.logger.info("Reinitializing CAPTCHA solver")
        # Close existing solver
        self.close()
        # Reinitialize
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

            # Check for local solver
            if service_type == 'local':
                try:
                    from .local_captcha_solver import LocalCaptchaSolverManager
                    local_solver_manager = LocalCaptchaSolverManager(self.config, self.logger)
                    if local_solver_manager.is_supported():
                        # For now, we'll use the manager directly
                        # In a full implementation, we'd adapt it to the plugin interface
                        self.logger.info("Initialized local CAPTCHA solver")
                        # Store reference for local solving
                        self._local_solver_manager = local_solver_manager
                        # Initialize it
                        local_solver_manager.initialize()
                    else:
                        self.logger.warning("Local CAPTCHA solver not supported on this system")
                except ImportError:
                    self.logger.error("Local CAPTCHA solver module not found")
                return

            if not service_type:
                self.logger.info("CAPTCHA solver not configured")
                return
            
            # Use plugin factory to create solver
            self.solver = CaptchaServicePluginFactory.create_plugin(service_type, self.config, self.logger)
            
            if self.solver:
                self.logger.info(f"Initialized {self.solver.get_service_name()} solver via plugin system")
            else:
                self.logger.warning(f"Failed to initialize CAPTCHA solver for service: {service_type}")
                
        except Exception as e:
            self.logger.exception(f"Failed to initialize CAPTCHA solver: {e}")
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
            self.logger.exception(f"Failed to get balance: {e}")
            return 0.0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get CAPTCHA solving statistics"""
        with self._lock:
            # Return a copy of stats with computed values
            stats = self._stats.copy()
            # Add current rate information
            stats['current_rate'] = self._rate_limiter.get_current_rate()
            
            # Calculate additional computed statistics
            total_attempts = stats['solved_count'] + stats['failed_count']
            stats['success_rate'] = stats['solved_count'] / max(1, total_attempts) * 100 if total_attempts > 0 else 0.0
            
            # Calculate average solve times
            if stats['solve_times']:
                stats['avg_solve_time'] = sum(stats['solve_times']) / len(stats['solve_times'])
                stats['min_solve_time'] = min(stats['solve_times'])
                stats['max_solve_time'] = max(stats['solve_times'])
            else:
                stats['avg_solve_time'] = 0.0
                stats['min_solve_time'] = 0.0
                stats['max_solve_time'] = 0.0
            
            # Calculate service-specific statistics
            for service_name, service_stats in stats['service_stats'].items():
                service_total = service_stats['solved'] + service_stats['failed']
                service_stats['success_rate'] = service_stats['solved'] / max(1, service_total) * 100 if service_total > 0 else 0.0
                if service_stats['solve_times']:
                    service_stats['avg_solve_time'] = sum(service_stats['solve_times']) / len(service_stats['solve_times'])
                    service_stats['min_solve_time'] = min(service_stats['solve_times'])
                    service_stats['max_solve_time'] = max(service_stats['solve_times'])
                else:
                    service_stats['avg_solve_time'] = 0.0
                    service_stats['min_solve_time'] = 0.0
                    service_stats['max_solve_time'] = 0.0
            
            # Calculate CAPTCHA type statistics
            for captcha_type, type_stats in stats['captcha_type_stats'].items():
                type_total = type_stats['solved'] + type_stats['failed']
                type_stats['success_rate'] = type_stats['solved'] / max(1, type_total) * 100 if type_total > 0 else 0.0
            
            return stats
    
    def get_available_services(self) -> Dict[str, str]:
        """Get list of available CAPTCHA services"""
        return CaptchaServicePluginFactory.get_available_plugins()
    
    def _wait_for_rate_limit(self) -> bool:
        """Wait for rate limit clearance before proceeding with CAPTCHA solving.

        Returns:
            bool: True if rate limit is acquired, False otherwise.
        """
        wait_time = self._rate_limiter.wait_time()
        if wait_time > 0:
            self.logger.warning(f"Rate limit reached, waiting {wait_time:.2f} seconds")
            time.sleep(wait_time)
        
        return self._rate_limiter.acquire()
    
    def solve_image_captcha(self, image_path: str) -> Optional[CaptchaSolution]:
        """Solve an image-based CAPTCHA using local solver if available"""
        # Check if we have a local solver
        if hasattr(self, '_local_solver_manager') and self._local_solver_manager:
            try:
                return self._local_solver_manager.solve_image_captcha(image_path)
            except Exception as e:
                self.logger.exception(f"Error solving image CAPTCHA locally: {e}")
                return None
        else:
            self.logger.warning("Local CAPTCHA solver not available for image CAPTCHA solving")
            return None
    
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
        start_time = time.time()
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Solving reCAPTCHA v2 (attempt {attempt + 1}/{max_retries})")
                solution = self.solver.solve_recaptcha_v2(site_key, page_url, **kwargs)
                
                solve_time = time.time() - start_time
                
                with self._lock:
                    self._stats['solved_count'] += 1
                    self._stats['last_solved_at'] = time.time()
                    # Add cost if available
                    cost = solution.cost if solution.cost is not None else 0.0
                    self._stats['total_cost'] += cost
                    # Update CAPTCHA type stats
                    self._stats['captcha_type_stats']['recaptcha_v2']['solved'] += 1
                    self._stats['captcha_type_stats']['recaptcha_v2']['total_cost'] += cost
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['solved'] += 1
                    self._stats['service_stats'][service_name]['total_cost'] += cost
                    self._stats['service_stats'][service_name]['solve_times'].append(solve_time)
                    # Keep only last 100 solve times
                    if len(self._stats['service_stats'][service_name]['solve_times']) > 100:
                        self._stats['service_stats'][service_name]['solve_times'] = \
                            self._stats['service_stats'][service_name]['solve_times'][-100:]
                    # Store solve time for overall stats
                    self._stats['solve_times'].append(solve_time)
                    if len(self._stats['solve_times']) > 1000:
                        self._stats['solve_times'] = self._stats['solve_times'][-1000:]
                
                self.logger.info(f"CAPTCHA solved successfully in {solve_time:.2f}s")
                return solution
                
            except CaptchaSolverBalanceError:
                self.logger.error("Insufficient balance for CAPTCHA solving")
                with self._lock:
                    self._stats['failed_count'] += 1
                    self._stats['captcha_type_stats']['recaptcha_v2']['failed'] += 1
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['failed'] += 1
                    # Track error
                    error_type = "balance_error"
                    if error_type not in self._stats['error_stats']:
                        self._stats['error_stats'][error_type] = 0
                    self._stats['error_stats'][error_type] += 1
                return None
                
            except CaptchaSolverTimeoutError as e:
                self.logger.warning(f"CAPTCHA solving timed out (attempt {attempt + 1}): {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    self._stats['captcha_type_stats']['recaptcha_v2']['failed'] += 1
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['failed'] += 1
                    # Track error
                    error_type = "timeout_error"
                    if error_type not in self._stats['error_stats']:
                        self._stats['error_stats'][error_type] = 0
                    self._stats['error_stats'][error_type] += 1
                    
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    self.logger.error("All CAPTCHA solving attempts timed out")
                    return None
                    
            except CaptchaSolverError as e:
                self.logger.warning(f"CAPTCHA solving failed (attempt {attempt + 1}): {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    self._stats['captcha_type_stats']['recaptcha_v2']['failed'] += 1
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['failed'] += 1
                    # Track error
                    error_type = type(e).__name__
                    if error_type not in self._stats['error_stats']:
                        self._stats['error_stats'][error_type] = 0
                    self._stats['error_stats'][error_type] += 1
                    
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    self.logger.error("All CAPTCHA solving attempts failed")
                    return None

            except Exception as e:
                self.logger.exception(f"Unexpected error during CAPTCHA solving: {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    self._stats['captcha_type_stats']['recaptcha_v2']['failed'] += 1
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['failed'] += 1
                    # Track error
                    error_type = f"unexpected_{type(e).__name__}"
                    if error_type not in self._stats['error_stats']:
                        self._stats['error_stats'][error_type] = 0
                    self._stats['error_stats'][error_type] += 1
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
        start_time = time.time()
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Solving reCAPTCHA v3 (attempt {attempt + 1}/{max_retries})")
                solution = self.solver.solve_recaptcha_v3(site_key, page_url, action, **kwargs)
                
                solve_time = time.time() - start_time
                
                with self._lock:
                    self._stats['solved_count'] += 1
                    self._stats['last_solved_at'] = time.time()
                    # Add cost if available
                    cost = solution.cost if solution.cost is not None else 0.0
                    self._stats['total_cost'] += cost
                    # Update CAPTCHA type stats
                    self._stats['captcha_type_stats']['recaptcha_v3']['solved'] += 1
                    self._stats['captcha_type_stats']['recaptcha_v3']['total_cost'] += cost
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['solved'] += 1
                    self._stats['service_stats'][service_name]['total_cost'] += cost
                    self._stats['service_stats'][service_name]['solve_times'].append(solve_time)
                    # Keep only last 100 solve times
                    if len(self._stats['service_stats'][service_name]['solve_times']) > 100:
                        self._stats['service_stats'][service_name]['solve_times'] = \
                            self._stats['service_stats'][service_name]['solve_times'][-100:]
                    # Store solve time for overall stats
                    self._stats['solve_times'].append(solve_time)
                    if len(self._stats['solve_times']) > 1000:
                        self._stats['solve_times'] = self._stats['solve_times'][-1000:]
                
                self.logger.info(f"CAPTCHA solved successfully in {solve_time:.2f}s")
                return solution
                
            except CaptchaSolverBalanceError:
                self.logger.error("Insufficient balance for CAPTCHA solving")
                with self._lock:
                    self._stats['failed_count'] += 1
                    self._stats['captcha_type_stats']['recaptcha_v3']['failed'] += 1
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['failed'] += 1
                    # Track error
                    error_type = "balance_error"
                    if error_type not in self._stats['error_stats']:
                        self._stats['error_stats'][error_type] = 0
                    self._stats['error_stats'][error_type] += 1
                return None
                
            except CaptchaSolverTimeoutError as e:
                self.logger.warning(f"CAPTCHA solving timed out (attempt {attempt + 1}): {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    self._stats['captcha_type_stats']['recaptcha_v3']['failed'] += 1
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['failed'] += 1
                    # Track error
                    error_type = "timeout_error"
                    if error_type not in self._stats['error_stats']:
                        self._stats['error_stats'][error_type] = 0
                    self._stats['error_stats'][error_type] += 1
                    
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    self.logger.error("All CAPTCHA solving attempts timed out")
                    return None
                    
            except CaptchaSolverError as e:
                self.logger.warning(f"CAPTCHA solving failed (attempt {attempt + 1}): {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    self._stats['captcha_type_stats']['recaptcha_v3']['failed'] += 1
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['failed'] += 1
                    # Track error
                    error_type = type(e).__name__
                    if error_type not in self._stats['error_stats']:
                        self._stats['error_stats'][error_type] = 0
                    self._stats['error_stats'][error_type] += 1
                    
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    self.logger.error("All CAPTCHA solving attempts failed")
                    return None

            except Exception as e:
                self.logger.exception(f"Unexpected error during CAPTCHA solving: {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    self._stats['captcha_type_stats']['recaptcha_v3']['failed'] += 1
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['failed'] += 1
                    # Track error
                    error_type = f"unexpected_{type(e).__name__}"
                    if error_type not in self._stats['error_stats']:
                        self._stats['error_stats'][error_type] = 0
                    self._stats['error_stats'][error_type] += 1
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
        start_time = time.time()
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Solving hCaptcha (attempt {attempt + 1}/{max_retries})")
                solution = self.solver.solve_hcaptcha(site_key, page_url, **kwargs)
                
                solve_time = time.time() - start_time
                
                with self._lock:
                    self._stats['solved_count'] += 1
                    self._stats['last_solved_at'] = time.time()
                    # Add cost if available
                    cost = solution.cost if solution.cost is not None else 0.0
                    self._stats['total_cost'] += cost
                    # Update CAPTCHA type stats
                    self._stats['captcha_type_stats']['hcaptcha']['solved'] += 1
                    self._stats['captcha_type_stats']['hcaptcha']['total_cost'] += cost
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['solved'] += 1
                    self._stats['service_stats'][service_name]['total_cost'] += cost
                    self._stats['service_stats'][service_name]['solve_times'].append(solve_time)
                    # Keep only last 100 solve times
                    if len(self._stats['service_stats'][service_name]['solve_times']) > 100:
                        self._stats['service_stats'][service_name]['solve_times'] = \
                            self._stats['service_stats'][service_name]['solve_times'][-100:]
                    # Store solve time for overall stats
                    self._stats['solve_times'].append(solve_time)
                    if len(self._stats['solve_times']) > 1000:
                        self._stats['solve_times'] = self._stats['solve_times'][-1000:]
                
                self.logger.info(f"CAPTCHA solved successfully in {solve_time:.2f}s")
                return solution
                
            except CaptchaSolverBalanceError:
                self.logger.error("Insufficient balance for CAPTCHA solving")
                with self._lock:
                    self._stats['failed_count'] += 1
                    self._stats['captcha_type_stats']['hcaptcha']['failed'] += 1
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['failed'] += 1
                    # Track error
                    error_type = "balance_error"
                    if error_type not in self._stats['error_stats']:
                        self._stats['error_stats'][error_type] = 0
                    self._stats['error_stats'][error_type] += 1
                return None
                
            except CaptchaSolverTimeoutError as e:
                self.logger.warning(f"CAPTCHA solving timed out (attempt {attempt + 1}): {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    self._stats['captcha_type_stats']['hcaptcha']['failed'] += 1
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['failed'] += 1
                    # Track error
                    error_type = "timeout_error"
                    if error_type not in self._stats['error_stats']:
                        self._stats['error_stats'][error_type] = 0
                    self._stats['error_stats'][error_type] += 1
                    
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    self.logger.error("All CAPTCHA solving attempts timed out")
                    return None
                    
            except CaptchaSolverError as e:
                self.logger.warning(f"CAPTCHA solving failed (attempt {attempt + 1}): {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    self._stats['captcha_type_stats']['hcaptcha']['failed'] += 1
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['failed'] += 1
                    # Track error
                    error_type = type(e).__name__
                    if error_type not in self._stats['error_stats']:
                        self._stats['error_stats'][error_type] = 0
                    self._stats['error_stats'][error_type] += 1
                    
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    self.logger.error("All CAPTCHA solving attempts failed")
                    return None

            except Exception as e:
                self.logger.exception(f"Unexpected error during CAPTCHA solving: {e}")
                with self._lock:
                    self._stats['failed_count'] += 1
                    self._stats['captcha_type_stats']['hcaptcha']['failed'] += 1
                    # Update service stats
                    service_name = self.solver.get_service_name()
                    if service_name not in self._stats['service_stats']:
                        self._stats['service_stats'][service_name] = {'solved': 0, 'failed': 0, 'total_cost': 0.0, 'solve_times': []}
                    self._stats['service_stats'][service_name]['failed'] += 1
                    # Track error
                    error_type = f"unexpected_{type(e).__name__}"
                    if error_type not in self._stats['error_stats']:
                        self._stats['error_stats'][error_type] = 0
                    self._stats['error_stats'][error_type] += 1
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
            self.logger.exception(f"Failed to submit CAPTCHA solution: {e}")
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

    def log_stats(self):
        """Log CAPTCHA solving statistics"""
        stats = self.get_stats()
        self.logger.info("CAPTCHA solver statistics:")
        self.logger.info(f"  Solved: {stats['solved_count']}")
        self.logger.info(f"  Failed: {stats['failed_count']}")
        self.logger.info(f"  Success rate: {stats['success_rate']:.1f}%")
        self.logger.info(f"  Total cost: ${stats['total_cost']:.4f}")
        if stats['last_solved_at']:
            self.logger.info(f"  Last solved: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stats['last_solved_at']))}")
        
        # Log CAPTCHA type statistics
        self.logger.info("  CAPTCHA Type Statistics:")
        for captcha_type, type_stats in stats['captcha_type_stats'].items():
            self.logger.info(f"    {captcha_type}: Solved={type_stats['solved']}, Failed={type_stats['failed']}, "
                           f"Success Rate={type_stats['success_rate']:.1f}%, Cost=${type_stats['total_cost']:.4f}")
        
        # Log service statistics
        if stats['service_stats']:
            self.logger.info("  Service Statistics:")
            for service_name, service_stats in stats['service_stats'].items():
                self.logger.info(f"    {service_name}: Solved={service_stats['solved']}, Failed={service_stats['failed']}, "
                               f"Success Rate={service_stats['success_rate']:.1f}%, Cost=${service_stats['total_cost']:.4f}")
                if service_stats['solve_times']:
                    self.logger.info(f"      Solve Times: Avg={service_stats['avg_solve_time']:.2f}s, "
                                   f"Min={service_stats['min_solve_time']:.2f}s, Max={service_stats['max_solve_time']:.2f}s")
        
        # Log performance statistics
        if stats['solve_times']:
            self.logger.info(f"  Overall Performance: Avg={stats['avg_solve_time']:.2f}s, "
                           f"Min={stats['min_solve_time']:.2f}s, Max={stats['max_solve_time']:.2f}s")
        
        # Log error statistics
        if stats['error_stats']:
            self.logger.info("  Error Statistics:")
            for error_type, count in stats['error_stats'].items():
                self.logger.info(f"    {error_type}: {count}")
    
    def start_monitoring(self, interval: int = 300):
        """Start monitoring CAPTCHA service health and performance"""
        self.monitor.start_monitoring(self, interval)
    
    def stop_monitoring(self):
        """Stop monitoring CAPTCHA service health and performance"""
        self.monitor.stop_monitoring()