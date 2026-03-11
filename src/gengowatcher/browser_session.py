import asyncio
import json
import random
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import websockets

DEFAULT_BROWSER_DEBUG_URL = "http://127.0.0.1:9222"
PRIMARY_GENGO_COOKIE_NAMES = (
    "myG_myGSession_",
    "my_gengo_session",
    "myG_rdsessID",
)


class BrowserSessionError(RuntimeError):
    """Raised when the browser session token cannot be retrieved."""


def _normalize_debug_url(debug_url: str | None) -> str:
    return (debug_url or DEFAULT_BROWSER_DEBUG_URL).rstrip("/")


def _load_cdp_targets(debug_url: str) -> list[dict[str, Any]]:
    with urllib.request.urlopen(f"{debug_url}/json/list", timeout=5) as response:
        return json.load(response)


def select_gengo_target(targets: list[dict[str, Any]]) -> dict[str, Any]:
    for target in targets:
        if target.get("type") != "page":
            continue
        if "gengo.com" not in str(target.get("url", "")):
            continue
        if target.get("webSocketDebuggerUrl"):
            return target
    raise BrowserSessionError("No open gengo.com page target found in browser")


def extract_cookie_value(
    cookies: list[dict[str, Any]],
    cookie_name: str | tuple[str, ...] = PRIMARY_GENGO_COOKIE_NAMES,
) -> str:
    cookie_names = (
        (cookie_name,)
        if isinstance(cookie_name, str)
        else tuple(str(name) for name in cookie_name)
    )
    for expected_name in cookie_names:
        for cookie in cookies:
            if cookie.get("name") != expected_name:
                continue
            value = str(cookie.get("value", "")).strip()
            if value:
                return value
    raise BrowserSessionError(
        f"None of the session cookies {cookie_names} were found for gengo.com"
    )


async def _cdp_call(
    websocket,
    method: str,
    params: dict[str, Any] | None = None,
    call_id: int = 1,
) -> dict[str, Any]:
    await websocket.send(
        json.dumps({"id": call_id, "method": method, "params": params or {}})
    )
    while True:
        raw_message = await websocket.recv()
        message = json.loads(raw_message)
        if message.get("id") != call_id:
            continue
        if "error" in message:
            raise BrowserSessionError(str(message["error"]))
        return message.get("result", {})


async def fetch_browser_session_token(
    debug_url: str | None = None,
    cookie_name: str | tuple[str, ...] = PRIMARY_GENGO_COOKIE_NAMES,
) -> str:
    normalized_debug_url = _normalize_debug_url(debug_url)
    target = select_gengo_target(_load_cdp_targets(normalized_debug_url))
    websocket_url = str(target.get("webSocketDebuggerUrl", "")).strip()
    if not websocket_url:
        raise BrowserSessionError(
            "Selected gengo.com page target has no CDP websocket URL"
        )

    async with websockets.connect(websocket_url, max_size=5_000_000) as websocket:
        result = await _cdp_call(
            websocket,
            "Network.getCookies",
            {"urls": ["https://gengo.com"]},
        )

    cookies = result.get("cookies")
    if not isinstance(cookies, list):
        raise BrowserSessionError("Browser did not return a cookie list")
    return extract_cookie_value(cookies, cookie_name=cookie_name)


def fetch_browser_session_token_sync(
    debug_url: str | None = None,
    cookie_name: str | tuple[str, ...] = PRIMARY_GENGO_COOKIE_NAMES,
) -> str:
    return asyncio.run(
        fetch_browser_session_token(debug_url=debug_url, cookie_name=cookie_name)
    )
