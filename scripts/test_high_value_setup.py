#!/usr/bin/env python3
"""
Test script to verify high-value job configuration and setup.
"""

__test__ = False

import asyncio
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gengowatcher.config import AppConfig
from gengowatcher.high_value_job_manager import HighValueJobManager


def test_configuration():
    """
    Verify that the high-value job configuration file exists and contains valid settings.

    Checks for the presence of config_high_value.ini, loads it via AppConfig and validates the RSS feed URL, WebSocket credentials (user_id, user_session, user_key), high-value thresholds and CAPTCHA configuration. Status messages are printed to stdout for each check.

    Returns:
        bool: `True` if the configuration file exists and all validations complete without error, `False` otherwise.
    """
    print("Testing High-Value Job Configuration...\n")

    # Check if high-value config exists
    config_path = Path("config_high_value.ini")
    if not config_path.exists():
        print("❌ ERROR: config_high_value.ini not found!")
        print("\nPlease create this configuration file with your Gengo settings.")
        return False

    # Load and test configuration
    try:
        config = AppConfig()
        config.CONFIG_FILE = "config_high_value.ini"
        config.load_config()

        # Check critical settings
        print("✅ Configuration loaded successfully")

        # Check RSS feed URL
        feed_url = config.get("Watcher", "feed_url")
        parsed_feed = urlparse(feed_url)
        host = parsed_feed.hostname
        if (
            host
            and (host == "gengo.com" or host.endswith(".gengo.com"))
            and "YOUR_RSS_KEY" not in feed_url
        ):
            print("✅ RSS feed URL appears to be configured")
        else:
            print("❌ RSS feed URL needs configuration")

        # Check WebSocket settings
        user_id = config.get("WebSocket", "user_id")
        session = config.get("WebSocket", "user_session")
        user_key = config.get("WebSocket", "user_key")
        key_placeholder_tokens = {
            "YOUR_USER_KEY",
            "REPLACE_WITH_YOUR_USER_KEY",
            "REPLACE_WITH_BROWSER_USER_KEY",
        }
        if (
            user_id != 0
            and "YOUR_SESSION_TOKEN" not in session
            and not any(token in (user_key or "") for token in key_placeholder_tokens)
        ):
            print("✅ WebSocket appears to be configured")
        else:
            print("❌ WebSocket needs configuration")

        # Check high-value thresholds
        threshold = float(config.get("HighValue", "threshold"))
        very_high = float(config.get("HighValue", "very_high_threshold"))
        extreme = float(config.get("HighValue", "extreme_threshold"))
        print(f"✅ High-value thresholds: ${threshold}, ${very_high}, ${extreme}")

        # Check CAPTCHA settings
        captcha_service = config.get("Captcha", "service")
        if captcha_service and "YOUR_2CAPTCHA_API_KEY" not in config.get(
            "Captcha", "api_key"
        ):
            print(f"✅ CAPTCHA service configured: {captcha_service}")
        else:
            print(
                "⚠️  CAPTCHA service not configured - recommended for high-value jobs"
            )

        return True

    except Exception as e:
        print(f"❌ Error loading configuration: {e}")
        return False


async def test_high_value_manager():
    """Test the HighValueJobManager with sample data."""
    print("\nTesting HighValueJobManager...\n")

    try:
        # Set up logging
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger("Test")

        # Load configuration
        config = AppConfig()
        config.CONFIG_FILE = "config_high_value.ini"
        config.load_config()

        # Create manager
        manager = HighValueJobManager(config, logger)

        # Test with sample jobs
        test_jobs = [
            {"id": "test1", "reward": 100.0, "title": "Small job"},
            {"id": "test2", "reward": 600.0, "title": "High-value job"},
            {"id": "test3", "reward": 1500.0, "title": "Very high-value job"},
            {"id": "test4", "reward": 10000.0, "title": "EXTREME value job"},
        ]

        for job in test_jobs:
            is_hv, category = manager.is_high_value(job["reward"])
            print(
                f"Job {job['id']}: ${job['reward']} -> {category if is_hv else 'Standard'}"
            )

        # Test stats
        stats = manager.get_stats()
        print("\n📊 Current Stats:")
        print(f"   High-value threshold: ${stats['thresholds']['high']}")
        print(f"   Max per day: {config.get('HighValue', 'max_per_day')}")
        print(
            f"   Min interval: {config.get('HighValue', 'min_interval_seconds')} seconds"
        )

        return True

    except Exception as e:
        print(f"❌ Error testing manager: {e}")
        return False


def show_setup_instructions():
    """
    Print the setup and configuration instructions required to configure high-value job monitoring.

    The printed message covers required configuration file edits and keys, RSS feed details, WebSocket credentials (user ID, session cookie and user key), running instructions, recommended safety limits and notification/logging locations.
    """
    print("\n" + "=" * 60)
    print("HIGH-VALUE JOB SETUP INSTRUCTIONS")
    print("=" * 60)
    print("""
1. CONFIGURATION:
   - Copy config_high_value.ini to config.ini
   - Update YOUR_RSS_KEY_HERE with your actual RSS key
   - Set your user_id, user_session, and user_key from Gengo
   - Configure CAPTCHA service (recommended: 2captcha)

2. RSS FEED:
   - Get your RSS key from: https://gengo.com/developers/dashboard
   - Format: https://gengo.com/rss/available_jobs/YOUR_KEY

3. WEBSOCKET:
   - User ID found in Gengo dashboard URL
   - Session cookie from browser dev tools (Cookies → my_gengo_session)
   - User key from browser dev tools (Application → Local Storage → https://gengo.com → userKey)

4. RUNNING:
   - Use: python -m gengowatcher.main
   - Monitor logs for high-value job alerts

5. SAFETY LIMITS:
   - Default: 3 high-value jobs per day
   - Minimum 6 hours between acceptances
   - Extreme value jobs ($5000+) bypass limits

6. NOTIFICATIONS:
   - Desktop alerts for high-value jobs
   - Sound alerts configured
   - Detailed logging in logs/high_value_jobs.json
""")


def main():
    """Run all tests."""
    print("🚀 GengoWatcher High-Value Job Setup Test\n")

    # Test configuration
    config_ok = test_configuration()

    if config_ok:
        # Test manager
        import asyncio

        manager_ok = asyncio.run(test_high_value_manager())

        if manager_ok:
            print("\n✅ All tests passed!")
            show_setup_instructions()
        else:
            print("\n❌ Manager test failed")
    else:
        print("\n❌ Configuration test failed")


if __name__ == "__main__":
    main()
