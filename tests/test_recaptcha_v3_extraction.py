"""
Unit tests for reCAPTCHA v3 site key and action extraction
"""

import pytest
from unittest.mock import Mock, patch
from bs4 import BeautifulSoup
import sys
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gengowatcher.job_acceptance import JobAcceptanceEngine
from gengowatcher.config import AppConfig


class TestRecaptchaV3Extraction:
    """Test cases for reCAPTCHA v3 extraction methods"""
    
    def setup_method(self):
        """Set up test fixtures"""
        # Create a mock config to avoid file system dependencies
        self.config = Mock()
        self.config.get.return_value = "test_value"
        self.config.getboolean.return_value = True
        self.config.getint.return_value = 30
        self.config.getfloat.return_value = 1.0
        self.logger = Mock()
        self.engine = JobAcceptanceEngine(self.config, self.logger)
    
    def test_extract_recaptcha_v3_site_key_from_data_attribute(self):
        """Test extraction of site key from data attribute"""
        html = """
        <html>
            <body>
                <div class="g-recaptcha" data-sitekey="FAKE_TEST_SITE_KEY_FOR_UNIT_TESTS_ONLY"></div>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        site_key = self.engine._extract_recaptcha_v3_site_key(soup)
        assert site_key == "FAKE_TEST_SITE_KEY_FOR_UNIT_TESTS_ONLY"
    
    def test_extract_recaptcha_v3_site_key_from_script_execute(self):
        """Test extraction of site key from grecaptcha.execute call"""
        html = """
        <html>
            <body>
                <script>
                    grecaptcha.execute('FAKE_TEST_SITE_KEY_FOR_UNIT_TESTS_ONLY', {action: 'job_acceptance'}).then(function(token) {
                        // Handle token
                    });
                </script>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        site_key = self.engine._extract_recaptcha_v3_site_key(soup)
        assert site_key == "FAKE_TEST_SITE_KEY_FOR_UNIT_TESTS_ONLY"
    
    def test_extract_recaptcha_v3_site_key_from_script_ready(self):
        """Test extraction of site key from grecaptcha.ready call"""
        html = """
        <html>
            <body>
                <script>
                    grecaptcha.ready(function() {
                        grecaptcha.execute('FAKE_TEST_SITE_KEY_FOR_UNIT_TESTS_ONLY', {action: 'job_acceptance'}).then(function(token) {
                            // Handle token
                        });
                    });
                </script>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        site_key = self.engine._extract_recaptcha_v3_site_key(soup)
        assert site_key == "FAKE_TEST_SITE_KEY_FOR_UNIT_TESTS_ONLY"
    
    def test_extract_recaptcha_v3_site_key_from_site_key_variable(self):
        """Test extraction of site key from recaptcha_site_key variable"""
        html = """
        <html>
            <body>
                <script>
                    var recaptcha_site_key = 'FAKE_TEST_SITE_KEY_FOR_UNIT_TESTS_ONLY';
                    // Other code
                </script>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        site_key = self.engine._extract_recaptcha_v3_site_key(soup)
        assert site_key == "FAKE_TEST_SITE_KEY_FOR_UNIT_TESTS_ONLY"
    
    def test_extract_recaptcha_v3_site_key_not_found(self):
        """Test behavior when site key is not found"""
        html = """
        <html>
            <body>
                <div>No reCAPTCHA here</div>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        site_key = self.engine._extract_recaptcha_v3_site_key(soup)
        assert site_key is None
    
    def test_extract_recaptcha_v3_action_from_execute_call(self):
        """Test extraction of action from grecaptcha.execute call"""
        html = """
        <html>
            <body>
                <script>
                    grecaptcha.execute('FAKE_TEST_SITE_KEY_FOR_UNIT_TESTS_ONLY', {action: 'job_acceptance'}).then(function(token) {
                        // Handle token
                    });
                </script>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        action = self.engine._extract_recaptcha_v3_action(soup)
        assert action == "job_acceptance"
    
    def test_extract_recaptcha_v3_action_from_object(self):
        """Test extraction of action from action property"""
        html = """
        <html>
            <body>
                <script>
                    var recaptchaParams = {
                        action: 'submit_job'
                    };
                </script>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        action = self.engine._extract_recaptcha_v3_action(soup)
        assert action == "submit_job"
    
    def test_extract_recaptcha_v3_action_not_found(self):
        """Test behavior when action is not found"""
        html = """
        <html>
            <body>
                <div>No action here</div>
            </body>
        </html>
        """
        soup = BeautifulSoup(html, 'html.parser')
        action = self.engine._extract_recaptcha_v3_action(soup)
        assert action is None


if __name__ == "__main__":
    pytest.main([__file__])