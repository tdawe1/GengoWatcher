import asyncio
import json
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
GENGO_LOCAL_STORAGE_USER_KEY = "userKey"
DEFAULT_GENGO_ORIGIN = "https://gengo.com"
DEFAULT_ACCEPT_LANGUAGE = "en-GB,en-US;q=0.9,en;q=0.8"
DEFAULT_CDP_RECEIVE_TIMEOUT_SEC = 5


class BrowserSessionError(RuntimeError):
    """Raised when the browser session token cannot be retrieved."""


@dataclass(frozen=True)
class BrowserSessionSnapshot:
    session_token: str
    user_key: str = ""
    user_agent: str = ""
    accept_language: str = ""
    origin: str = DEFAULT_GENGO_ORIGIN
    target_url: str = ""
    target_title: str = ""


def _normalize_debug_url(debug_url: str | None) -> str:
    return (debug_url or DEFAULT_BROWSER_DEBUG_URL).rstrip("/")


def _load_cdp_targets(debug_url: str) -> list[dict[str, Any]]:
    parsed = urlparse(debug_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            f"unsupported browser debug URL scheme for CDP target fetch: {parsed.scheme}"
        )
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
    receive_timeout_sec: float = DEFAULT_CDP_RECEIVE_TIMEOUT_SEC,
) -> dict[str, Any]:
    await websocket.send(
        json.dumps({"id": call_id, "method": method, "params": params or {}})
    )
    while True:
        try:
            raw_message = await asyncio.wait_for(
                websocket.recv(),
                timeout=receive_timeout_sec,
            )
        except asyncio.TimeoutError as exc:
            raise BrowserSessionError(
                f"CDP call timed out waiting for response: method={method} call_id={call_id}"
            ) from exc
        message = json.loads(raw_message)
        if message.get("id") != call_id:
            continue
        if "error" in message:
            raise BrowserSessionError(str(message["error"]))
        return message.get("result", {})


def _extract_runtime_value(
    evaluation: dict[str, Any],
    *,
    expected_type: str | None = None,
) -> Any:
    if "exceptionDetails" in evaluation:
        raise BrowserSessionError(str(evaluation["exceptionDetails"]))

    runtime_result = evaluation.get("result")
    if not isinstance(runtime_result, dict):
        raise BrowserSessionError("Browser evaluation did not return a runtime result")

    value = runtime_result.get("value")
    if expected_type and runtime_result.get("type") != expected_type:
        raise BrowserSessionError(
            f"Browser evaluation returned unexpected type {runtime_result.get('type')}"
        )
    return value


async def fetch_browser_session_snapshot(
    debug_url: str | None = None,
    cookie_name: str | tuple[str, ...] = PRIMARY_GENGO_COOKIE_NAMES,
) -> BrowserSessionSnapshot:
    normalized_debug_url = _normalize_debug_url(debug_url)
    target = select_gengo_target(_load_cdp_targets(normalized_debug_url))
    websocket_url = str(target.get("webSocketDebuggerUrl", "")).strip()
    if not websocket_url:
        raise BrowserSessionError(
            "Selected gengo.com page target has no CDP websocket URL"
        )

    async with websockets.connect(websocket_url, max_size=5_000_000) as websocket:
        cookie_result = await _cdp_call(
            websocket,
            "Network.getCookies",
            {"urls": [DEFAULT_GENGO_ORIGIN]},
            call_id=1,
        )
        runtime_result = await _cdp_call(
            websocket,
            "Runtime.evaluate",
            {
                "expression": (
                    "(() => ({"
                    f'userKey: window.localStorage.getItem("{GENGO_LOCAL_STORAGE_USER_KEY}") || "",'
                    'userAgent: navigator.userAgent || "",'
                    'acceptLanguage: (Array.isArray(navigator.languages) && navigator.languages.length'
                    ' ? navigator.languages.join(",") : (navigator.language || "")),'
                    'origin: location.origin || "",'
                    'url: location.href || "",'
                    'title: document.title || "",'
                    "}))()"
                ),
                "returnByValue": True,
                "awaitPromise": True,
            },
            call_id=2,
        )

    cookies = cookie_result.get("cookies")
    if not isinstance(cookies, list):
        raise BrowserSessionError("Browser did not return a cookie list")

    session_token = extract_cookie_value(cookies, cookie_name=cookie_name)
    page_state = _extract_runtime_value(runtime_result, expected_type="object")
    if not isinstance(page_state, dict):
        raise BrowserSessionError("Browser page state did not return an object")

    return BrowserSessionSnapshot(
        session_token=session_token,
        user_key=str(page_state.get("userKey", "") or "").strip(),
        user_agent=str(page_state.get("userAgent", "") or "").strip(),
        accept_language=str(page_state.get("acceptLanguage", "") or "").strip(),
        origin=str(page_state.get("origin", "") or DEFAULT_GENGO_ORIGIN).strip(),
        target_url=str(page_state.get("url", "") or target.get("url", "")).strip(),
        target_title=str(page_state.get("title", "") or "").strip(),
    )


async def fetch_browser_session_token(
    debug_url: str | None = None,
    cookie_name: str | tuple[str, ...] = PRIMARY_GENGO_COOKIE_NAMES,
) -> str:
    snapshot = await fetch_browser_session_snapshot(
        debug_url=debug_url,
        cookie_name=cookie_name,
    )
    return snapshot.session_token


def fetch_browser_session_snapshot_sync(
    debug_url: str | None = None,
    cookie_name: str | tuple[str, ...] = PRIMARY_GENGO_COOKIE_NAMES,
) -> BrowserSessionSnapshot:
    return asyncio.run(
        fetch_browser_session_snapshot(debug_url=debug_url, cookie_name=cookie_name)
    )


def fetch_browser_session_token_sync(
    debug_url: str | None = None,
    cookie_name: str | tuple[str, ...] = PRIMARY_GENGO_COOKIE_NAMES,
) -> str:
    return asyncio.run(
        fetch_browser_session_token(debug_url=debug_url, cookie_name=cookie_name)
    )


def build_browser_aligned_websocket_headers(
    *,
    session_token: str,
    user_agent: str = "",
    origin: str = DEFAULT_GENGO_ORIGIN,
    accept_language: str = "",
) -> dict[str, str]:
    headers = {
        "Origin": origin or DEFAULT_GENGO_ORIGIN,
    }
    if user_agent:
        headers["User-Agent"] = user_agent
    if accept_language:
        headers["Accept-Language"] = accept_language
    return headers


def build_websocket_auth_payload(
    *,
    user_id: Any,
    session_token: str,
    user_key: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user_id": user_id,
        "user_session": session_token,
    }
    if str(user_key or "").strip():
        payload["user_key"] = str(user_key).strip()
    return payload
