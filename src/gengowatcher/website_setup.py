"""
Website Setup - Interactive WebsiteMonitor configuration wizard.

Guides user through configuring the WebsiteMonitor for scraping the Gengo jobs page.
"""

import re
from urllib.parse import urlparse

from .config import AppConfig


def validate_url(url: str) -> bool:
    """Validate that the URL is a valid HTTP/HTTPS URL."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def validate_interval(value: str, min_val: int = 30, max_val: int = 3600) -> int | None:
    """Validate and parse an interval value."""
    try:
        interval = int(value)
        if min_val <= interval <= max_val:
            return interval
        return None
    except ValueError:
        return None


def setup_website_interactive(config: AppConfig, logger=None) -> bool:
    """
    Interactive setup wizard for WebsiteMonitor configuration.

    Returns True if setup completed successfully.
    """

    def log(msg: str):
        if logger:
            logger.info(msg)
        else:
            print(msg)

    log("\n" + "=" * 60)
    log("    WebsiteMonitor Setup Wizard")
    log("=" * 60 + "\n")

    log("What is WebsiteMonitor?")
    log("-" * 40)
    log("WebsiteMonitor uses a stealth browser (Playwright) to periodically")
    log("visit the Gengo jobs page and detect new job listings.")
    log("")
    log("It uses human-like behavior (random delays, mouse movements,")
    log("natural scrolling) to avoid detection as a bot.")
    log("")
    log("This is useful as a backup when WebSocket or RSS are unavailable.\n")

    log("Requirements:")
    log("  - Playwright browser: pip install playwright && playwright install chromium")
    log("  - Valid Gengo session cookie (extracted from your browser)\n")

    # Prompt for jobs_url
    log("-" * 40)
    log("Jobs Page URL")
    log("-" * 40)
    current_url = (
        config.get("WebsiteMonitor", "jobs_url") or "https://gengo.com/t/jobs/"
    )
    log(f"Current: {current_url}")
    log("The URL to monitor for new jobs. Usually: https://gengo.com/t/jobs/\n")

    while True:
        jobs_url = input("Enter jobs URL (Enter to keep current): ").strip()
        if not jobs_url:
            jobs_url = current_url
            break
        if validate_url(jobs_url):
            break
        log("Error: Invalid URL. Please enter a valid HTTP/HTTPS URL.")

    config.set("WebsiteMonitor", "jobs_url", jobs_url)

    # Prompt for session_cookie
    log("\n" + "-" * 40)
    log("Session Cookie")
    log("-" * 40)
    log("To authenticate, you need your Gengo session cookie.\n")
    log("How to extract it:")
    log("  1. Log in to gengo.com in your browser")
    log("  2. Open Developer Tools (F12)")
    log("  3. Go to Application -> Cookies -> https://gengo.com")
    log("  4. Find the cookie named '_gengo_session'")
    log("  5. Copy the entire Value (it's a long string)\n")

    current_cookie = config.get("WebsiteMonitor", "session_cookie") or ""
    if current_cookie:
        masked = (
            current_cookie[:10] + "..." + current_cookie[-10:]
            if len(current_cookie) > 25
            else current_cookie
        )
        log(f"Current: {masked}")

    while True:
        session_cookie = input("Enter session cookie (Enter to keep current): ").strip()
        if not session_cookie:
            if current_cookie:
                session_cookie = current_cookie
                break
            else:
                log("Error: Session cookie is required for WebsiteMonitor to work.")
                continue
        if len(session_cookie) < 10:
            log("Error: Session cookie seems too short. Please check and try again.")
            continue
        break

    config.set("WebsiteMonitor", "session_cookie", session_cookie)

    # Prompt for headless mode
    log("\n" + "-" * 40)
    log("Headless Mode")
    log("-" * 40)
    log("Headless mode runs the browser invisibly in the background.")
    log("Non-headless mode shows the browser window (useful for debugging).\n")

    current_headless = config.get("WebsiteMonitor", "headless")
    if current_headless is None:
        current_headless = True
    current_str = "yes" if current_headless else "no"
    log(f"Current: {current_str}")

    while True:
        headless_input = (
            input("Run headless (invisible)? [yes/no] (Enter to keep current): ")
            .strip()
            .lower()
        )
        if not headless_input:
            headless = current_headless
            break
        if headless_input in ("yes", "y", "true", "1"):
            headless = True
            break
        if headless_input in ("no", "n", "false", "0"):
            headless = False
            break
        log("Error: Please enter 'yes' or 'no'.")

    config.set("WebsiteMonitor", "headless", headless)

    # Prompt for check_interval_min
    log("\n" + "-" * 40)
    log("Check Interval (seconds)")
    log("-" * 40)
    log("How often to check for new jobs. Uses a random interval between")
    log("min and max to appear more human-like.\n")
    log("Recommended: 120-300 seconds (2-5 minutes)")
    log("Shorter intervals may trigger anti-bot detection.\n")

    current_min = config.get("WebsiteMonitor", "check_interval_min") or 120
    current_max = config.get("WebsiteMonitor", "check_interval_max") or 300
    log(f"Current: {current_min}-{current_max} seconds")

    while True:
        min_input = input(
            f"Minimum interval in seconds (Enter for {current_min}): "
        ).strip()
        if not min_input:
            check_min = current_min
            break
        check_min = validate_interval(min_input, 30, 3600)
        if check_min is not None:
            break
        log("Error: Please enter a number between 30 and 3600.")

    config.set("WebsiteMonitor", "check_interval_min", check_min)

    while True:
        max_input = input(
            f"Maximum interval in seconds (Enter for {current_max}): "
        ).strip()
        if not max_input:
            check_max = current_max
            break
        check_max = validate_interval(max_input, 30, 3600)
        if check_max is not None:
            if check_max >= check_min:
                break
            log(f"Error: Maximum must be >= minimum ({check_min}).")
        else:
            log("Error: Please enter a number between 30 and 3600.")

    config.set("WebsiteMonitor", "check_interval_max", check_max)

    # Enable the monitor
    config.set("WebsiteMonitor", "enabled", True)

    # Save configuration
    config.save_config()

    log("\n" + "=" * 60)
    log("    Setup Complete!")
    log("=" * 60)
    log("")
    log("Configuration saved to config.ini:")
    log(f"  Jobs URL:        {jobs_url}")
    log(f"  Session Cookie:  {'*' * 20} (hidden)")
    log(f"  Headless Mode:   {'Yes' if headless else 'No'}")
    log(f"  Check Interval:  {check_min}-{check_max} seconds")
    log("  Enabled:         Yes")
    log("")
    log("WebsiteMonitor is now enabled and will start with GengoWatcher.")
    log("")
    log("Note: Make sure Playwright is installed:")
    log("  pip install playwright && playwright install chromium")
    log("")

    return True
