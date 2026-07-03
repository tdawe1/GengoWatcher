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
import sys
import time
from pathlib import Path
from typing import Optional

import websockets
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .browser_session import (
    GENGO_REALTIME_URL,
    BrowserSessionError,
    build_browser_aligned_websocket_headers,
    fetch_browser_session_token_sync,
)
from .config import AppConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GengoRealtimeGateway:
    """Standalone gateway - connects to Gengo, emits events via file/Redis."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.running = False
        self._shutdown_event = asyncio.Event()
        self._last_event: Optional[dict] = None
        self._event_file: Optional[Path] = None

    def _get_event_file(self) -> Path:
        cache_dir = Path.home() / ".cache" / "gengowatcher"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / "gateway_events.jsonl"

    def _build_headers(self) -> dict:
        debug_url = self.config.get("WebSocket", "browser_debug_url")
        session_token = ""
        
        if debug_url:
            try:
                token = fetch_browser_session_token_sync(str(debug_url))
                if token:
                    session_token = token
                    logger.info("Fetched live session from browser")
            except Exception as e:
                logger.warning(f"Browser extract failed: {e}")
        
        if not session_token:
            session_token = str(self.config.get("WebSocket", "user_session") or "")
            if session_token:
                logger.info("Using configured session token")

        user_agent = self.config.get("Network", "browser_user_agent") or \
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
        accept_language = self.config.get("Network", "browser_accept_language") or \
            "en-GB,en-US;q=0.9,en;q=0.8"

        return build_browser_aligned_websocket_headers(
            session_token=session_token,
            user_agent=user_agent,
            origin="https://gengo.com",
            accept_language=accept_language,
        )

    def _emit(self, event_type: str, data: dict) -> None:
        event = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
        }
        self._last_event = event
        # Write to file for TUI polling
        try:
            with self._get_event_file().open("a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as e:
            logger.warning(f"File emit failed: {e}")

    async def run(self) -> None:
        self.running = True
        logger.info("Gengo Realtime Gateway started")

        headers = self._build_headers()
        if not headers.get("Cookie"):
            logger.warning("No session token - authentication will fail")

        backoff = 5.0
        while not self._shutdown_event.is_set():
            try:
                ws_url = self.config.get("WebSocket", "wss_url") or GENGO_REALTIME_URL
                async with websockets.connect(
                    ws_url,
                    additional_headers=headers,
                    open_timeout=20,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    logger.info(f"Connected to {ws_url}")
                    backoff = 5.0

                    user_id = self.config.get("WebSocket", "user_id", "")
                    # Extract session token from Cookie header (format: myG_myGSession_=TOKEN; myG_rdsessID=TOKEN)
                    cookie = headers.get("Cookie", "")
                    session = ""
                    if "myG_myGSession_=" in cookie:
                        session = cookie.split("myG_myGSession_=")[1].split(";")[0]
                    auth = {"user_id": user_id, "user_session": session}
                    await ws.send(json.dumps(auth))

                    async for msg in ws:
                        if self._shutdown_event.is_set():
                            break
                        try:
                            data = json.loads(msg)
                            if data.get("type") == "available_collection":
                                for job in data.get("data", []):
                                    self._emit("job", job)
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
api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

_gateway: Optional[GengoRealtimeGateway] = None

@api.get("/events/latest")
async def latest():
    global _gateway
    if _gateway is None or _gateway._last_event is None:
        raise HTTPException(503, "Gateway not connected")
    return _gateway._last_event

@api.get("/health")
async def health():
    return {"status": "ok", "running": _gateway.running if _gateway else False}


async def run_gateway(config_path: Optional[str] = None):
    global _gateway

    config = AppConfig() if config_path is None else AppConfig(str(config_path))
    
    _gateway = GengoRealtimeGateway(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: _gateway._shutdown_event.set())

    # Start both WebSocket client AND HTTP API server concurrently
    import uvicorn
    
    server = uvicorn.Server(uvicorn.Config(
        api,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    ))
    
    # Run both tasks
    await asyncio.gather(
        _gateway.run(),
        server.serve(),
    )


def main():
    asyncio.run(run_gateway(sys.argv[1] if len(sys.argv) > 1 else None))


if __name__ == "__main__":
    main()