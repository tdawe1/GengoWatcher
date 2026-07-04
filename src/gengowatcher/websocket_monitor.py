"""Clean WebSocket monitor with browser session integration."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from .browser_session import (
    BrowserSessionError,
    build_browser_aligned_websocket_headers,
    fetch_browser_session_snapshot_sync,
)
from .config import AppConfig
from .state import AppState
from .watcher_debug import redact_raw_ws_text as _redact_raw_ws_text


@dataclass
class WebSocketMetrics:
    connected_at_ts: Optional[float] = None
    last_pong_ts: Optional[float] = None
    ping_latency_ms: Optional[float] = None
    next_ping_ts: Optional[float] = None
    last_message_ts: Optional[float] = None
    last_close_code: Optional[int] = None
    last_close_reason: Optional[str] = None
    reconnect_count: int = 0
    sync_failed: bool = False
    sync_failure_reason: str = ""


@dataclass
class WebSocketConfig:
    wss_url: str = "wss://live-dashboard.gengo.com/"
    user_id: str = ""
    session_token: str = ""
    user_key: str = ""
    enable: bool = True
    heartbeat_sec: int = 25
    open_timeout: int = 20
    ping_timeout: int = 10
    session_sync_interval_sec: int = 14400
    session_sync_fail_hard: bool = True
    session_sync_alert_on_failure: bool = True
    browser_debug_url: str = ""
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    )
    accept_language: str = "en-GB,en-US;q=0.9,en;q=0.8"


def _build_auth_payload(user_id: str, session_token: str, user_key: str = "") -> dict:
    """Build the Gengo WebSocket authentication payload."""
    payload = {"userId": user_id, "sessionToken": session_token}
    if user_key:
        payload["userKey"] = user_key
    return payload


class GengoWebSocketMonitor:
    """Manages WebSocket connection to Gengo realtime API with browser-aligned headers."""

    HEARTBEAT_INTERVAL = 25
    MAX_BACKOFF = 60.0
    BASE_BACKOFF = 5.0
    RECONNECT_JITTER_MAX = 5.0
    CLEAN_CLOSE_BACKOFF_MIN = 1.0
    CLEAN_CLOSE_BACKOFF_MAX = 5.0

    def __init__(
        self,
        config: AppConfig,
        state: AppState,
        logger: logging.Logger,
        *,
        on_job_received: Optional[Callable[[Any], Any]] = None,
        on_event: Optional[Callable[[Any], Any]] = None,
    ):
        self.config = config
        self.state = state
        self.logger = logger
        self.on_job_received = on_job_received
        self.on_event = on_event
        self.defaults = WebSocketConfig()
        self.metrics = WebSocketMetrics()
        self._shutdown_event = threading.Event()
        self._raw_ws_messages: list[dict] = []
        self._capture_max = 100
        self._next_quiet_socket_sync_ts: float = 0.0
        self._websocket_session_refresh_requested = False
        self._websocket_sync_failed = False
        self._websocket_sync_failure_reason = ""

    def is_configured(self) -> bool:
        session_token = self.config.get("WebSocket", "user_session")
        return bool(
            session_token
            and session_token not in {None, "", "REPLACE_WITH_YOUR_SESSION_TOKEN"}
        )

    def _sync_session_from_browser(self) -> bool:
        """Sync session token from live browser, return True if changed."""
        debug_url = self.config.get("WebSocket", "browser_debug_url")
        if not debug_url:
            return False

        try:
            snapshot = fetch_browser_session_snapshot_sync(str(debug_url))
            browser_token = snapshot.session_token
            configured_token = self.config.get("WebSocket", "user_session")
            if browser_token and browser_token != configured_token:
                self.logger.info(
                    f"WebSocket: Synced browser session token (masked: {configured_token[:4] if configured_token else ''}...{configured_token[-4:] if configured_token and len(configured_token) > 4 else ''})"
                )
                self.config.set("WebSocket", "user_session", browser_token)
                return True
        except Exception as exc:
            self.logger.warning(f"Browser session sync skipped: {exc}")
        return False

    def _build_headers(self) -> dict[str, str]:
        session_token = self.config.get("WebSocket", "user_session", "")
        user_agent = (
            self.config.get("Network", "browser_user_agent", "")
            or self.defaults.user_agent
        )
        accept_language = (
            self.config.get("Network", "browser_accept_language", "")
            or self.defaults.accept_language
        )
        return build_browser_aligned_websocket_headers(
            session_token=session_token,
            user_agent=user_agent,
            origin="https://gengo.com",
            accept_language=accept_language,
        )

    def _capture_raw_ws_message(self, message: str, *, direction: str = "recv") -> None:
        if len(self._raw_ws_messages) >= self._capture_max:
            self._raw_ws_messages.pop(0)
        self._raw_ws_messages.append(
            {
                "direction": direction,
                "payload": _redact_raw_ws_text(message)[:2000],
                "ts": time.time(),
            }
        )

    def get_raw_ws_messages(self) -> list[dict]:
        return list(self._raw_ws_messages)

    def _config_int(self, section: str, key: str, fallback: int) -> int:
        getter = getattr(self.config, "getint", None)
        if callable(getter):
            try:
                return int(getter(section, key, fallback=fallback))
            except Exception:
                pass
        try:
            return int(self.config.get(section, key, fallback))
        except Exception:
            return fallback

    def _connect(self, ws_url: str, *, headers: Optional[dict] = None):
        return websockets.connect(
            ws_url,
            additional_headers=headers,
            open_timeout=self._config_int(
                "WebSocket", "open_timeout", self.defaults.open_timeout
            ),
            ping_interval=self._config_int(
                "WebSocket", "heartbeat_sec", self.defaults.heartbeat_sec
            ),
            ping_timeout=self._config_int(
                "WebSocket", "ping_timeout", self.defaults.ping_timeout
            ),
        )

    async def _call_callback(
        self,
        callback: Callable[[Any], Any] | None,
        payload: Any,
        *,
        name: str,
    ) -> None:
        if not callable(callback):
            return
        try:
            result = callback(payload)
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:
            self.logger.error("WebSocket %s callback failed: %s", name, exc)

    async def _handle_received_message(self, message: str | bytes) -> None:
        if isinstance(message, bytes):
            message_text = message.decode("utf-8", errors="replace")
        else:
            message_text = str(message)

        self.metrics.last_message_ts = time.time()
        self._capture_raw_ws_message(message_text, direction="recv")

        try:
            payload = json.loads(message_text)
        except Exception as exc:
            self.logger.warning("WebSocket: Could not parse message as JSON: %s", exc)
            await self._call_callback(
                self.on_event,
                message_text,
                name="event",
            )
            return

        await self._call_callback(self.on_event, payload, name="event")
        if not isinstance(payload, dict):
            self.logger.debug("WebSocket: Ignoring non-object message payload")
            return

        msg_type = payload.get("type")
        if msg_type != "available_collection":
            self.logger.debug("WebSocket: Ignoring message type %r", msg_type)
            return

        collection = payload.get("collection")
        job_payload = collection if isinstance(collection, dict) else payload
        await self._call_callback(
            self.on_job_received,
            job_payload,
            name="job",
        )

    async def _websocket_session(self) -> None:
        """Single WebSocket session lifecycle."""
        ws_url = self.config.get("WebSocket", "wss_url") or self.defaults.wss_url
        user_id = self.config.get("WebSocket", "user_id")
        session_token = self.config.get("WebSocket", "user_session")
        user_key = self.config.get("WebSocket", "user_key", "")

        headers = self._build_headers()

        try:
            async with self._connect(ws_url, headers=headers) as ws:
                self.metrics.connected_at_ts = time.time()
                self.metrics.last_close_code = None
                self.metrics.last_close_reason = None
                self.logger.info(f"WebSocket: Connected to {ws_url}")

                auth = _build_auth_payload(user_id, session_token, user_key)
                self._capture_raw_ws_message(json.dumps(auth), direction="send")
                await ws.send(json.dumps(auth))
                self.logger.debug("WebSocket: Auth sent")

                async def receive_loop() -> None:
                    try:
                        async for message in ws:
                            await self._handle_received_message(message)
                    except ConnectionClosed as exc:
                        self.metrics.last_close_code = getattr(exc, "code", None)
                        self.metrics.last_close_reason = getattr(exc, "reason", None)
                        self.logger.info(
                            "WebSocket: Connection closed: code=%s reason=%s",
                            self.metrics.last_close_code,
                            self.metrics.last_close_reason,
                        )

                async def heartbeat_loop() -> None:
                    while True:
                        await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                        t0 = time.perf_counter()
                        pong_waiter = await ws.ping()
                        await asyncio.wait_for(pong_waiter, timeout=5)
                        self.metrics.last_pong_ts = time.time()
                        self.metrics.ping_latency_ms = (time.perf_counter() - t0) * 1000
                        # Throttle session sync
                        now = time.time()
                        if now >= self._next_quiet_socket_sync_ts:
                            sync_ok = await asyncio.to_thread(self._sync_session_from_browser)
                            self._next_quiet_socket_sync_ts = now + self.defaults.session_sync_interval_sec
                            if not sync_ok and self.defaults.session_sync_fail_hard:
                                self._websocket_sync_failed = True
                                break

                receive_task = asyncio.create_task(receive_loop())
                heartbeat_task = asyncio.create_task(heartbeat_loop())
                done, pending = await asyncio.wait(
                    {receive_task, heartbeat_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in pending:
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                for task in done:
                    task.result()

                self.metrics.last_close_code = getattr(ws, "close_code", None)
                self.metrics.last_close_reason = getattr(ws, "close_reason", None)
        except Exception as e:
            self.logger.error(f"WebSocket session error: {e}")

    def run(self) -> None:
        """Thread entry point - run websocket monitor."""
        if not self.is_configured():
            self.logger.warning(
                "WebSocket monitor: NOT CONFIGURED (no valid session token)"
            )
            return

        backoff = self.BASE_BACKOFF
        while not self._shutdown_event.is_set():
            try:
                asyncio.run(self._websocket_session())
                if self._websocket_sync_failed:
                    break
                backoff = min(
                    self.MAX_BACKOFF,
                    backoff + random.uniform(0, self.RECONNECT_JITTER_MAX),
                )
                self._shutdown_event.wait(backoff)
            except Exception as e:
                self.logger.error(f"WebSocket monitor crashed: {e}")
                self._shutdown_event.wait(5)

    def stop(self) -> None:
        self._shutdown_event.set()

    def get_status(self) -> str:
        return "Live" if self.metrics.connected_at_ts else "Disconnected"
