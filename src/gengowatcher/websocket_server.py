#!/usr/bin/env python3
"""
Standalone WebSocket Gateway for GengoWatcher

Architecture:
- This process: Connects to Gengo realtime via WebSockets, mirrors browser headers
- TUI process: Connects via HTTP polling or Redis pub/sub
- Separation ensures UI never blocks on WebSocket I/O
"""

import asyncio
import json
import logging
import signal
import secrets
import sys
import time
from pathlib import Path

from websockets.asyncio.client import connect
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .browser_session import (
    build_browser_aligned_websocket_headers,
    fetch_browser_session_snapshot_sync,
    format_cookies_as_header,
)
from .browser_session_core import GENGO_REALTIME_URL
from .config import AppConfig, PLACEHOLDER_CONFIG_VALUES
from .websocket_monitor import WebSocketConfig

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
_WEBSOCKET_DEFAULTS = WebSocketConfig()


def _extract_session_token(cookie_header: str) -> str:
    cookies: dict[str, str] = {}
    for item in cookie_header.split(";"):
        name, separator, value = item.partition("=")
        if separator:
            cookies[name.strip()] = value.strip()

    for name in ("myG_myGSession_", "my_gengo_session"):
        if cookies.get(name):
            return cookies[name]
    return ""


class GengoRealtimeGateway:
    """Standalone gateway - connects to Gengo, emits events via file/Redis."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.running = False
        self._shutdown_event = asyncio.Event()
        self._last_event: dict | None = None
        self._event_file: Path | None = None

    def _get_event_file(self) -> Path:
        cache_dir = Path.home() / ".cache" / "gengowatcher"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / "gateway_events.jsonl"

    def _build_headers(self) -> dict:
        debug_url = self.config.get("WebSocket", "browser_debug_url")
        session_token = ""
        rd_session_id = ""
        cookie_header = ""
        user_agent = ""
        accept_language = ""

        if debug_url:
            try:
                snapshot = fetch_browser_session_snapshot_sync(str(debug_url))
                if snapshot.session_token:
                    session_token = snapshot.session_token
                    rd_session_id = snapshot.rd_session_id
                    cookie_header = format_cookies_as_header(snapshot.cookies)
                    user_agent = snapshot.user_agent
                    accept_language = snapshot.accept_language
                    logger.info("Fetched live session from browser")
            except Exception as e:
                logger.warning(f"Browser extract failed: {e}")

        if not session_token:
            session_token = str(self.config.get("WebSocket", "user_session") or "")
            if session_token:
                logger.info("Using configured session token")
        if not rd_session_id:
            rd_session_id = str(
                self.config.get("WebSocket", "rd_session_id") or ""
            )

        user_agent = user_agent or (
            self.config.get("Network", "browser_user_agent")
            or _WEBSOCKET_DEFAULTS.user_agent
        )
        accept_language = accept_language or (
            self.config.get("Network", "browser_accept_language")
            or _WEBSOCKET_DEFAULTS.accept_language
        )

        return build_browser_aligned_websocket_headers(
            session_token=session_token,
            rd_session_id=rd_session_id,
            user_agent=user_agent,
            origin="https://gengo.com",
            accept_language=accept_language,
            sec_gpc="1",
            cookie_header=cookie_header,
        )

    _MAX_EVENT_LOG_LINES = 5000

    def _emit(self, event_type: str, data: dict) -> None:
        event = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
        }
        self._last_event = event
        # Write to file for TUI polling (with size cap)
        try:
            event_file = self._get_event_file()
            with event_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
            # Cap file size: keep last N lines if file is too large
            if event_file.stat().st_size > 1_000_000:  # 1MB cap
                with event_file.open("r", encoding="utf-8") as f:
                    lines = f.readlines()
                temp_file = event_file.with_name(f".{event_file.name}.tmp")
                with temp_file.open("w", encoding="utf-8") as f:
                    f.writelines(lines[-self._MAX_EVENT_LOG_LINES :])
                temp_file.replace(event_file)
        except Exception as e:
            logger.warning(f"File emit failed: {e}")

    async def run(self) -> None:
        self.running = True
        logger.info("Gengo Realtime Gateway started")

        backoff = 5.0
        while not self._shutdown_event.is_set():
            try:
                # Build fresh headers each iteration for fresh session token
                headers = await asyncio.to_thread(self._build_headers)
                if not headers.get("Cookie"):
                    logger.warning(
                        "No session token - skipping Gengo realtime gateway connect"
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 1.5, 60.0)
                    continue
                ws_url = self.config.get("WebSocket", "wss_url") or GENGO_REALTIME_URL
                async with connect(
                    ws_url,
                    additional_headers=headers,
                    open_timeout=20,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    logger.info(f"Connected to {ws_url}")
                    backoff = 5.0

                    user_id = self.config.get("WebSocket", "user_id", "")
                    user_key = self.config.get("WebSocket", "user_key", "")
                    cookie = headers.get("Cookie", "")
                    session = _extract_session_token(cookie)
                    # Gengo's realtime WS expects the same field shape as the
                    # browser-aligned in-process monitor: userId / sessionToken /
                    # userKey. Sending user_id / user_session (snake_case) silently
                    # fails the handshake.
                    auth: dict[str, str] = {
                        "userId": str(user_id or ""),
                        "sessionToken": session,
                    }
                    if user_key:
                        auth["userKey"] = str(user_key)
                    await ws.send(json.dumps(auth))

                    async for msg in ws:
                        if self._shutdown_event.is_set():
                            break
                        try:
                            data = json.loads(msg)
                            if not isinstance(data, dict):
                                continue
                            if data.get("type") == "available_collection":
                                collection = data.get("collection")
                                jobs = (
                                    [collection]
                                    if isinstance(collection, dict)
                                    else data.get("data", [])
                                )
                                for job in jobs:
                                    await asyncio.to_thread(self._emit, "job", job)
                            self._last_event = data
                        except json.JSONDecodeError:
                            pass

            except Exception as e:
                logger.error(f"Gengo WS error: {e}")
                if not self._shutdown_event.is_set():
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 1.5, 60.0)

    def stop(self) -> None:
        self._shutdown_event.set()


# FastAPI for TUI to poll
api = FastAPI()
api.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_methods=["GET"],
    allow_headers=["Authorization"],
)

_gateway: GengoRealtimeGateway | None = None


def _extract_bearer_token(authorization: str | None) -> str:
    scheme, _, value = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not value:
        return ""
    return value.strip()


def _events_latest_authorized(request: Request) -> bool:
    if _gateway is None:
        return False
    expected = str(_gateway.config.get("WebServer", "auth_token", fallback="") or "")
    if not expected or expected in PLACEHOLDER_CONFIG_VALUES:
        return False
    supplied = _extract_bearer_token(request.headers.get("authorization"))
    return bool(supplied and secrets.compare_digest(supplied, expected))


@api.get("/events/latest")
async def latest(request: Request):
    global _gateway
    if not _events_latest_authorized(request):
        return Response(status_code=404)
    if _gateway is None or _gateway._last_event is None:
        raise HTTPException(503, "Gateway not connected")
    return _gateway._last_event


@api.get("/health")
async def health():
    return {"status": "ok", "running": _gateway.running if _gateway else False}


async def run_gateway(config_path: str | None = None):
    global _gateway

    config = AppConfig() if config_path is None else AppConfig(str(config_path))

    _gateway = GengoRealtimeGateway(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: _gateway._shutdown_event.set())

    # Start both WebSocket client AND HTTP API server concurrently
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(
            api,
            host="127.0.0.1",
            port=8000,
            log_level="info",
        )
    )

    # Run both tasks
    await asyncio.gather(
        _gateway.run(),
        server.serve(),
    )


def main():
    asyncio.run(run_gateway(sys.argv[1] if len(sys.argv) > 1 else None))


if __name__ == "__main__":
    main()
