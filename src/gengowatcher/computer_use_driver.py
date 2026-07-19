"""Computer-Use Driver - Command consumer for visible browser actions.

Consumes commands from event bus and performs approved visible actions.
Outcomes confirmed by passive listener events, NOT by trusting action calls.
"""

from __future__ import annotations

import logging
import queue
import threading

from .events import EventEnvelope
from .event_bus import register_consumer, unregister_consumer
from .native_browser_actions import NativeBrowserActions

logger = logging.getLogger(__name__)


class ComputerUseDriver:
    """Consumes browser.action.requested events and performs visible actions."""

    def __init__(self, debug_url: str = "ws://127.0.0.1:6000"):
        self.actions = NativeBrowserActions(debug_url)
        self.running = False
        self._thread: threading.Thread | None = None
        # Register as event bus consumer — this is the queue the bus feeds
        self._command_queue: queue.Queue = register_consumer("browser_action")
        logger.info("ComputerUseDriver registered as 'browser_action' consumer")

    def start(self) -> None:
        """Start consuming commands."""
        self._command_queue = register_consumer("browser_action")
        self.running = True
        self._thread = threading.Thread(target=self._consume_loop, daemon=True)
        self._thread.start()
        logger.info("Computer-use driver started")

    def stop(self) -> None:
        """Stop consuming and wait for the consumer thread to exit."""
        self.running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        unregister_consumer("browser_action")

    def _consume_loop(self) -> None:
        """Main consumer loop."""
        while self.running:
            try:
                event_data = self._command_queue.get(timeout=1.0)
                self._process_command(event_data)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Command consumer error: {e}", exc_info=True)

    def _process_command(self, event_data: dict) -> None:
        """Process a browser action command."""
        event = EventEnvelope.from_dict(event_data)
        cmd_type = event.type
        payload = event.payload or {}

        if cmd_type == "browser.open_job":
            self._handle_open_job(payload, event.collection_id)
        elif cmd_type == "browser.accept_visible_job":
            self._handle_accept_job(payload, event.collection_id)
        elif cmd_type == "browser.download_file":
            self._handle_download(payload, event.collection_id)

    def _handle_open_job(self, payload: dict, collection_id: str | None) -> None:
        """Open workbench in visible browser."""
        job_id = payload.get("job_id") or collection_id
        if not job_id:
            return

        self.actions.open_workbench(str(job_id))
        # Outcome will be confirmed by passive listener

    def _handle_accept_job(self, payload: dict, collection_id: str | None) -> None:
        """Accept job via visible browser."""
        job_id = payload.get("job_id") or collection_id
        if not job_id:
            return

        # Request user action if needed
        # Native accept if workbench visible
        self.actions.accept_visible_job(str(job_id))

    def _handle_download(self, payload: dict, collection_id: str | None) -> None:
        """Download file via visible browser."""
        job_id = payload.get("job_id") or collection_id
        if not job_id:
            return

        self.actions.download_file(str(job_id))
        # Outcome confirmed by listener seeing file download events
