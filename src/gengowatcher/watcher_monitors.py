"""Optional-monitor thread helpers extracted from GengoWatcher.

Owns the three side-channel monitor threads that the orchestrator's
``run()`` method spawns alongside the RSS and WebSocket monitors:

* run_email_monitor(watcher)         -- EmailMonitor-backed worker.
* run_website_monitor(watcher)       -- WebsiteMonitor-backed worker.
* run_native_browser_listener(watcher)
  -- NativeBrowserListener + StateProjector pipeline.

The watcher keeps thin delegator methods on the class so the
existing ``threading.Thread(target=self._run_*)`` call sites in
``GengoWatcher.run()`` continue to resolve them through the
instance.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING

try:
    from .email_monitor import EmailMonitor
except ImportError:  # pragma: no cover - email monitor optional
    EmailMonitor = None

try:
    from .native_browser_listener import NativeBrowserListener
except ImportError:  # pragma: no cover - native listener optional
    NativeBrowserListener = None

try:
    from .state_projector import StateProjector
except ImportError:  # pragma: no cover - state projector optional
    StateProjector = None

try:
    from .website_monitor import WebsiteMonitor
except ImportError:  # pragma: no cover - website monitor optional
    WebsiteMonitor = None

if TYPE_CHECKING:
    pass


def run_email_monitor(watcher):
    """Run email monitor in a dedicated thread with its own event loop."""
    if EmailMonitor is None:
        watcher.logger.error("Email monitor dependencies not installed")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def job_callback(job_id, title, reward, url, source):
        await asyncio.to_thread(
            watcher._process_new_job, job_id, title, reward, url, source
        )

    watcher.email_monitor = EmailMonitor(
        config=watcher.config,
        logger=watcher.logger,
        job_callback=job_callback,
        shutdown_event=asyncio.Event(),
    )

    checker_stop = threading.Event()

    def check_shutdown():
        while not checker_stop.wait(1):
            if not watcher.shutdown_event.is_set():
                continue
            break
        if watcher.email_monitor:
            loop.call_soon_threadsafe(watcher.email_monitor.shutdown_event.set)

    shutdown_thread = threading.Thread(target=check_shutdown, daemon=True)
    shutdown_thread.start()

    try:
        loop.run_until_complete(watcher.email_monitor.start())
    except Exception as e:
        watcher.logger.error(f"Email monitor error: {e}")
    finally:
        checker_stop.set()
        shutdown_thread.join()
        loop.close()


def run_website_monitor(watcher):
    """Run website monitor in a dedicated thread with its own event loop."""
    if WebsiteMonitor is None:
        watcher.logger.error("Website monitor dependencies not installed (playwright)")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def job_callback(job_id, title, reward, url, source):
        await asyncio.to_thread(
            watcher._process_new_job, job_id, title, reward, url, source
        )

    watcher.website_monitor = WebsiteMonitor(
        config=watcher.config,
        logger=watcher.logger,
        job_callback=job_callback,
        shutdown_event=asyncio.Event(),
    )

    checker_stop = threading.Event()

    def check_shutdown():
        while not checker_stop.wait(1):
            if not watcher.shutdown_event.is_set():
                continue
            break
        if watcher.website_monitor:
            loop.call_soon_threadsafe(watcher.website_monitor.shutdown_event.set)

    shutdown_thread = threading.Thread(target=check_shutdown, daemon=True)
    shutdown_thread.start()

    try:
        loop.run_until_complete(watcher.website_monitor.start())
    except Exception as e:
        watcher.logger.error(f"Website monitor error: {e}")
    finally:
        checker_stop.set()
        shutdown_thread.join()
        loop.close()


def run_native_browser_listener(watcher):
    """Run native browser listener loop - drains events into state projector."""
    from queue import Empty

    watcher.logger.info("Native browser listener starting...")
    while not watcher.shutdown_event.is_set():
        try:
            # Poll native listener (publishes events)
            if hasattr(watcher, "_native_listener"):
                watcher._native_listener.run_once()

            # Drain events into state projector
            if hasattr(watcher, "_state_projector"):
                try:
                    from .event_bus import get_native_events_queue
                    from .events import EventEnvelope

                    q = get_native_events_queue()
                    while True:
                        try:
                            event_dict = q.get_nowait()
                            event = EventEnvelope.from_dict(event_dict)
                            watcher._state_projector.project(event)
                        except Empty:
                            break
                        except Exception as e:
                            watcher.logger.debug(f"Event projection error: {e}")
                except Exception as e:
                    watcher.logger.debug(f"Event bus drain error: {e}")

        except Exception as e:
            watcher.logger.debug(f"Native browser listener error: {e}")
        capture_interval = (
            getattr(watcher, "_native_listener", None).capture_interval
            if hasattr(watcher, "_native_listener")
            and hasattr(getattr(watcher, "_native_listener", None), "capture_interval")
            else 0.75
        )
        time.sleep(capture_interval)


__all__ = [
    "run_email_monitor",
    "run_native_browser_listener",
    "run_website_monitor",
]
