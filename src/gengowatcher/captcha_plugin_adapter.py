"""
Adapter for integrating existing CAPTCHA solvers with the plugin architecture
"""

import logging
from typing import Dict, Any
from .captcha_plugin import CaptchaServicePlugin
from .captcha_solver import TwoCaptchaSolver, AntiCaptchaSolver, CaptchaSolution, CaptchaTask


class TwoCaptchaSolverPluginAdapter(CaptchaServicePlugin):
    """Adapter for TwoCaptchaSolver to work with plugin interface"""
    
    def __init__(self, config: Dict[str, Any], logger: logging.Logger = None):
        self.service_identifier = "2captcha"
        self.logger = logger or logging.getLogger(__name__)
        
        # Create the actual solver instance
        # Note: API key will be handled by the parent class
        super().__init__(config, logger)
        self._solver = None
    
    def _initialize_plugin(self):
        """Initialize the actual TwoCaptcha solver"""
        if self.api_key:
            self._solver = TwoCaptchaSolver(self.api_key, self.logger)
    
    def get_service_name(self) -> str:
        """Return the service name"""
        if self._solver:
            return self._solver.get_service_name()
        return "2Captcha"
    
    def get_balance(self) -> float:
        """Get account balance"""
        if self._solver:
            return self._solver.get_balance()
        return 0.0
    
    def solve_recaptcha_v2(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        """Solve reCAPTCHA v2"""
        if self._solver:
            return self._solver.solve_recaptcha_v2(site_key, page_url, **kwargs)
        raise Exception("Solver not initialized")
    
    def solve_recaptcha_v3(self, site_key: str, page_url: str, action: str = "verify", **kwargs) -> CaptchaSolution:
        """Solve reCAPTCHA v3"""
        if self._solver:
            return self._solver.solve_recaptcha_v3(site_key, page_url, action, **kwargs)
        raise Exception("Solver not initialized")
    
    def solve_hcaptcha(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        """Solve hCaptcha"""
        if self._solver:
            return self._solver.solve_hcaptcha(site_key, page_url, **kwargs)
        raise Exception("Solver not initialized")
    
    def _check_result(self, task_id: str) -> Dict[str, Any]:
        """Check CAPTCHA solving result"""
        if self._solver:
            return self._solver._check_result(task_id)
        raise Exception("Solver not initialized")
    
    def close(self):
        """Close the HTTP session and clean up resources"""
        if self._solver:
            self._solver.close()


class AntiCaptchaSolverPluginAdapter(CaptchaServicePlugin):
    """Adapter for AntiCaptchaSolver to work with plugin interface"""
    
    def __init__(self, config: Dict[str, Any], logger: logging.Logger = None):
        self.service_identifier = "anti-captcha"
        self.logger = logger or logging.getLogger(__name__)
        
        # Create the actual solver instance
        super().__init__(config, logger)
        self._solver = None
    
    def _initialize_plugin(self):
        """Initialize the actual AntiCaptcha solver"""
        if self.api_key:
            self._solver = AntiCaptchaSolver(self.api_key, self.logger)
    
    def get_service_name(self) -> str:
        """Return the service name"""
        if self._solver:
            return self._solver.get_service_name()
        return "Anti-Captcha"
    
    def get_balance(self) -> float:
        """Get account balance"""
        if self._solver:
            return self._solver.get_balance()
        return 0.0
    
    def solve_recaptcha_v2(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        """Solve reCAPTCHA v2"""
        if self._solver:
            return self._solver.solve_recaptcha_v2(site_key, page_url, **kwargs)
        raise Exception("Solver not initialized")
    
    def solve_recaptcha_v3(self, site_key: str, page_url: str, action: str = "verify", **kwargs) -> CaptchaSolution:
        """Solve reCAPTCHA v3"""
        if self._solver:
            return self._solver.solve_recaptcha_v3(site_key, page_url, action, **kwargs)
        raise Exception("Solver not initialized")
    
    def solve_hcaptcha(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        """Solve hCaptcha"""
        if self._solver:
            return self._solver.solve_hcaptcha(site_key, page_url, **kwargs)
        raise Exception("Solver not initialized")
    
    def _check_result(self, task_id: str) -> Dict[str, Any]:
        """Check CAPTCHA solving result"""
        if self._solver:
            return self._solver._check_result(task_id)
        raise Exception("Solver not initialized")
    
    def close(self):
        """Close the HTTP session and clean up resources"""
        if self._solver:
            self._solver.close()