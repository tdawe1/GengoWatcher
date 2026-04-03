import asyncio
import json
import random
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import websockets

from .config import PLACEHOLDER_CONFIG_VALUES

DEFAULT_BROWSER_DEBUG_URL = "http://127.0.0.1:9222"
PRIMARY_GENGO_COOKIE_NAMES = (
    "myG_myGSession_",
    "my_gengo_session",
    "myG_rdsessID",
)
GENGO_LOCAL_STORAGE_USER_KEY = "userKey"
DEFAULT_GENGO_ORIGIN = "https://gengo.com"
GENGO_REALTIME_PATH = "/t/jobs/status/available/realtime"
GENGO_SUMMARY_PATH = "/t/dashboard"
GENGO_REALTIME_URL = f"{DEFAULT_GENGO_ORIGIN}{GENGO_REALTIME_PATH}"
GENGO_SUMMARY_URL = f"{DEFAULT_GENGO_ORIGIN}{GENGO_SUMMARY_PATH}"
DEFAULT_ACCEPT_LANGUAGE = "en-GB,en-US;q=0.9,en;q=0.8"
DEFAULT_CDP_RECEIVE_TIMEOUT_SEC = 5
BROWSER_ACTIVITY_DESCRIPTIONS = {
    "reload": "reloading the realtime dashboard",
    "summary_roundtrip": "opening the summary dashboard and returning to realtime",
    "job_roundtrip": "opening a visible job details page and returning to realtime",
}


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


def select_gengo_target(
    targets: list[dict[str, Any]],
    preferred_url_fragments: tuple[str, ...] = (),
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for target in targets:
        if target.get("type") != "page":
            continue
        raw_url = str(target.get("url", ""))
        parsed = urlparse(raw_url)
        hostname = parsed.hostname or ""
        if not (
            hostname == "gengo.com"
            or hostname.endswith(".gengo.com")
        ):
            continue
        if not target.get("webSocketDebuggerUrl"):
            continue
        candidates.append(target)
    for fragment in preferred_url_fragments:
        for target in candidates:
            if fragment in str(target.get("url", "")):
                return target
    if candidates:
        return candidates[0]
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
    target = select_gengo_target(
        _load_cdp_targets(normalized_debug_url),
        preferred_url_fragments=(GENGO_REALTIME_PATH, GENGO_SUMMARY_PATH),
    )
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


async def _evaluate_expression(
    websocket,
    expression: str,
    *,
    call_id: int,
    expected_type: str | None = None,
) -> Any:
    result = await _cdp_call(
        websocket,
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        },
        call_id=call_id,
    )
    return _extract_runtime_value(result, expected_type=expected_type)


async def _wait_for_location_contains(
    websocket,
    fragment: str,
    *,
    call_id_start: int,
    attempts: int = 12,
    sleep_sec: float = 0.35,
) -> tuple[str, int]:
    call_id = call_id_start
    last_location = ""
    for _ in range(attempts):
        try:
            location = await _evaluate_expression(
                websocket,
                "location.href || ''",
                call_id=call_id,
                expected_type="string",
            )
            last_location = str(location or "")
        except BrowserSessionError:
            last_location = ""
        call_id += 1
        if fragment in last_location:
            return last_location, call_id
        await asyncio.sleep(sleep_sec)
    return last_location, call_id


def describe_browser_activity_action(action: str) -> str:
    return BROWSER_ACTIVITY_DESCRIPTIONS.get(action, action.replace("_", " "))


def _choose_browser_activity_action(
    *,
    job_href: str,
    previous_action: str | None = None,
) -> str:
    weighted_actions: list[tuple[str, float]] = [
        ("summary_roundtrip", 0.55),
        ("reload", 0.15),
    ]
    if job_href:
        weighted_actions.append(("job_roundtrip", 0.30))

    if previous_action:
        filtered_actions = [
            (name, weight) for name, weight in weighted_actions if name != previous_action
        ]
        if filtered_actions:
            weighted_actions = filtered_actions

    actions = [name for name, _weight in weighted_actions]
    weights = [weight for _name, weight in weighted_actions]
    return random.choices(actions, weights=weights, k=1)[0]


