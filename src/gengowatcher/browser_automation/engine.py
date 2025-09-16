"""
Browser Automation Engine for GengoWatcher
Handles automatic job acceptance through browser automation with CAPTCHA solving capabilities.
"""

import time
import random
import logging
import json
import threading
from typing import Dict, Any, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


class BrowserAutomationEngine:
    """Browser automation engine for job acceptance"""
    
    def __init__(self, config, logger, captcha_solver=None):
        self.config = config
        self.logger = logger
        self.captcha_solver = captcha_solver
        self.driver = None
        self.logger.info("BrowserAutomationEngine initialized")
    
    def _initialize_driver(self) -> webdriver.Chrome:
        """Initialize Chrome WebDriver with appropriate options"""
        if self.driver:
            return self.driver
            
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # Add user agent if configured
        user_agent = self.config.get("Watcher", {}).get("user_agent")
        if user_agent:
            chrome_options.add_argument(f"--user-agent={user_agent}")
        
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.logger.info("Chrome WebDriver initialized successfully")
            return self.driver
        except Exception as e:
            self.logger.error(f"Failed to initialize Chrome WebDriver: {e}")
            raise
    
    def solve_recaptcha_v3_with_browser(self, site_key: str, page_url: str, action: str = "job_acceptance") -> Optional[str]:
        """
        Solve reCAPTCHA v3 using browser automation to execute the challenge.
        
        Args:
            site_key: reCAPTCHA v3 site key
            page_url: URL of the page where reCAPTCHA is used
            action: Action name for reCAPTCHA v3
            
        Returns:
            str: reCAPTCHA v3 token if successful, None otherwise
        """
        if not self.config.get("Captcha", {}).get("enable_browser_automation_fallback", False):
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
