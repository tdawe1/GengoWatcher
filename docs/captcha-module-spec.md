# Captcha Solving Module Specification

## Module Overview
The captcha solving module provides automated captcha solving capabilities for the GengoWatcher application, enabling automatic job rejection based on user-defined criteria.

## Module Structure
```
src/gengowatcher/
├── captcha/
│   ├── __init__.py
│   ├── solver.py          # Abstract base class and factory
│   ├── twocaptcha.py      # 2Captcha implementation
│   ├── anticaptcha.py     # Anti-Captcha implementation
│   ├── config.py          # Configuration management
│   ├── exceptions.py      # Custom exceptions
│   └── job_rejection.py   # Job rejection logic
```

## Core Components

### 1. CaptchaSolver Interface (solver.py)
```python
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import asyncio

class CaptchaSolver(ABC):
    """Abstract base class for captcha solving services."""
    
    def __init__(self, api_key: str, timeout: int = 120):
        self.api_key = api_key
        self.timeout = timeout
    
    @abstractmethod
    async def solve_recaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve reCAPTCHA v2/v3.
        
        Args:
            site_key: The reCAPTCHA site key
            page_url: The URL where the captcha appears
            
        Returns:
            The solved captcha token, or None if failed
        """
        pass
    
    @abstractmethod
    async def solve_image_captcha(self, image_data: bytes) -> Optional[str]:
        """Solve image-based captcha.
        
        Args:
            image_data: The captcha image data
            
        Returns:
            The solved captcha text, or None if failed
        """
        pass
    
    @abstractmethod
    async def get_balance(self) -> float:
        """Get account balance.
        
        Returns:
            Account balance in USD
        """
        pass
    
    @abstractmethod
    async def report_bad_solution(self, captcha_id: str) -> bool:
        """Report incorrectly solved captcha.
        
        Args:
            captcha_id: The ID of the captcha solution to report
            
        Returns:
            True if report was successful, False otherwise
        """
        pass

class CaptchaSolverFactory:
    """Factory for creating captcha solver instances."""
    
    _solvers = {
        '2captcha': 'gengowatcher.captcha.twocaptcha.TwoCaptchaSolver',
        'anticaptcha': 'gengowatcher.captcha.anticaptcha.AntiCaptchaSolver'
    }
    
    @classmethod
    def create_solver(cls, provider: str, api_key: str, timeout: int = 120) -> CaptchaSolver:
        """Create a captcha solver instance.
        
        Args:
            provider: The captcha service provider name
            api_key: The API key for the service
            timeout: Timeout in seconds for solving operations
            
        Returns:
            A CaptchaSolver instance
            
        Raises:
            ValueError: If provider is not supported
        """
        if provider not in cls._solvers:
            raise ValueError(f"Unsupported captcha provider: {provider}")
        
        # Dynamic import to avoid hard dependencies
        module_path, class_name = cls._solvers[provider].rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        solver_class = getattr(module, class_name)
        return solver_class(api_key, timeout)
```

### 2. 2Captcha Implementation (twocaptcha.py)
```python
import aiohttp
import asyncio
import json
from typing import Optional
from .solver import CaptchaSolver

class TwoCaptchaSolver(CaptchaSolver):
    """2Captcha service implementation."""
    
    BASE_URL = "https://2captcha.com"
    
    async def solve_recaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve reCAPTCHA v2/v3 using 2Captcha service."""
        # Implementation details for 2Captcha API
        pass
    
    async def solve_image_captcha(self, image_data: bytes) -> Optional[str]:
        """Solve image-based captcha using 2Captcha service."""
        # Implementation details for 2Captcha API
        pass
    
    async def get_balance(self) -> float:
        """Get account balance from 2Captcha."""
        # Implementation details for 2Captcha API
        pass
    
    async def report_bad_solution(self, captcha_id: str) -> bool:
        """Report incorrectly solved captcha to 2Captcha."""
        # Implementation details for 2Captcha API
        pass
```

