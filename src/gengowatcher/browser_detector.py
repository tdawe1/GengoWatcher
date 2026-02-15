"""
Browser Detector - Detect system browser and generate realistic user agents.

Detects the default browser on the system and generates appropriate user agent strings.
Supports cross-platform detection with fallbacks for reliability.
"""

import json
import os
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Optional


class BrowserDetector:
    """Detects browser information from system and generates user agents."""

    CACHE_FILE = Path.home() / ".gengowatcher" / "browser_cache.json"
    CACHE_DURATION = 7 * 24 * 60 * 60  # 7 days in seconds

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self._cached_user_agent = None
        self._cache_timestamp = 0

    def get_user_agent(self) -> str:
        """
        Get user agent string with priority order:
        1. Configured browser_user_agent (manual override)
        2. System default browser detection (if enabled)
        3. Generic browser fallback
        """
        try:
            # Priority 1: Configured override
            configured_ua = self.config.get("Network", "browser_user_agent")
            if configured_ua and configured_ua.strip():
                self.logger.debug(f"Using configured browser user agent")
                return configured_ua.strip()

            # Priority 2: System detection (if enabled)
            if self.config.getboolean("Network", "detect_browser_ua", fallback=False):
                self.logger.debug(f"Auto-detection enabled, checking cache...")
                cached_ua = self._get_cached_user_agent()
                if cached_ua:
                    return cached_ua

                detected_ua = self._detect_system_browser_ua()
                if detected_ua:
                    self._cache_user_agent(detected_ua)
                    return detected_ua

            # Priority 3: Generic fallback
            self.logger.debug(f"Using generic browser user agent fallback")
            return self._get_generic_browser_ua()

        except Exception as e:
            self.logger.error(f"Error in get_user_agent: {e}")
            return self._get_generic_browser_ua()

    def _get_cached_user_agent(self) -> Optional[str]:
        """Get cached user agent if still valid."""
        try:
            if not self.CACHE_FILE.exists():
                return None

            with open(self.CACHE_FILE, "r") as f:
                cache_data = json.load(f)

            user_agent = cache_data.get("user_agent")
            cached_at = cache_data.get("cached_at", 0)

            if user_agent and (time.time() - cached_at) < self.CACHE_DURATION:
                self.logger.debug(f"Using cached user agent: {user_agent[:50]}...")
                return user_agent

        except Exception as e:
            self.logger.debug(f"Error reading cache: {e}")

        return None

    def _cache_user_agent(self, user_agent: str):
        """Cache user agent for long-term storage."""
        try:
            # Ensure cache directory exists
            self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

            cache_data = {
                "user_agent": user_agent,
                "cached_at": time.time(),
            }

            with open(self.CACHE_FILE, "w") as f:
                json.dump(cache_data, f, indent=2)

            self.logger.debug(f"Cached user agent: {user_agent[:50]}...")

        except Exception as e:
            self.logger.debug(f"Error caching user agent: {e}")

    def _detect_system_browser_ua(self) -> Optional[str]:
        """Detect system default browser and build realistic user agent."""
        try:
            system = platform.system()

            if system == "Linux":
                return self._detect_linux_browser()
            elif system == "Windows":
                return self._detect_windows_browser()
            elif system == "Darwin":  # macOS
                return self._detect_macos_browser()

        except Exception as e:
            self.logger.debug(f"Error detecting system browser: {e}")

        return None

    def _detect_linux_browser(self) -> Optional[str]:
        """Detect browser on Linux systems."""
        try:
            # Try xdg-settings first (most reliable)
            result = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True,
                text=True,
                check=True,
            )
            browser_info = result.stdout.strip().lower()
            self.logger.debug(f"Detected Linux default browser: {browser_info}")

            if "vivaldi" in browser_info:
                return self._get_vivaldi_ua()
            elif "chrome" in browser_info or "chromium" in browser_info:
                return self._get_chrome_ua()
            elif "firefox" in browser_info:
                return self._get_firefox_ua()

        except (subprocess.CalledProcessError, FileNotFoundError):
            self.logger.debug("xdg-settings not available, trying alternative methods")

        # Try to detect by checking common browser executables
        browsers = [
            ("vivaldi", self._get_vivaldi_ua),
            ("google-chrome", self._get_chrome_ua),
            ("chromium-browser", self._get_chromium_ua),
            ("firefox", self._get_firefox_ua),
        ]

        for browser_name, ua_func in browsers:
            try:
                subprocess.run(
                    [browser_name, "--version"],
                    capture_output=True,
                    check=True,
                )
                return ua_func()
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue

        return None

    def _detect_windows_browser(self) -> Optional[str]:
        """Detect browser on Windows systems."""
        try:
            import winreg

            # Check default browser in Windows Registry
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
            ) as key:
                prog_id = winreg.QueryValueEx(key, "ProgId")[0]

            browser_map = {
                "Vivaldi": self._get_vivaldi_ua,
                "Chrome": self._get_chrome_ua,
                "Firefox": self._get_firefox_ua,
            }

            for browser_name, ua_func in browser_map.items():
                if browser_name.lower() in prog_id.lower():
                    return ua_func()

        except (ImportError, OSError):
            self.logger.debug("Windows registry detection not available")

        return None

    def _detect_macos_browser(self) -> Optional[str]:
        """Detect browser on macOS systems."""
        try:
            result = subprocess.run(
                ["defaults", "read", "com.apple.LaunchServices", "LSHandlers"],
                capture_output=True,
                text=True,
                check=True,
            )
            handlers = result.stdout.lower()

            if "vivaldi" in handlers:
                return self._get_vivaldi_ua()
            elif "chrome" in handlers:
                return self._get_chrome_ua()
            elif "firefox" in handlers:
                return self._get_firefox_ua()

        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return None

    def _get_vivaldi_ua(self) -> str:
        """Get Vivaldi user agent string."""
        try:
            system = platform.system()

            # Try to get Vivaldi version
            version = self._get_vivaldi_version()
            if version:
                chrome_version = self._get_chrome_version_from_vivaldi(version)
            else:
                chrome_version = "126.0.0.0"
                version = "7.8.3925.62"

            if system == "Linux":
                return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36 Vivaldi/{version}"
            elif system == "Windows":
                return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36 Vivaldi/{version}"
            elif system == "Darwin":
                return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36 Vivaldi/{version}"

        except Exception as e:
            self.logger.debug(f"Error getting Vivaldi UA: {e}")

        # Fallback Vivaldi UA
        return "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Vivaldi/7.8.3925.62"

    def _get_chrome_ua(self) -> str:
        """Get Chrome user agent string."""
        try:
            version = self._get_chrome_version()
            if version:
                return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"
        except:
            pass

        return "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

    def _get_chromium_ua(self) -> str:
        """Get Chromium user agent string."""
        try:
            version = self._get_chromium_version()
            if version:
                return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"
        except:
            pass

        return "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

    def _get_firefox_ua(self) -> str:
        """Get Firefox user agent string."""
        try:
            version = self._get_firefox_version()
            if version:
                return f"Mozilla/5.0 (X11; Linux x86_64; rv:{version}) Gecko/20100101 Firefox/{version}"
        except:
            pass

        return "Mozilla/5.0 (X11; Linux x86_64; rv:115.0) Gecko/20100101 Firefox/115.0"

    def _get_generic_browser_ua(self) -> str:
        """Return a realistic generic browser user agent."""
        # Use a modern Chrome user agent as fallback
        return "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

    def _get_vivaldi_version(self) -> Optional[str]:
        """Extract Vivaldi version."""
        try:
            result = subprocess.run(
                ["vivaldi", "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            version_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", result.stdout)
            if version_match:
                return version_match.group(1)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return None

    def _get_chrome_version(self) -> Optional[str]:
        """Extract Chrome version."""
        try:
            result = subprocess.run(
                ["google-chrome", "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            version_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", result.stdout)
            if version_match:
                return version_match.group(1)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return None

    def _get_chromium_version(self) -> Optional[str]:
        """Extract Chromium version."""
        try:
            result = subprocess.run(
                ["chromium-browser", "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            version_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", result.stdout)
            if version_match:
                return version_match.group(1)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return None

    def _get_firefox_version(self) -> Optional[str]:
        """Extract Firefox version."""
        try:
            result = subprocess.run(
                ["firefox", "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            version_match = re.search(r"(\d+\.\d+)", result.stdout)
            if version_match:
                return version_match.group(1)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return None

    def _get_chrome_version_from_vivaldi(self, vivaldi_version: str) -> str:
        """
        Map Vivaldi version to Chrome version.
        Vivaldi uses Chrome as its rendering engine.
        """
        # Simplified mapping for common Vivaldi versions
        vivaldi_to_chrome = {
            "7.8.3925.62": "126.0.6478.183",
            "7.7.3622.50": "125.0.6422.142",
            "7.6.3061.49": "124.0.6367.201",
            "7.5.2869.48": "123.0.6312.122",
        }

        return vivaldi_to_chrome.get(vivaldi_version, "126.0.0.0")
