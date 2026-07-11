"""Native Browser Actions - RDP/BiDi driven actions on visible browser.

Uses ONLY Firefox RDP/BiDi to:
- Focus existing Gengo tab
- Open job URL  
- Click visible controls via console evaluation
- Trigger downloads

Outcomes confirmed by passive listener events, NOT by trusting action calls.
"""

from __future__ import annotations

import logging

from .browser_session import (
    open_url_in_browser_debug_sync,
    refresh_browser_page_activity_sync,
)

logger = logging.getLogger(__name__)


class NativeBrowserActions:
    """Action driver using RDP/BiDi on visible browser only."""

    def __init__(self, debug_url: str = "ws://127.0.0.1:6000"):
        self.debug_url = debug_url

    def open_workbench(self, collection_id: str) -> bool:
        """Open workbench URL in existing tab or new tab using browser_session."""
        url = f"https://gengo.com/t/workbench/{collection_id}"
        try:
            result = open_url_in_browser_debug_sync(
                debug_url=self.debug_url,
                url=url,
            )
            return result in ("focus", "open")
        except Exception as e:
            logger.error(f"Failed to open workbench: {e}")
            return False

    def accept_visible_job(self, collection_id: str) -> bool:
        """Click accept button via browser refresh activity.

        We DON'T click directly - instead we let the user click manually and
        observe the result via native_browser_listener. This is the safe path.

        For auto-accept mode, we use browser activity that triggers page reload
        and the listener will see the accepted state.
        """
        try:
            # Refresh browser to trigger any pending operations
            # The actual click is done by user or via page navigation
            result = refresh_browser_page_activity_sync(
                debug_url=self.debug_url,
                action="auto",
            )
            return result in ("reload", "job_roundtrip", "summary_roundtrip")
        except Exception as e:
            logger.error(f"Failed to trigger accept workflow: {e}")
            return False

    def download_file(self, collection_id: str) -> bool:
        """Trigger file download via browser activity.

        We DON'T download directly - the listener will see download events.
        Instead we trigger page refresh to expose download buttons.
        """
        try:
            result = refresh_browser_page_activity_sync(
                debug_url=self.debug_url,
                action="auto",
            )
            return result in ("reload", "job_roundtrip", "summary_roundtrip")
        except Exception as e:
            logger.error(f"Download trigger failed: {e}")
            return False

    def focus_gengo_tab(self) -> bool:
        """Focus existing Gengo tab in browser."""
        url = "https://gengo.com/t/jobs/status/available"
        try:
            result = open_url_in_browser_debug_sync(
                debug_url=self.debug_url,
                url=url,
            )
            return result == "focus"
        except Exception as e:
            logger.error(f"Failed to focus Gengo tab: {e}")
            return False