import time
import threading
from collections import deque


class RateLimiter:
    """Simple rate limiter to prevent exceeding API request limits"""
    
    def __init__(self, max_requests: int = 60, time_window: int = 60):
        """
        Initialize rate limiter
        
        Args:
            max_requests: Maximum number of requests allowed
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        self.lock = threading.Lock()
    
    def acquire(self) -> bool:
        """
        Try to acquire permission to make a request
        
        Returns:
            bool: True if request is allowed, False if rate limited
        """
        with self.lock:
            current_time = time.time()
            
            # Remove old requests outside the time window
            while self.requests and self.requests[0] <= current_time - self.time_window:
                self.requests.popleft()
            
            # Check if we're within the limit
            if len(self.requests) < self.max_requests:
                self.requests.append(current_time)
                return True
            else:
                return False
    
    def wait_time(self) -> float:
        """
        Calculate how long to wait before making the next request
        
        Returns:
            float: Time to wait in seconds, 0 if no wait needed
        """
        with self.lock:
            if len(self.requests) < self.max_requests:
                return 0
            
            # Calculate wait time based on the oldest request
            current_time = time.time()
            oldest_request = self.requests[0]
            return max(0, oldest_request + self.time_window - current_time)
    
    def wait_and_acquire(self) -> bool:
        """
        Wait if necessary and then try to acquire permission
        
        Returns:
            bool: True if request is allowed, False if there was an error
        """
        wait_time = self.wait_time()
        if wait_time > 0:
            time.sleep(wait_time)
        
        return self.acquire()
    
    def get_current_rate(self) -> float:
        """
        Get current request rate
        
        Returns:
            float: Requests per second in the current time window
        """
        with self.lock:
            current_time = time.time()
            
            # Remove old requests outside the time window
            while self.requests and self.requests[0] <= current_time - self.time_window:
                self.requests.popleft()
            
            return len(self.requests) / self.time_window