### 3. Configuration Management (config.py)
```python
from ..config import AppConfig
from typing import Optional

class CaptchaConfig:
    """Manages captcha-related configuration."""
    
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config
    
    @property
    def enabled(self) -> bool:
        """Check if captcha solving is enabled."""
        return self.app_config.get("Captcha", "enabled")
    
    @property
    def provider(self) -> str:
        """Get the configured captcha provider."""
        return self.app_config.get("Captcha", "provider")
    
    @property
    def api_key(self) -> str:
        """Get the API key for the captcha service."""
        return self.app_config.get("Captcha", "api_key")
    
    @property
    def timeout(self) -> int:
        """Get the timeout for captcha solving operations."""
        return self.app_config.get("Captcha", "timeout")
    
    @property
    def retry_attempts(self) -> int:
        """Get the number of retry attempts for failed operations."""
        return self.app_config.get("Captcha", "retry_attempts")
    
    @property
    def min_balance(self) -> float:
        """Get the minimum account balance required."""
        return self.app_config.get("Captcha", "min_balance")
    
    def validate(self) -> tuple[bool, Optional[str]]:
        """Validate captcha configuration.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self.enabled:
            return True, None
            
        if not self.provider:
            return False, "Captcha provider not configured"
            
        if not self.api_key:
            return False, "Captcha API key not configured"
            
        return True, None
```

### 4. Custom Exceptions (exceptions.py)
```python
class CaptchaError(Exception):
    """Base exception for captcha-related errors."""
    pass

class CaptchaServiceError(CaptchaError):
    """Error from captcha service provider."""
    pass

class CaptchaTimeoutError(CaptchaError):
    """Timeout while waiting for captcha solution."""
    pass

class InsufficientBalanceError(CaptchaError):
    """Insufficient balance in captcha service account."""
    pass

class InvalidApiKeyError(CaptchaError):
    """Invalid API key provided."""
    pass
```

### 5. Job Rejection Logic (job_rejection.py)
```python
import asyncio
import logging
from typing import Optional
from .solver import CaptchaSolverFactory
from .config import CaptchaConfig
from .exceptions import CaptchaError, InsufficientBalanceError

class JobRejectionManager:
    """Manages automatic job rejection with captcha solving."""
    
    def __init__(self, captcha_config: CaptchaConfig, logger: logging.Logger):
        self.captcha_config = captcha_config
        self.logger = logger
        self.solver: Optional[CaptchaSolver] = None
        self._initialize_solver()
    
    def _initialize_solver(self):
        """Initialize the captcha solver if configured."""
        if not self.captcha_config.enabled:
            return
            
        try:
            self.solver = CaptchaSolverFactory.create_solver(
                self.captcha_config.provider,
                self.captcha_config.api_key,
                self.captcha_config.timeout
            )
            self.logger.info(f"Captcha solver initialized: {self.captcha_config.provider}")
        except Exception as e:
            self.logger.error(f"Failed to initialize captcha solver: {e}")
            self.solver = None
    
    async def reject_job(self, job_id: int, reason: str = "auto_rejected") -> bool:
        """Reject a job with automated captcha solving.
        
        Args:
            job_id: The ID of the job to reject
            reason: The reason for rejection
            
        Returns:
            True if job was successfully rejected, False otherwise
        """
        if not self.solver:
            self.logger.warning("Captcha solver not available, cannot reject job")
            return False
            
        # Check account balance
        try:
            balance = await self.solver.get_balance()
            if balance < self.captcha_config.min_balance:
                raise InsufficientBalanceError(
                    f"Account balance (${balance}) below minimum (${self.captcha_config.min_balance})"
                )
        except CaptchaError as e:
            self.logger.error(f"Failed to check captcha balance: {e}")
            return False
            
        # Extract captcha from Gengo rejection page
        # (Implementation would depend on Gengo's specific rejection flow)
        captcha_data = await self._extract_captcha_from_job(job_id)
        if not captcha_data:
            self.logger.error(f"Failed to extract captcha for job {job_id}")
            return False
            
        # Solve captcha
        try:
            solution = await self._solve_captcha(captcha_data)
            if not solution:
                self.logger.error(f"Failed to solve captcha for job {job_id}")
                return False
        except CaptchaError as e:
            self.logger.error(f"Captcha solving failed for job {job_id}: {e}")
            return False
            
        # Submit rejection with solved captcha
        success = await self._submit_rejection(job_id, solution, reason)
        if success:
            self.logger.info(f"Successfully rejected job {job_id}")
        else:
            self.logger.error(f"Failed to reject job {job_id}")
            
        return success
    
    async def _extract_captcha_from_job(self, job_id: int) -> Optional[dict]:
        """Extract captcha data from a job rejection page.
        
        Args:
            job_id: The ID of the job
            
        Returns:
            Dictionary with captcha data, or None if extraction failed
        """
        # Implementation would depend on Gengo's specific rejection flow
        pass
    
    async def _solve_captcha(self, captcha_data: dict) -> Optional[str]:
        """Solve the captcha using the configured service.
        
        Args:
            captcha_data: Dictionary with captcha data
            
        Returns:
            The solved captcha solution, or None if failed
        """
        # Implementation for captcha solving based on captcha type
        pass
    
    async def _submit_rejection(self, job_id: int, captcha_solution: str, reason: str) -> bool:
        """Submit job rejection with solved captcha.
        
        Args:
            job_id: The ID of the job to reject
            captcha_solution: The solved captcha
            reason: The reason for rejection
            
        Returns:
            True if rejection was successful, False otherwise
        """
        # Implementation for submitting rejection to Gengo
        pass
```

