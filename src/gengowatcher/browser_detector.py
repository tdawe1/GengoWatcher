"""
Browser Detection Module for GengoWatcher

This module provides cross-platform browser detection functionality to dynamically
set User-Agent strings, preventing identification as GengoWatcher in HTTP requests.

Features:
- Detects installed browsers (Vivaldi, Chrome, Firefox) on Linux/Windows/macOS
- 7-day caching system to avoid repeated detection
- Priority system: manual override → system detection → generic fallback
- Cross-platform support with fallback mechanisms
"""

import json
import os
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Optional, Dict, Any


def _config_to_dict(config: Any) -> Dict[str, Any]:
    """Normalize AppConfig-like objects into the nested dict BrowserDetector expects."""
    if isinstance(config, dict):
        return config

    list_all = getattr(config, "list_all", None)
    if callable(list_all):
        try:
            config_dict = list_all()
        except Exception:
            config_dict = None
        if isinstance(config_dict, dict):
            return config_dict

    config_dict = getattr(config, "config", None)
    if isinstance(config_dict, dict):
        return config_dict

    return {}


def get_preferred_browser_user_agent(config: Any, logger=None) -> str:
    """Resolve the best browser-like User-Agent for an AppConfig-like object."""
    return BrowserDetector(_config_to_dict(config), logger).get_user_agent()


