import time
import json
import logging
import threading
import requests
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

class CaptchaServiceType(Enum):
    TWO_CAPTCHA = "2captcha"
    ANTI_CAPTCHA = "anti-captcha"

@dataclass
class CaptchaSolution:
    """Represents a solved CAPTCHA"""
    captcha_id: str
    solution: str
    solved_at: float
    cost: Optional[float] = None

class CaptchaType(Enum):
    """Supported CAPTCHA types"""
    RECAPTCHA_V2 = "recaptcha_v2"
    RECAPTCHA_V3 = "recaptcha_v3"
    HCAPTCHA = "hcaptcha"


@dataclass
class CaptchaTask:
    """Represents a CAPTCHA solving task"""
    task_id: str
    captcha_type: CaptchaType
    site_key: str
    page_url: str
    created_at: float
    action: Optional[str] = None  # For reCAPTCHA v3
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the task to a dictionary representation"""
        return {
            "task_id": self.task_id,
            "captcha_type": self.captcha_type.value,
            "site_key": self.site_key,
            "page_url": self.page_url,
            "created_at": self.created_at,
            "action": self.action
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CaptchaTask':
        """Create a task from a dictionary representation"""
        return cls(
            task_id=data["task_id"],
            captcha_type=CaptchaType(data["captcha_type"]),
            site_key=data["site_key"],
            page_url=data["page_url"],
            created_at=data["created_at"],
            action=data.get("action")
        )


class CaptchaSolverError(Exception):
    """Base exception for CAPTCHA solver errors"""
    pass

class CaptchaSolverAPIError(CaptchaSolverError):
    """Exception for API-related errors"""
    pass

class CaptchaSolverBalanceError(CaptchaSolverError):
    """Exception for insufficient balance"""
    pass

class CaptchaSolverTimeoutError(CaptchaSolverError):
    """Exception for timeout during solving"""
    pass


class BaseCaptchaSolver(ABC):
    """Abstract base class for CAPTCHA solving services"""
    
    def __init__(self, api_key: str, logger: logging.Logger = None):
        self.api_key = api_key
        self.logger = logger or logging.getLogger(__name__)
        
        # Configure session with connection pooling
        self.session = requests.Session()
        
        # Configure adapter with connection pooling
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=20,  # Number of connection pools to cache
            pool_maxsize=50,      # Maximum number of connections to save in the pool
            max_retries=3         # Retry failed requests up to 3 times
        )
        
        # Mount adapter for both HTTP and HTTPS
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        # Set default timeouts
        self.default_timeout = (10, 30)  # (connection timeout, read timeout)
        
        self._balance = None
        self._balance_lock = threading.Lock()
        self._last_balance_check = 0
        self._balance_cache_ttl = 300  # 5 minutes
    
    def _log_event(self, level: str, message: str, **kwargs):
        """Log events with structured data"""
        log_func = getattr(self.logger, level)
        if kwargs:
            log_func(message, extra=kwargs)
        else:
            log_func(message)
    
    @abstractmethod
    def get_service_name(self) -> str:
        """Return the service name"""
        pass
    
    @abstractmethod
    def get_balance(self) -> float:
        """Get account balance"""
        pass
    
    @abstractmethod
    def solve_recaptcha_v2(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        """Solve reCAPTCHA v2"""
        pass
    
    @abstractmethod
    def solve_recaptcha_v3(self, site_key: str, page_url: str, action: str = "verify", **kwargs) -> CaptchaSolution:
        """Solve reCAPTCHA v3"""
        pass
    
    @abstractmethod
    def solve_hcaptcha(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        """Solve hCaptcha"""
        pass
    
    def _make_request(self, method: str, url: str, timeout: tuple = None, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with error handling and timeout support"""
        # Use provided timeout or default timeout
        request_timeout = timeout or self.default_timeout
        
        try:
            response = self.session.request(method, url, timeout=request_timeout, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout as e:
            raise CaptchaSolverAPIError(f"API request timed out: {str(e)}")
        except requests.exceptions.RequestException as e:
            raise CaptchaSolverAPIError(f"API request failed: {str(e)}")
        except json.JSONDecodeError as e:
            raise CaptchaSolverAPIError(f"Invalid JSON response: {str(e)}")
    
    
    @abstractmethod
    def _check_result(self, task_id: str) -> Dict[str, Any]:
        """Check CAPTCHA solving result"""
        pass
    
    def close(self):
        """Close the HTTP session and clean up resources"""
        if hasattr(self, 'session') and self.session:
            self.session.close()


class TwoCaptchaSolver(BaseCaptchaSolver):
    """2Captcha service implementation"""
    
    BASE_URL = "https://2captcha.com"
    
    def get_service_name(self) -> str:
        return "2Captcha"
    
    def get_balance(self) -> float:
        """Get account balance"""
        current_time = time.time()
        with self._balance_lock:
            # Return cached balance if still valid
            if self._balance is not None and (current_time - self._last_balance_check) < self._balance_cache_ttl:
                return self._balance
            
            try:
                response = self._make_request(
                    'GET',
                    f'{self.BASE_URL}/res.php',
                    timeout=(10, 15),  # Shorter timeout for balance check
                    params={
                        'key': self.api_key,
                        'action': 'getbalance',
                        'json': 1
                    }
                )
                
                if response.get('status') == 1:
                    balance = float(response.get('request', 0))
                    self._balance = balance
                    self._last_balance_check = current_time
                    return balance
                else:
                    raise CaptchaSolverAPIError(f"Failed to get balance: {response.get('request')}")
            except Exception as e:
                self.logger.error(f"Error getting 2Captcha balance: {e}")
                return 0.0
    
    def solve_recaptcha_v2(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        """Solve reCAPTCHA v2"""
        start_time = time.time()
        
        # Check balance first
        balance = self.get_balance()
        if balance <= 0:
            self.logger.warning("Insufficient balance for CAPTCHA solving", extra={
                'service': self.get_service_name(),
                'captcha_type': 'recaptcha_v2',
                'balance': balance
            })
            raise CaptchaSolverBalanceError("Insufficient balance")
        
        self.logger.debug("Submitting reCAPTCHA v2", extra={
            'service': self.get_service_name(),
            'site_key': site_key,
            'page_url': page_url
        })
        
        # Submit CAPTCHA
        response = self._make_request(
            'POST',
            f'{self.BASE_URL}/in.php',
            timeout=(10, 30),
            data={
                'key': self.api_key,
                'method': 'userrecaptcha',
                'googlekey': site_key,
                'pageurl': page_url,
                'json': 1,
                **kwargs
            }
        )
        
        if response.get('status') != 1:
            error_msg = response.get('request', 'Unknown error')
            self.logger.error("Failed to submit reCAPTCHA v2", extra={
                'service': self.get_service_name(),
                'error': error_msg
            })
            raise CaptchaSolverAPIError(f"Failed to submit CAPTCHA: {error_msg}")
        
        task_id = response.get('request')
        submit_time = time.time() - start_time
        
        self.logger.info("Submitted reCAPTCHA v2 task", extra={
            'service': self.get_service_name(),
            'task_id': task_id,
            'submit_time': round(submit_time, 3)
        })
        
        # Poll for result
        poll_start_time = time.time()
        try:
            result = self._poll_for_result(task_id)
            poll_time = time.time() - poll_start_time
            
            solution = result.get('request')
            
            # Get cost if available
            cost = None
            if 'cost' in result:
                try:
                    cost = float(result['cost'])
                except (ValueError, TypeError):
                    pass
            
            total_time = time.time() - start_time
            
            self.logger.info("Successfully solved reCAPTCHA v2", extra={
                'service': self.get_service_name(),
                'task_id': task_id,
                'solution_length': len(solution) if solution else 0,
                'cost': cost,
                'submit_time': round(submit_time, 3),
                'poll_time': round(poll_time, 3),
                'total_time': round(total_time, 3)
            })
            
            return CaptchaSolution(
                captcha_id=task_id,
                solution=solution,
                solved_at=time.time(),
                cost=cost
            )
        except Exception as e:
            poll_time = time.time() - poll_start_time
            total_time = time.time() - start_time
            
            self.logger.error("Failed to solve reCAPTCHA v2", extra={
                'service': self.get_service_name(),
                'task_id': task_id,
                'error': str(e),
                'submit_time': round(submit_time, 3),
                'poll_time': round(poll_time, 3),
                'total_time': round(total_time, 3)
            })
            raise
    
    def solve_recaptcha_v3(self, site_key: str, page_url: str, action: str = "verify", **kwargs) -> CaptchaSolution:
        """Solve reCAPTCHA v3"""
        start_time = time.time()
        
        # Check balance first
        balance = self.get_balance()
        if balance <= 0:
            self._log_event('warning', "Insufficient balance for CAPTCHA solving", 
                           service=self.get_service_name(), 
                           captcha_type='recaptcha_v3', 
                           balance=balance)
            raise CaptchaSolverBalanceError("Insufficient balance")
        
        self._log_event('debug', "Submitting reCAPTCHA v3", 
                       service=self.get_service_name(), 
                       site_key=site_key, 
                       page_url=page_url, 
                       action=action)
        
        # Submit CAPTCHA
        response = self._make_request(
            'POST',
            f'{self.BASE_URL}/in.php',
            timeout=(10, 30),
            data={
                'key': self.api_key,
                'method': 'userrecaptcha',
                'version': 'v3',
                'googlekey': site_key,
                'pageurl': page_url,
                'action': action,
                'json': 1,
                **kwargs
            }
        )
        
        if response.get('status') != 1:
            error_msg = response.get('request', 'Unknown error')
            self._log_event('error', "Failed to submit reCAPTCHA v3", 
                           service=self.get_service_name(), 
                           error=error_msg)
            raise CaptchaSolverAPIError(f"Failed to submit CAPTCHA: {error_msg}")
        
        task_id = response.get('request')
        submit_time = time.time() - start_time
        
        self._log_event('info', "Submitted reCAPTCHA v3 task", 
                       service=self.get_service_name(), 
                       task_id=task_id, 
                       submit_time=round(submit_time, 3))
        
        # Poll for result
        poll_start_time = time.time()
        try:
            result = self._poll_for_result(task_id)
            poll_time = time.time() - poll_start_time
            
            solution = result.get('request')
            
            # Get cost if available
            cost = None
            if 'cost' in result:
                try:
                    cost = float(result['cost'])
                except (ValueError, TypeError):
                    pass
            
            total_time = time.time() - start_time
            
            self._log_event('info', "Successfully solved reCAPTCHA v3", 
                           service=self.get_service_name(), 
                           task_id=task_id, 
                           solution_length=len(solution) if solution else 0, 
                           cost=cost, 
                           submit_time=round(submit_time, 3), 
                           poll_time=round(poll_time, 3), 
                           total_time=round(total_time, 3))
            
            return CaptchaSolution(
                captcha_id=task_id,
                solution=solution,
                solved_at=time.time(),
                cost=cost
            )
        except Exception as e:
            poll_time = time.time() - poll_start_time
            total_time = time.time() - start_time
            
            self._log_event('error', "Failed to solve reCAPTCHA v3", 
                           service=self.get_service_name(), 
                           task_id=task_id, 
                           error=str(e), 
                           submit_time=round(submit_time, 3), 
                           poll_time=round(poll_time, 3), 
                           total_time=round(total_time, 3))
            raise
    
    def solve_hcaptcha(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        """Solve hCaptcha"""
        start_time = time.time()
        
        # Check balance first
        balance = self.get_balance()
        if balance <= 0:
            self._log_event('warning', "Insufficient balance for CAPTCHA solving", 
                           service=self.get_service_name(), 
                           captcha_type='hcaptcha', 
                           balance=balance)
            raise CaptchaSolverBalanceError("Insufficient balance")
        
        self._log_event('debug', "Submitting hCaptcha", 
                       service=self.get_service_name(), 
                       site_key=site_key, 
                       page_url=page_url)
        
        # Submit CAPTCHA
        response = self._make_request(
            'POST',
            f'{self.BASE_URL}/in.php',
            timeout=(10, 30),
            data={
                'key': self.api_key,
                'method': 'hcaptcha',
                'sitekey': site_key,
                'pageurl': page_url,
                'json': 1,
                **kwargs
            }
        )
        
        if response.get('status') != 1:
            error_msg = response.get('request', 'Unknown error')
            self._log_event('error', "Failed to submit hCaptcha", 
                           service=self.get_service_name(), 
                           error=error_msg)
            raise CaptchaSolverAPIError(f"Failed to submit CAPTCHA: {error_msg}")
        
        task_id = response.get('request')
        submit_time = time.time() - start_time
        
        self._log_event('info', "Submitted hCaptcha task", 
                       service=self.get_service_name(), 
                       task_id=task_id, 
                       submit_time=round(submit_time, 3))
        
        # Poll for result
        poll_start_time = time.time()
        try:
            result = self._poll_for_result(task_id)
            poll_time = time.time() - poll_start_time
            
            solution = result.get('request')
            
            # Get cost if available
            cost = None
            if 'cost' in result:
                try:
                    cost = float(result['cost'])
                except (ValueError, TypeError):
                    pass
            
            total_time = time.time() - start_time
            
            self._log_event('info', "Successfully solved hCaptcha", 
                           service=self.get_service_name(), 
                           task_id=task_id, 
                           solution_length=len(solution) if solution else 0, 
                           cost=cost, 
                           submit_time=round(submit_time, 3), 
                           poll_time=round(poll_time, 3), 
                           total_time=round(total_time, 3))
            
            return CaptchaSolution(
                captcha_id=task_id,
                solution=solution,
                solved_at=time.time(),
                cost=cost
            )
        except Exception as e:
            poll_time = time.time() - poll_start_time
            total_time = time.time() - start_time
            
            self._log_event('error', "Failed to solve hCaptcha", 
                           service=self.get_service_name(), 
                           task_id=task_id, 
                           error=str(e), 
                           submit_time=round(submit_time, 3), 
                           poll_time=round(poll_time, 3), 
                           total_time=round(total_time, 3))
            raise
    
    def _check_result(self, task_id: str) -> Dict[str, Any]:
        """Check CAPTCHA solving result"""
        return self._make_request(
            'GET',
            f'{self.BASE_URL}/res.php',
            timeout=(5, 15),  # Shorter timeout for polling
            params={
                'key': self.api_key,
                'action': 'get',
                'id': task_id,
                'json': 1
            }
        )

    def _poll_for_result(self, task_id: str, polling_interval: float = 5, max_wait_time: int = 300) -> Dict[str, Any]:
        """
        Poll for 2Captcha solving result with adaptive polling.

        2Captcha API response format:
        - status: 0 (processing) or 1 (ready)
        - request: Contains either "CAPCHA_NOT_READY" (when processing) or the solution token (when ready)
        - When status=0 and request starts with "ERROR_", it's an error

        Args:
            task_id: The CAPTCHA task ID
            polling_interval: Initial polling interval in seconds
            max_wait_time: Maximum time to wait for solution

        Returns:
            Dict containing the solution

        Raises:
            CaptchaSolverError: If solving fails
            CaptchaSolverTimeoutError: If timeout is reached
        """
        start_time = time.time()
        current_polling_interval = polling_interval
        max_polling_interval = 30  # Maximum polling interval

        while time.time() - start_time < max_wait_time:
            result = self._check_result(task_id)
            status = result.get('status')
            request = result.get('request', '')

            if status == 1:
                # CAPTCHA is ready, solution is in 'request' field
                return result
            elif status == 0:
                if request == 'CAPCHA_NOT_READY':
                    # Still processing, continue polling
                    pass
                elif request.startswith('ERROR_'):
                    # Error occurred
                    raise CaptchaSolverError(f"CAPTCHA solving failed: {request}")
                else:
                    # Unexpected response format
                    self.logger.warning(f"Unexpected 2Captcha response: status={status}, request={request}")
            else:
                # Invalid status
                raise CaptchaSolverError(f"Invalid 2Captcha response status: {status}")

            # Adaptive polling with exponential backoff
            time.sleep(current_polling_interval)

            # Increase polling interval exponentially, but cap it at max_polling_interval
            current_polling_interval = min(current_polling_interval * 1.5, max_polling_interval)

        raise CaptchaSolverTimeoutError("CAPTCHA solving timed out")


class AntiCaptchaSolver(BaseCaptchaSolver):
    """Anti-Captcha service implementation"""
    
    BASE_URL = "https://api.anti-captcha.com"
    
    def get_service_name(self) -> str:
        return "Anti-Captcha"
    
    def get_balance(self) -> float:
        """Get account balance"""
        current_time = time.time()
        with self._balance_lock:
            # Return cached balance if still valid
            if self._balance is not None and (current_time - self._last_balance_check) < self._balance_cache_ttl:
                return self._balance
            
            try:
                response = self._make_request(
                    'POST',
                    f'{self.BASE_URL}/getBalance',
                    json={'clientKey': self.api_key},
                    timeout=(10, 15)  # Shorter timeout for balance check
                )
                
                if response.get('errorId') == 0:
                    balance = float(response.get('balance', 0))
                    self._balance = balance
                    self._last_balance_check = current_time
                    return balance
                else:
                    raise CaptchaSolverAPIError(f"Failed to get balance: {response.get('errorDescription')}")
            except Exception as e:
                self.logger.error(f"Error getting Anti-Captcha balance: {e}")
                return 0.0
    
    def solve_recaptcha_v2(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        """Solve reCAPTCHA v2"""
        start_time = time.time()
        
        # Check balance first
        balance = self.get_balance()
        if balance <= 0:
            self._log_event('warning', "Insufficient balance for CAPTCHA solving", 
                           service=self.get_service_name(), 
                           captcha_type='recaptcha_v2', 
                           balance=balance)
            raise CaptchaSolverBalanceError("Insufficient balance")
        
        self._log_event('debug', "Submitting reCAPTCHA v2", 
                       service=self.get_service_name(), 
                       site_key=site_key, 
                       page_url=page_url)
        
        # Submit CAPTCHA
        task_data = {
            "clientKey": self.api_key,
            "task": {
                "type": "NoCaptchaTaskProxyless",
                "websiteURL": page_url,
                "websiteKey": site_key,
                **kwargs
            },
            "softId": 0
        }
        
        response = self._make_request(
            'POST',
            f'{self.BASE_URL}/createTask',
            timeout=(10, 30),
            json=task_data
        )
        
        if response.get('errorId') != 0:
            error_msg = response.get('errorDescription', 'Unknown error')
            self._log_event('error', "Failed to submit reCAPTCHA v2", 
                           service=self.get_service_name(), 
                           error=error_msg)
            raise CaptchaSolverAPIError(f"Failed to submit CAPTCHA: {error_msg}")
        
        task_id = response.get('taskId')
        submit_time = time.time() - start_time
        
        self._log_event('info', "Submitted reCAPTCHA v2 task to Anti-Captcha", 
                       service=self.get_service_name(), 
                       task_id=task_id, 
                       submit_time=round(submit_time, 3))
        
        # Poll for result
        poll_start_time = time.time()
        try:
            result = self._poll_for_result(task_id)
            poll_time = time.time() - poll_start_time
            
            solution = result.get('solution', {}).get('gRecaptchaResponse')
            
            # Get cost if available
            cost = None
            if 'cost' in result:
                try:
                    cost = float(result['cost'])
                except (ValueError, TypeError):
                    pass
            
            total_time = time.time() - start_time
            
            self._log_event('info', "Successfully solved reCAPTCHA v2", 
                           service=self.get_service_name(), 
                           task_id=task_id, 
                           solution_length=len(solution) if solution else 0, 
                           cost=cost, 
                           submit_time=round(submit_time, 3), 
                           poll_time=round(poll_time, 3), 
                           total_time=round(total_time, 3))
            
            return CaptchaSolution(
                captcha_id=str(task_id),
                solution=solution,
                solved_at=time.time(),
                cost=cost
            )
        except Exception as e:
            poll_time = time.time() - poll_start_time
            total_time = time.time() - start_time
            
            self._log_event('error', "Failed to solve reCAPTCHA v2", 
                           service=self.get_service_name(), 
                           task_id=task_id, 
                           error=str(e), 
                           submit_time=round(submit_time, 3), 
                           poll_time=round(poll_time, 3), 
                           total_time=round(total_time, 3))
            raise
    
    def solve_recaptcha_v3(self, site_key: str, page_url: str, action: str = "verify", **kwargs) -> CaptchaSolution:
        """Solve reCAPTCHA v3"""
        # Check balance first
        balance = self.get_balance()
        if balance <= 0:
            raise CaptchaSolverBalanceError("Insufficient balance")
        
        # Submit CAPTCHA
        task_data = {
            "clientKey": self.api_key,
            "task": {
                "type": "RecaptchaV3TaskProxyless",
                "websiteURL": page_url,
                "websiteKey": site_key,
                "pageAction": action,
                **kwargs
            },
            "softId": 0
        }
        
        response = self._make_request(
            'POST',
            f'{self.BASE_URL}/createTask',
            timeout=(10, 30),
            json=task_data
        )
        
        if response.get('errorId') != 0:
            raise CaptchaSolverAPIError(f"Failed to submit CAPTCHA: {response.get('errorDescription')}")
        
        task_id = response.get('taskId')
        self.logger.info(f"Submitted reCAPTCHA v3 task: {task_id}")
        
        # Poll for result
        result = self._poll_for_result(task_id)
        solution = result.get('solution', {}).get('gRecaptchaResponse')
        
        # Get cost if available
        cost = None
        if 'cost' in result:
            try:
                cost = float(result['cost'])
            except (ValueError, TypeError):
                pass
        
        return CaptchaSolution(
            captcha_id=str(task_id),
            solution=solution,
            solved_at=time.time(),
            cost=cost
        )
    
    def solve_hcaptcha(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        """Solve hCaptcha"""
        # Check balance first
        balance = self.get_balance()
        if balance <= 0:
            raise CaptchaSolverBalanceError("Insufficient balance")
        
        # Submit CAPTCHA
        task_data = {
            "clientKey": self.api_key,
            "task": {
                "type": "HCaptchaTaskProxyless",
                "websiteURL": page_url,
                "websiteKey": site_key,
                **kwargs
            },
            "softId": 0
        }
        
        response = self._make_request(
            'POST',
            f'{self.BASE_URL}/createTask',
            timeout=(10, 30),
            json=task_data
        )
        
        if response.get('errorId') != 0:
            raise CaptchaSolverAPIError(f"Failed to submit CAPTCHA: {response.get('errorDescription')}")
        
        task_id = response.get('taskId')
        self.logger.info(f"Submitted hCaptcha task: {task_id}")
        
        # Poll for result
        result = self._poll_for_result(task_id)
        solution = result.get('solution', {}).get('gRecaptchaResponse')
        
        # Get cost if available
        cost = None
        if 'cost' in result:
            try:
                cost = float(result['cost'])
            except (ValueError, TypeError):
                pass
        
        return CaptchaSolution(
            captcha_id=str(task_id),
            solution=solution,
            solved_at=time.time(),
            cost=cost
        )
    
    def _check_result(self, task_id: str) -> Dict[str, Any]:
        """Check CAPTCHA solving result"""
        response = self._make_request(
            'POST',
            f'{self.BASE_URL}/getTaskResult',
            timeout=(5, 15),  # Shorter timeout for polling
            json={
                'clientKey': self.api_key,
                'taskId': task_id
            }
        )
        return response
    
    def _poll_for_result(self, task_id: str, polling_interval: float = 5, max_wait_time: int = 300) -> Dict[str, Any]:
        """
        Poll for Anti-Captcha solving result with adaptive polling.

        Anti-Captcha API response format:
        - errorId: 0 (success) or non-zero (error)
        - status: "processing" or "ready"
        - solution.gRecaptchaResponse: Contains the solution token (when ready)
        - errorDescription: Error message when errorId != 0

        Args:
            task_id: The CAPTCHA task ID
            polling_interval: Initial polling interval in seconds
            max_wait_time: Maximum time to wait for solution

        Returns:
            Dict containing the solution

        Raises:
            CaptchaSolverError: If solving fails
            CaptchaSolverTimeoutError: If timeout is reached
        """
        start_time = time.time()
        current_polling_interval = polling_interval
        max_polling_interval = 30  # Maximum polling interval

        while time.time() - start_time < max_wait_time:
            result = self._check_result(task_id)
            error_id = result.get('errorId', -1)

            if error_id == 0:
                # No error, check status
                status = result.get('status')
                if status == 'ready':
                    # CAPTCHA is ready, solution is in result.solution.gRecaptchaResponse
                    return result
                elif status == 'processing':
                    # Still processing, continue polling
                    pass
                else:
                    # Unexpected status
                    raise CaptchaSolverError(f"Anti-Captcha returned unexpected status: {status}")
            else:
                # Error occurred
                error_desc = result.get('errorDescription', 'Unknown error')
                raise CaptchaSolverError(f"Anti-Captcha error: {error_desc}")

            # Adaptive polling with exponential backoff
            time.sleep(current_polling_interval)

            # Increase polling interval exponentially, but cap it at max_polling_interval
            current_polling_interval = min(current_polling_interval * 1.5, max_polling_interval)

        raise CaptchaSolverTimeoutError("CAPTCHA solving timed out")