## Integration Points

### 1. Configuration Integration (config.py)
Add new section to DEFAULT_CONFIG:
```python
"DEFAULT_CONFIG": {
    # ... existing sections ...
    "Captcha": {
        "enabled": False,
        "provider": "2captcha",
        "api_key": "",
        "timeout": 120,
        "retry_attempts": 3,
        "min_balance": 0.10,
    },
    "JobRejection": {
        "auto_reject_enabled": False,
        "reject_below_reward": 0.0,
        "reject_languages": "",
    }
}
```

### 2. Watcher Integration (watcher.py)
Modify `_process_new_job` method to include auto-rejection logic:
```python
def _process_new_job(self, job_id, title, reward, url, source):
    # ... existing code ...
    
    # Check if job meets rejection criteria
    if self._should_auto_reject_job(reward, title):
        asyncio.create_task(self._auto_reject_job(job_id, reward))
        return
    
    # ... existing code ...

def _should_auto_reject_job(self, reward, title) -> bool:
    """Check if job should be automatically rejected."""
    # Implementation based on user configuration
    pass

async def _auto_reject_job(self, job_id, reward):
    """Automatically reject job if captcha solving is configured."""
    # Implementation using JobRejectionManager
    pass
```

### 3. Main Application Integration (main.py)
Initialize captcha components:
```python
# In main() function
from .captcha.config import CaptchaConfig
from .captcha.job_rejection import JobRejectionManager

# After config and state initialization
captcha_config = CaptchaConfig(config)
job_rejection_manager = JobRejectionManager(captcha_config, log)

# Pass to watcher
watcher = GengoWatcher(config=config, state=state, logger=log, 
                      job_rejection_manager=job_rejection_manager)
```

## Testing Strategy

### Unit Tests
1. Test `CaptchaSolverFactory` creation logic
2. Test configuration validation
3. Test error handling scenarios
4. Mock service provider APIs for integration testing

### Integration Tests
1. Test end-to-end captcha solving workflow
2. Test job rejection flow with mock Gengo responses
3. Test provider switching functionality
4. Test retry logic and timeout handling

### Mock Implementations
Create mock implementations for testing without actual service calls:
```python
class MockCaptchaSolver(CaptchaSolver):
    """Mock implementation for testing."""
    
    async def solve_recaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        # Return mock solution
        return "mock_solution_12345"
    
    async def solve_image_captcha(self, image_data: bytes) -> Optional[str]:
        # Return mock solution
        return "mock_text"
    
    async def get_balance(self) -> float:
        # Return mock balance
        return 5.00
    
    async def report_bad_solution(self, captcha_id: str) -> bool:
        # Return mock success
        return True
```