class BrowserDetector:
    """
    Detects and provides User-Agent strings for installed browsers.
    """

    def __init__(self, config: Dict[str, Any], logger=None):
        """
        Initialize browser detector.

        Args:
            config: Configuration dictionary containing browser settings
            logger: Logger instance for debugging
        """
        self.config = config
        self.logger = logger
        self.cache_file = Path.home() / ".gengowatcher" / "browser_cache.json"
        self.cache_duration = 7 * 24 * 60 * 60  # 7 days in seconds

        # Default user agent strings (fallback)
        self.default_ua = {
            "windows": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "linux": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "macos": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

    def get_user_agent(self) -> str:
        """
        Get the most appropriate User-Agent string.

        Priority: manual override → system detection → generic fallback

        Returns:
            User-Agent string for HTTP requests
        """
        # 0. Check for manual override in config
        manual_ua = self._get_manual_user_agent()
        if manual_ua:
            if self.logger:
                self.logger.debug(f"Using manually configured User-Agent: {manual_ua}")
            return manual_ua

        # 1. Check if browser detection is disabled - early return with fallback
        detect_ua_flag = self.config.get("Network", {}).get("detect_browser_ua", False)
        # Coerce string values to boolean (config may return "true"/"false" strings)
        if isinstance(detect_ua_flag, str):
            detect_ua_flag = detect_ua_flag.lower() in (
                "1",
                "true",
                "yes",
                "on",
                "enabled",
            )
        if not detect_ua_flag:
            if self.logger:
                self.logger.debug("Browser detection disabled, using fallback")
            return self._get_fallback_user_agent()

        # 2. Check cache first
        cached_ua = self._get_cached_user_agent()
        if cached_ua:
            if self.logger:
                self.logger.debug(f"Using cached User-Agent: {cached_ua}")
            return cached_ua

        # 3. Detect from system
        detected_ua = self._detect_browser_user_agent()
        if detected_ua:
            if self.logger:
                self.logger.debug(f"Using detected User-Agent: {detected_ua}")
            self._cache_user_agent(detected_ua)
            return detected_ua

        # 4. Fallback to platform default
        fallback_ua = self._get_fallback_user_agent()
        if self.logger:
            self.logger.debug(f"Using fallback User-Agent: {fallback_ua}")
        return fallback_ua

    def _get_manual_user_agent(self) -> Optional[str]:
        """
        Get manually configured User-Agent from config.

        Returns:
            Manual User-Agent string or None if not configured
        """
        network_config = self.config.get("Network", {})
        if not isinstance(network_config, dict):
            return None

        for key in ("browser_user_agent", "user_agent"):
            manual_ua = str(network_config.get(key, "") or "").strip()
            if manual_ua:
                return manual_ua

        return None

    def _get_cached_user_agent(self) -> Optional[str]:
        """
        Get User-Agent from cache if still valid.

        Returns:
            Cached User-Agent string or None if cache is invalid
        """
        if not self.cache_file.exists():
            return None

        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            # Check if cache is still valid
            if time.time() - cache_data.get("timestamp", 0) < self.cache_duration:
                return cache_data.get("user_agent")
        except (json.JSONDecodeError, KeyError, IOError) as e:
            if self.logger:
                self.logger.warning(f"Error reading browser cache: {e}")

        return None

    def _cache_user_agent(self, user_agent: str) -> None:
        """
        Cache the detected User-Agent.

        Args:
            user_agent: User-Agent string to cache
        """
        try:
            # Ensure cache directory exists
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)

            cache_data = {
                "timestamp": time.time(),
                "user_agent": user_agent,
                "platform": platform.system(),
            }

            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)

            if self.logger:
                self.logger.debug(
                    f"Cached User-Agent for {self.cache_duration} seconds"
                )

        except (IOError, OSError) as e:
            if self.logger:
                self.logger.warning(f"Error writing browser cache: {e}")

    def _detect_browser_user_agent(self) -> Optional[str]:
        """
        Detect browser User-Agent from installed browsers.

        Returns:
            Detected User-Agent string or None if detection fails
        """
        system = platform.system().lower()

        # Priority order: Vivaldi → Chrome → Firefox
        detectors = [self._detect_vivaldi, self._detect_chrome, self._detect_firefox]

        for detector in detectors:
            try:
                ua = detector(system)
                if ua:
                    return ua
            except Exception as e:
                if self.logger:
                    self.logger.debug(
                        f"Browser detection failed for {detector.__name__}: {e}"
                    )

        return None

    def _detect_vivaldi(self, system: str) -> Optional[str]:
        """
        Detect Vivaldi browser and return its User-Agent.

        Args:
            system: Operating system name (windows, linux, darwin)

        Returns:
            Vivaldi User-Agent string or None if not found
        """
        paths = {
            "windows": [
                r"C:\Users\%USERNAME%\AppData\Local\Vivaldi\Application\vivaldi.exe",
                r"C:\Program Files\Vivaldi\Application\vivaldi.exe",
                r"C:\Program Files (x86)\Vivaldi\Application\vivaldi.exe",
            ],
            "linux": [
                "/usr/bin/vivaldi",
                "/usr/local/bin/vivaldi",
                "/opt/vivaldi/vivaldi",
            ],
            "darwin": ["/Applications/Vivaldi.app/Contents/MacOS/Vivaldi"],
        }

        for path_pattern in paths.get(system, []):
            path = path_pattern.replace("%USERNAME%", os.getenv("USERNAME", ""))
            if os.path.exists(path):
                return self._extract_browser_version(path, "Vivaldi")

        return None

    def _detect_chrome(self, system: str) -> Optional[str]:
        """
        Detect Chrome browser and return its User-Agent.

        Args:
            system: Operating system name (windows, linux, darwin)

        Returns:
            Chrome User-Agent string or None if not found
        """
        paths = {
            "windows": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Users\%USERNAME%\AppData\Local\Google\Chrome\Application\chrome.exe",
            ],
            "linux": [
                "/usr/bin/google-chrome",
                "/usr/local/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/snap/bin/google-chrome",
            ],
            "darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
        }

        for path_pattern in paths.get(system, []):
            path = path_pattern.replace("%USERNAME%", os.getenv("USERNAME", ""))
            if os.path.exists(path):
                return self._extract_browser_version(path, "Chrome")

        return None

    def _detect_firefox(self, system: str) -> Optional[str]:
        """
        Detect Firefox browser and return its User-Agent.

        Args:
            system: Operating system name (windows, linux, darwin)

        Returns:
            Firefox User-Agent string or None if not found
        """
        paths = {
            "windows": [
                r"C:\Program Files\Mozilla Firefox\firefox.exe",
                r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
                r"C:\Users\%USERNAME%\AppData\Local\Mozilla Firefox\firefox.exe",
            ],
            "linux": [
                "/usr/bin/firefox",
                "/usr/local/bin/firefox",
                "/snap/bin/firefox",
            ],
            "darwin": ["/Applications/Firefox.app/Contents/MacOS/firefox"],
        }

        for path_pattern in paths.get(system, []):
            path = path_pattern.replace("%USERNAME%", os.getenv("USERNAME", ""))
            if os.path.exists(path):
                return self._extract_browser_version(path, "Firefox")

        return None

    def _extract_browser_version(
        self, browser_path: str, browser_name: str
    ) -> Optional[str]:
        """
        Extract browser version and construct User-Agent string.

        Args:
            browser_path: Path to browser executable
            browser_name: Name of browser (Chrome, Firefox, Vivaldi)

        Returns:
            User-Agent string or None if extraction fails
        """
        try:
            if browser_name in ["Chrome", "Vivaldi"]:
                version_arg = "--version"
            else:  # Firefox
                version_arg = (
                    "--version" if platform.system() != "Windows" else "-version"
                )

            result = subprocess.run(
                [browser_path, version_arg],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )

            version_output = result.stdout.strip() or result.stderr.strip()
            # Match 2-4 part version numbers (e.g., 131.0, 131.0.3, 131.0.3.1)
            version_match = re.search(r"(\d+\.\d+(?:\.\d+){0,2})", version_output)

            if version_match:
                version = version_match.group(1)
                return self._construct_user_agent(browser_name, version)

        except (
            subprocess.TimeoutExpired,
            subprocess.CalledProcessError,
            FileNotFoundError,
        ) as e:
            if self.logger:
                self.logger.debug(f"Failed to extract version for {browser_name}: {e}")

        return None

    def _construct_user_agent(self, browser_name: str, version: str) -> str:
        """
        Construct User-Agent string for browser.

        Args:
            browser_name: Name of browser
            version: Browser version

        Returns:
            User-Agent string
        """
        system = platform.system()
        arch = platform.machine()

        # Platform information
        if system == "Windows":
            platform_info = "Windows NT 10.0; Win64; x64"
        elif system == "Linux":
            platform_info = "X11; Linux x86_64"
        elif system == "Darwin":  # macOS
            mac_version = platform.mac_ver()[0] or "10.15.7"
            platform_info = f"Macintosh; Intel Mac OS X {mac_version.replace('.', '_')}"
        else:
            platform_info = f"{system} {arch}"

        # Construct User-Agent based on browser type
        if browser_name == "Chrome":
            return f"Mozilla/5.0 ({platform_info}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"
        elif browser_name == "Vivaldi":
            return f"Mozilla/5.0 ({platform_info}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36 Vivaldi/{version}"
        elif browser_name == "Firefox":
            return f"Mozilla/5.0 ({platform_info}; rv:{version}) Gecko/20100101 Firefox/{version}"
        else:
            # Fallback to Chrome-style UA
            return f"Mozilla/5.0 ({platform_info}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"

    def _get_fallback_user_agent(self) -> str:
        """
        Get platform-specific fallback User-Agent.

        Returns:
            Default User-Agent for current platform
        """
        system = platform.system().lower()
        # Normalize platform names to match default_ua keys
        platform_key = {"darwin": "macos"}.get(system, system)
        return self.default_ua.get(platform_key, self.default_ua["linux"])

    def clear_cache(self) -> None:
        """
        Clear the browser cache.
        """
        if self.cache_file.exists():
            try:
                self.cache_file.unlink()
                if self.logger:
                    self.logger.info("Browser cache cleared")
            except OSError as e:
                if self.logger:
                    self.logger.warning(f"Failed to clear browser cache: {e}")