async def refresh_browser_page_activity(
    debug_url: str | None = None,
    *,
    action: str = "auto",
    previous_action: str | None = None,
) -> str:
    normalized_debug_url = _normalize_debug_url(debug_url)
    target = select_gengo_target(
        _load_cdp_targets(normalized_debug_url),
        preferred_url_fragments=(GENGO_REALTIME_PATH, GENGO_SUMMARY_PATH),
    )
    websocket_url = str(target.get("webSocketDebuggerUrl", "")).strip()
    if not websocket_url:
        raise BrowserSessionError(
            "Selected gengo.com page target has no CDP websocket URL"
        )

    async with websockets.connect(websocket_url, max_size=5_000_000) as websocket:
        call_id = 1
        await _cdp_call(websocket, "Page.enable", call_id=call_id)
        call_id += 1
        page_state = await _evaluate_expression(
            websocket,
            (
                "(() => ({"
                "href: location.href || '',"
                "jobHref: (document.querySelector('a[href*=\"/jobs/details/\"]')?.href || '')"
                "}))()"
            ),
            call_id=call_id,
            expected_type="object",
        )
        call_id += 1

        if not isinstance(page_state, dict):
            raise BrowserSessionError("Browser page state did not return an object")

        job_href = str(page_state.get("jobHref", "") or "").strip()
        if action == "auto":
            action = _choose_browser_activity_action(
                job_href=job_href,
                previous_action=previous_action,
            )

        if action == "reload":
            await _cdp_call(
                websocket,
                "Page.reload",
                {"ignoreCache": False},
                call_id=call_id,
            )
            call_id += 1
            await _wait_for_location_contains(
                websocket,
                "gengo.com",
                call_id_start=call_id,
            )
            return "reload"

        if action == "job_roundtrip" and job_href:
            await _cdp_call(
                websocket,
                "Page.navigate",
                {"url": job_href},
                call_id=call_id,
            )
            call_id += 1
            _location, call_id = await _wait_for_location_contains(
                websocket,
                "/t/jobs/details/",
                call_id_start=call_id,
            )
            await asyncio.sleep(0.6)
            await _cdp_call(
                websocket,
                "Page.navigate",
                {"url": GENGO_REALTIME_URL},
                call_id=call_id,
            )
            call_id += 1
            await _wait_for_location_contains(
                websocket,
                GENGO_REALTIME_PATH,
                call_id_start=call_id,
            )
            return "job_roundtrip"

        await _cdp_call(
            websocket,
            "Page.navigate",
            {"url": GENGO_SUMMARY_URL},
            call_id=call_id,
        )
        call_id += 1
        _location, call_id = await _wait_for_location_contains(
            websocket,
            GENGO_SUMMARY_PATH,
            call_id_start=call_id,
        )
        await asyncio.sleep(0.6)
        await _cdp_call(
            websocket,
            "Page.navigate",
            {"url": GENGO_REALTIME_URL},
            call_id=call_id,
        )
        call_id += 1
        await _wait_for_location_contains(
            websocket,
            GENGO_REALTIME_PATH,
            call_id_start=call_id,
        )
        return "summary_roundtrip"


def refresh_browser_page_activity_sync(
    debug_url: str | None = None,
    *,
    action: str = "auto",
    previous_action: str | None = None,
) -> str:
    return asyncio.run(
        refresh_browser_page_activity(
            debug_url=debug_url,
            action=action,
            previous_action=previous_action,
        )
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
    normalized_user_key = str(user_key or "").strip()
    if normalized_user_key and normalized_user_key not in PLACEHOLDER_CONFIG_VALUES:
        payload["user_key"] = normalized_user_key
    return payload
