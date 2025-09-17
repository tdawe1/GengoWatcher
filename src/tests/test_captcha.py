import pytest
import os
import tempfile
from unittest.mock import Mock, patch
from gengowatcher.captcha_solver import CaptchaServiceType
from gengowatcher.captcha_manager import CaptchaSolverManager
from gengowatcher.secure_storage import SecureKeyStorage

class TestCaptchaManager:
    """Test CAPTCHA manager functionality"""
    
    def test_captcha_manager_initialization_no_config(self):
        """Test CAPTCHA manager initialization with no configuration"""
        config = {"Captcha": {"service": ""}}
        logger = Mock()
        
        manager = CaptchaSolverManager(config, logger)
        
        assert manager.is_configured() == False
        assert manager.get_balance() == 0.0
    
    def test_rate_limiter_basic_functionality(self):
        """Test rate limiter basic functionality"""
        from gengowatcher.rate_limiter import RateLimiter
        
        # Create a rate limiter with 3 requests per second
        limiter = RateLimiter(max_requests=3, time_window=1)
        
        # First 3 requests should be allowed
        assert limiter.acquire() == True
        assert limiter.acquire() == True
        assert limiter.acquire() == True
        
        # 4th request should be denied
        assert limiter.acquire() == False
        
        # Wait and try again
        import time
        time.sleep(1.1)
        assert limiter.acquire() == True

class TestSecureStorage:
    """Test secure storage functionality"""
    
    def test_secure_storage_store_and_retrieve(self):
        """Test storing and retrieving API keys"""
        # Create a temporary file for testing
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            storage_file = tmp_file.name
        
        try:
            # Create storage instance
            storage = SecureKeyStorage(storage_file=storage_file)
            
            # Store an API key
            service = "2captcha"
            api_key = "test_api_key_12345"
            
            assert storage.store_api_key(service, api_key) == True
            
            # Retrieve the API key
            retrieved_key = storage.retrieve_api_key(service)
            assert retrieved_key == api_key
            
            # Try to retrieve non-existent key
            assert storage.retrieve_api_key("nonexistent") == None
            
            # Delete the key
            assert storage.delete_api_key(service) == True
            
            # Try to retrieve deleted key
            assert storage.retrieve_api_key(service) == None
        finally:
            # Clean up
            if os.path.exists(storage_file):
                os.unlink(storage_file)
    
    def test_secure_storage_delete_nonexistent(self):
        """Test deleting a non-existent API key"""
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            storage_file = tmp_file.name
        
        try:
            storage = SecureKeyStorage(storage_file=storage_file)
            
            # Delete non-existent key should return True
            assert storage.delete_api_key("nonexistent") == True
        finally:
            if os.path.exists(storage_file):
                os.unlink(storage_file)