"""
Browser Automation Package for GengoWatcher

DEPRECATED: This Selenium-based automation is deprecated in favor of the new
Playwright-based WebsiteMonitor. See website_monitor.py for the replacement.

This module is kept for backwards compatibility but will be removed in a future version.
"""

import warnings

warnings.warn(
    "browser_automation (Selenium) is deprecated. Use WebsiteMonitor (Playwright) instead. "
    "Set WebsiteMonitor.enabled=true in config.ini and run 'playwright install chromium'.",
    DeprecationWarning,
    stacklevel=2,
)

from .engine import BrowserAutomationEngine

__all__ = [
    "BrowserAutomationEngine"
]
