"""Native Browser Listener - observes visible Firefox for Gengo workbench events.

Uses Firefox RDP via browser_session.py helpers (_open_firefox_rdp_client,
_firefox_rdp_list_tabs, _firefox_rdp_evaluate_json) to observe workbench
visibility and extract normalized workbench payloads.

No script injection beyond reading already-loaded page state. No HTTP scraping.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
from typing import Any

from . import _async_utils
from .events import EventEnvelope, EventType
from .event_bus import publish_native_event
from .workbench_payload import normalize_workbench_payload
from .browser_session import (
    _open_firefox_rdp_client,
    _firefox_rdp_list_tabs,
    _firefox_rdp_evaluate_json,
    _firefox_rdp_resolve_tab,
)

logger = logging.getLogger(__name__)

WORKBENCH_PATH_PREFIX = "/t/workbench/"

# JS expression: scan page objects for a workbench-shaped payload
# (summary + jobs array). Mirrors browser_worker/flows/accept_flow.py logic.
_WORKBENCH_SCAN_EXPRESSION = """
(() => {
  const seen = new Set();
  const MAX_DEPTH = 4;
  const MAX_KEYS = 40;
  const MAX_VISITED = 1000;
  let visited = 0;
  function isObject(v) { return v !== null && typeof v === "object"; }
  function looksLikeWorkbench(v) {
    if (!isObject(v)) return false;
    const s = v.summary; const j = v.jobs;
    if (!isObject(s) || !Array.isArray(j)) return false;
    return s.order_id !== undefined || s.seconds_left !== undefined;
  }
  function clone(v) { return JSON.parse(JSON.stringify(v)); }
  function scan(value, path, depth) {
    if (!isObject(value) || seen.has(value) || visited >= MAX_VISITED) return null;
    seen.add(value); visited++;
    if (looksLikeWorkbench(value)) {
      try {
        return { source: path, payload: clone(value) };
      } catch (_e) {
        return null;
      }
    }
    if (depth >= MAX_DEPTH) return null;
    let keys = [];
    try { keys = Object.keys(value).slice(0, MAX_KEYS); } catch (_e) { return null; }
    for (const key of keys) {
      let child;
      try { child = value[key]; } catch (_e) { continue; }
      const r = scan(child, path + "." + key, depth + 1);
      if (r) return r;
    }
    return null;
  }
  const roots = [
    ["window.myG_myGSession_", window.myG_myGSession_],
    ["window.__INITIAL_STATE__", window.__INITIAL_STATE__],
    ["window.__NEXT_DATA__", window.__NEXT_DATA__],
  ];
  for (const [name, root] of roots) {
    const found = scan(root, name, 0);
    if (found) return JSON.stringify({ result: found });
  }
  return JSON.stringify({ result: null });
})()
"""

# JS expression: read current URL + seconds_left from the workbench page
_WORKBENCH_STATUS_EXPRESSION = """
(() => {
  const url = location.href || "";
  let secondsLeft = null;
  const countdownEl = document.querySelector("[data-seconds-left], [data-countdown]");
  if (countdownEl) {
    secondsLeft = parseInt(countdownEl.getAttribute("data-seconds-left")
      || countdownEl.getAttribute("data-countdown") || "", 10);
    if (isNaN(secondsLeft)) secondsLeft = null;
  }
  const m = url.match(/\\/workbench\\/(\\d+)/);
  return JSON.stringify({ url, collection_id: m ? m[1] : null, seconds_left: secondsLeft });
})()
"""


class _RdpConnection:
    """Async context manager for a single RDP client connection."""

    def __init__(self, debug_url: str):
        self.debug_url = debug_url
        self.client: Any = None

    async def __aenter__(self) -> "_RdpConnection":
        self.client = await _open_firefox_rdp_client(self.debug_url)
        return self

    async def __aexit__(self, *exc) -> None:
        if self.client is not None:
            try:
                await self.client.websocket.close()
            except Exception as e:
                logger.debug(f"Error closing RDP websocket: {e}")

    async def list_tabs(self) -> list[dict[str, Any]]:
        response = await _firefox_rdp_list_tabs(self.client)
        tabs = response.get("tabs", [])
        return tabs if isinstance(tabs, list) else []

    async def find_workbench_tab(self) -> tuple[dict[str, Any] | None, str | None]:
        for tab in await self.list_tabs():
            url = str(tab.get("url", ""))
            if WORKBENCH_PATH_PREFIX in url:
                resolved_tab = await _firefox_rdp_resolve_tab(self.client, tab)
                if resolved_tab is None:
                    continue
                actor = str(resolved_tab.get("consoleActor") or "").strip()
                if actor:
                    return resolved_tab, actor
        return None, None

    async def evaluate(
        self,
        actor: str,
        expression: str,
        *,
        inner_window_id: int | None = None,
    ) -> dict[str, Any] | None:
        try:
            return await _firefox_rdp_evaluate_json(
                self.client,
                actor,
                expression,
                inner_window_id=inner_window_id,
            )
        except Exception as e:
            logger.debug(f"RDP evaluate failed: {e}")
            return None


class NativeBrowserListener:
    """Uses browser_session.py RDP helpers to observe workbench state.

    Emits:
    - browser.workbench.visible: raw {collection_id, url, raw, seconds_left}
    - browser.workbench.details: normalized payload from page scan
    - browser.workbench.status: countdown updates
    """

    def __init__(
        self,
        debug_url: str = "ws://127.0.0.1:6000",
        capture_interval_ms: int = 750,
    ):
        self.debug_url = debug_url
        self.capture_interval = capture_interval_ms / 1000.0
        self.running = False
        self._last_collection_id: str | None = None
        self.last_poll_ts: float | None = None
        self.last_success_ts: float | None = None
        self.last_error: str = ""
        self.last_workbench_url: str = ""
        self.detected_collection_id: str | None = None
        self.workbench_detected_count = 0
        self._last_visible_payload: dict[str, Any] | None = None
        self._last_status_seconds: int | None = None
        self._last_status_collection_id: str | None = None

    def _reset_workbench_state(self) -> None:
        self._last_collection_id = None
        self.detected_collection_id = None
        self.last_workbench_url = ""
        self._last_visible_payload = None
        self._last_status_collection_id = None
        self._last_status_seconds = None

    def start(self) -> None:
        self.running = True
        logger.info(f"Native browser listener starting on {self.debug_url}")

    def stop(self) -> None:
        self.running = False
        logger.info("Native browser listener stopped")

    def _poll(self) -> None:
        """Single poll iteration."""
        self.last_poll_ts = time.time()
        try:
            _async_utils.run_coroutine_sync(self._poll_async)
            self.last_success_ts = time.time()
            self.last_error = ""
        except Exception as e:
            self.last_error = str(e)
            logger.exception("Poll iteration failed")
            self._reset_workbench_state()

    async def _poll_async(self) -> None:
        async with _RdpConnection(self.debug_url) as conn:
            tab, actor = await conn.find_workbench_tab()
            if not tab or not actor:
                self._reset_workbench_state()
                return

            url = tab.get("url", "")
            collection_id = (
                urllib.parse.urlparse(url).path.split("/workbench/")[-1].split("/")[0]
            )
            if not collection_id:
                self._reset_workbench_state()
                return

            inner_window_id = tab.get("innerWindowId")

            # 1) Scan page objects for full workbench payload
            scan_result = await conn.evaluate(
                actor,
                _WORKBENCH_SCAN_EXPRESSION,
                inner_window_id=inner_window_id,
            )
            raw_envelope = None

            # The scan expression returns JSON-stringified result,
            # _firefox_rdp_evaluate_json parses it to dict already
            if isinstance(scan_result, dict):
                raw_envelope = scan_result.get("result")
            elif isinstance(scan_result, str):
                try:
                    raw_envelope = json.loads(scan_result)
                except (json.JSONDecodeError, TypeError):
                    raw_envelope = None

            # 2) Read status (URL, seconds_left)
            status_info: dict[str, Any] = {}
            status_result = await conn.evaluate(
                actor,
                _WORKBENCH_STATUS_EXPRESSION,
                inner_window_id=inner_window_id,
            )
            if isinstance(status_result, dict):
                status_info = status_result
            elif isinstance(status_result, str):
                try:
                    status_info = json.loads(status_result)
                except (json.JSONDecodeError, TypeError):
                    pass

            # Emit visibility event (always, when workbench is visible)
            is_new = collection_id != self._last_collection_id
            self._last_collection_id = collection_id
            self.detected_collection_id = collection_id
            self.last_workbench_url = str(url or "")
            if is_new:
                self.workbench_detected_count += 1

            visible_payload: dict[str, Any] = {
                "collection_id": collection_id,
                "url": url,
                "raw": raw_envelope,
                "seconds_left": status_info.get("seconds_left"),
            }
            if visible_payload != self._last_visible_payload:
                self._last_visible_payload = visible_payload
                publish_native_event(
                    EventEnvelope(
                        type=EventType.BROWSER_WORKBENCH_VISIBLE,
                        source="native_browser_listener",
                        payload=visible_payload,
                        collection_id=collection_id,
                    )
                )

            # Normalize from page-object scan if available
            if isinstance(raw_envelope, dict):
                # raw_envelope shape: {source, payload: {summary, jobs, ...}}
                if isinstance(raw_envelope.get("payload"), dict):
                    normalized = normalize_workbench_payload(raw_envelope["payload"])
                else:
                    normalized = normalize_workbench_payload(raw_envelope)
                if normalized:
                    normalized.setdefault("collection_id", collection_id)
                    normalized.setdefault("url", url)
                    publish_native_event(
                        EventEnvelope(
                            type=EventType.BROWSER_WORKBENCH_DETAILS,
                            source="native_browser_listener",
                            payload={
                                "collection_id": collection_id,
                                "normalized": normalized,
                            },
                            collection_id=collection_id,
                        )
                    )

            # Emit countdown status
            current_seconds = status_info.get("seconds_left")
            if current_seconds is not None and (
                collection_id != self._last_status_collection_id
                or current_seconds != self._last_status_seconds
            ):
                self._last_status_collection_id = collection_id
                self._last_status_seconds = current_seconds
                publish_native_event(
                    EventEnvelope(
                        type=EventType.BROWSER_WORKBENCH_STATUS,
                        source="native_browser_listener",
                        payload={
                            "collection_id": collection_id,
                            "seconds_left": current_seconds,
                        },
                        collection_id=collection_id,
                    )
                )

            if is_new:
                logger.info(f"Workbench detected: {collection_id}")

    def run_forever(self) -> None:
        """Main listener loop."""
        self.start()
        import time

        while self.running:
            try:
                self._poll()
            except Exception as e:
                logger.error(f"Native browser listener error: {e}", exc_info=True)
            time.sleep(self.capture_interval)

    def run_once(self) -> None:
        """Single poll - for testing."""
        self._poll()
