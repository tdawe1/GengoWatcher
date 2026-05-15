import base64
import asyncio
import json
import logging
import random
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import websockets

from ._async_utils import run_coroutine_sync

logger = logging.getLogger(__name__)

DEFAULT_BROWSER_DEBUG_URL = "http://127.0.0.1:9222"
DEFAULT_FIREFOX_BIDI_PATH = "/session"
DEFAULT_GENGO_ORIGIN = "https://gengo.com"
GENGO_LOCAL_STORAGE_USER_KEY = "userKey"
GENGO_ACTIVITY_MARKER_STORAGE_KEY = "__gengowatcher_activity_marker"
GENGO_REALTIME_PATH = "/t/jobs/status/available/realtime"
GENGO_SUMMARY_PATH = "/t/dashboard"
GENGO_REALTIME_URL = f"{DEFAULT_GENGO_ORIGIN}{GENGO_REALTIME_PATH}"
GENGO_SUMMARY_URL = f"{DEFAULT_GENGO_ORIGIN}{GENGO_SUMMARY_PATH}"
DEFAULT_ACCEPT_LANGUAGE = "en-GB,en-US;q=0.9,en;q=0.8"
DEFAULT_CDP_RECEIVE_TIMEOUT_SEC = 5
PRIMARY_GENGO_COOKIE_NAMES = (
    "myG_myGSession_",
    "my_gengo_session",
    "myG_rdsessID",
)


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


@dataclass(frozen=True)
class BrowserDebugEndpoint:
    backend: str
    url: str


@dataclass(frozen=True)
class BrowserDebugTarget:
    backend: str
    target_id: str
    url: str
    title: str = ""
    target_type: str = ""
    actor: str = ""
    console_actor: str = ""


class _FirefoxBiDiSession:
    def __init__(self, websocket):
        self.websocket = websocket
        self._next_call_id = 1

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        receive_timeout_sec: float = DEFAULT_CDP_RECEIVE_TIMEOUT_SEC,
    ) -> dict[str, Any]:
        call_id = self._next_call_id
        self._next_call_id += 1
        return await _bidi_call(
            self.websocket,
            method,
            params=params,
            call_id=call_id,
            receive_timeout_sec=receive_timeout_sec,
        )


class _FirefoxRdpClient:
    _NOTIFICATION_TYPES = {
        "consoleAPICall",
        "lastPrivateContextExited",
        "networkEvent",
        "networkEventUpdate",
        "pageError",
        "tabDetached",
        "tabListChanged",
        "tabNavigated",
    }

    def __init__(self, websocket, hello_packet: dict[str, Any]):
        self.websocket = websocket
        self.hello_packet = hello_packet

    async def request(
        self,
        actor: str,
        packet_type: str,
        **payload: Any,
    ) -> dict[str, Any]:
        packet = {"to": actor, "type": packet_type}
        packet.update(payload)
        await self.websocket.send(json.dumps(packet))

        while True:
            try:
                raw_message = await asyncio.wait_for(
                    self.websocket.recv(),
                    timeout=DEFAULT_CDP_RECEIVE_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError as exc:
                raise BrowserSessionError(
                    "Firefox DevTools request timed out waiting for response: "
                    f"actor={actor} type={packet_type}"
                ) from exc
            try:
                response = json.loads(raw_message)
            except json.JSONDecodeError as exc:
                raise BrowserSessionError(
                    f"Failed to parse Firefox DevTools response as JSON: {exc}"
                ) from exc

            if response.get("from") != actor:
                continue
            if response.get("type") in self._NOTIFICATION_TYPES:
                continue
            if response.get("error"):
                detail = response.get("message") or response.get("error")
                raise BrowserSessionError(
                    str(detail or "unknown Firefox DevTools error")
                )
            return response


def _normalize_debug_url(debug_url: str | None) -> str:
    raw_url = str(debug_url or "").strip()
    if not raw_url:
        return DEFAULT_BROWSER_DEBUG_URL
    if "://" not in raw_url:
        if raw_url.startswith(":"):
            raw_url = f"127.0.0.1{raw_url}"
        if "/" not in raw_url and ":" not in raw_url:
            raw_url = f"{raw_url}:9222"
        raw_url = f"http://{raw_url}"
    return raw_url.rstrip("/")


def _looks_like_firefox_bidi_url(debug_url: str) -> bool:
    parsed = urlparse(debug_url)
    path = parsed.path.rstrip("/")
    return path == DEFAULT_FIREFOX_BIDI_PATH


def _looks_like_firefox_rdp_url(debug_url: str) -> bool:
    parsed = urlparse(debug_url)
    return parsed.scheme in {"ws", "wss"} and not _looks_like_firefox_bidi_url(
        debug_url
    )


def _firefox_bidi_url(debug_url: str | None) -> str:
    normalized_debug_url = _normalize_debug_url(debug_url)
    parsed = urlparse(normalized_debug_url)
    scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
    hostname = parsed.hostname or "127.0.0.1"
    if hostname == "localhost":
        hostname = "127.0.0.1"
    netloc = hostname
    if parsed.port is not None:
        netloc = f"{hostname}:{parsed.port}"
    return urlunparse((scheme, netloc, DEFAULT_FIREFOX_BIDI_PATH, "", "", ""))


def _resolve_browser_endpoint(debug_url: str | None) -> BrowserDebugEndpoint:
    normalized_debug_url = _normalize_debug_url(debug_url)
    parsed = urlparse(normalized_debug_url)
    if parsed.scheme not in {"http", "https", "ws", "wss"}:
        raise ValueError(
            f"unsupported browser debug URL scheme: {parsed.scheme or '(empty)'}"
        )

    if _looks_like_firefox_rdp_url(normalized_debug_url):
        return BrowserDebugEndpoint(
            backend="firefox-rdp",
            url=normalized_debug_url,
        )

    if _looks_like_firefox_bidi_url(normalized_debug_url):
        return BrowserDebugEndpoint(
            backend="firefox-bidi",
            url=_firefox_bidi_url(normalized_debug_url),
        )

    try:
        _load_cdp_targets(normalized_debug_url)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return BrowserDebugEndpoint(
            backend="firefox-bidi",
            url=_firefox_bidi_url(normalized_debug_url),
        )

    return BrowserDebugEndpoint(backend="chromium-cdp", url=normalized_debug_url)


def _load_cdp_targets(debug_url: str) -> list[dict[str, Any]]:
    parsed = urlparse(debug_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            f"unsupported browser debug URL scheme for CDP target fetch: {parsed.scheme}"
        )
    with urllib.request.urlopen(f"{debug_url}/json/list", timeout=5) as response:
        return json.load(response)


def _summarize_cdp_targets(targets: list[dict[str, Any]]) -> list[BrowserDebugTarget]:
    summarized: list[BrowserDebugTarget] = []
    for target in targets:
        summarized.append(
            BrowserDebugTarget(
                backend="chromium-cdp",
                target_id=str(target.get("id", "") or ""),
                url=str(target.get("url", "") or ""),
                title=str(target.get("title", "") or ""),
                target_type=str(target.get("type", "") or ""),
            )
        )
    return summarized


def _summarize_firefox_contexts(
    contexts: list[dict[str, Any]],
) -> list[BrowserDebugTarget]:
    summarized: list[BrowserDebugTarget] = []
    for context in contexts:
        summarized.append(
            BrowserDebugTarget(
                backend="firefox-bidi",
                target_id=str(context.get("context", "") or ""),
                url=str(context.get("url", "") or ""),
                title=str(context.get("title", "") or ""),
                target_type=str(context.get("userContext", "") or "context"),
            )
        )
    return summarized


def _summarize_firefox_tabs(tabs: list[dict[str, Any]]) -> list[BrowserDebugTarget]:
    summarized: list[BrowserDebugTarget] = []
    for tab in tabs:
        summarized.append(
            BrowserDebugTarget(
                backend="firefox-rdp",
                target_id=str(tab.get("outerWindowID", "") or ""),
                url=str(tab.get("url", "") or ""),
                title=str(tab.get("title", "") or ""),
                target_type=str(tab.get("type", "") or "tab"),
                actor=str(tab.get("actor", "") or ""),
                console_actor=str(tab.get("consoleActor", "") or ""),
            )
        )
    return summarized


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
        if not (hostname == "gengo.com" or hostname.endswith(".gengo.com")):
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
            value = _coerce_cookie_value(cookie.get("value", ""))
            if value:
                return value
    raise BrowserSessionError(
        f"None of the session cookies {cookie_names} were found for gengo.com"
    )


def _coerce_cookie_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return str(value or "").strip()

    value_type = str(value.get("type") or "")
    raw_value = value.get("value", "")
    if value_type == "string":
        return str(raw_value or "").strip()
    if value_type == "base64":
        try:
            return (
                base64.b64decode(str(raw_value or ""), validate=False)
                .decode("utf-8", errors="replace")
                .strip()
            )
        except (ValueError, TypeError):
            return ""
    return str(raw_value or "").strip()


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
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError as exc:
            raise BrowserSessionError(
                f"Failed to parse CDP response as JSON: {exc}"
            ) from exc
        if message.get("id") != call_id:
            continue
        if "error" in message:
            raise BrowserSessionError(str(message["error"]))
        return message.get("result", {})


async def _bidi_call(
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
                "BiDi call timed out waiting for response: "
                f"method={method} call_id={call_id}"
            ) from exc
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError as exc:
            raise BrowserSessionError(
                f"Failed to parse BiDi response as JSON: {exc}"
            ) from exc
        if message.get("id") != call_id:
            continue
        if message.get("type") == "error" or "error" in message:
            detail = message.get("message") or message.get("error")
            raise BrowserSessionError(str(detail or "unknown BiDi error"))
        if message.get("type") != "success":
            raise BrowserSessionError(
                f"Unexpected BiDi response type: {message.get('type')}"
            )
        return message.get("result", {})


def _extract_rdp_evaluation_value(packet: dict[str, Any]) -> Any:
    exception = packet.get("exception")
    if exception not in (None, {"type": "null"}):
        raise BrowserSessionError(str(packet.get("exceptionMessage") or exception))

    result = packet.get("result")
    if isinstance(result, dict):
        result_type = str(result.get("type") or "")
        if result_type == "longString":
            initial = str(result.get("initial") or "")
            total_length = int(result.get("length") or len(initial))
            if len(initial) < total_length:
                raise BrowserSessionError(
                    "Firefox DevTools returned a truncated long string result"
                )
            return initial
        if result_type in {"string", "number", "boolean", "bigint"}:
            return result.get("value")
        if result_type in {"null", "undefined"}:
            return None
    return result


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


def _extract_bidi_remote_value(remote_value: Any) -> Any:
    if not isinstance(remote_value, dict):
        return remote_value

    value_type = str(remote_value.get("type") or "")
    if value_type in {"string", "number", "boolean", "bigint"}:
        return remote_value.get("value")
    if value_type in {"null", "undefined"}:
        return None
    if value_type == "array":
        values = remote_value.get("value")
        if not isinstance(values, list):
            return []
        return [_extract_bidi_remote_value(item) for item in values]
    if value_type == "object":
        values = remote_value.get("value")
        if not isinstance(values, list):
            return {}
        output: dict[str, Any] = {}
        for pair in values:
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            raw_key, raw_value = pair
            key = (
                raw_key
                if isinstance(raw_key, str)
                else _extract_bidi_remote_value(raw_key)
            )
            output[str(key)] = _extract_bidi_remote_value(raw_value)
        return output
    return remote_value.get("value")


def _extract_bidi_evaluation_value(evaluation: dict[str, Any]) -> Any:
    result_type = evaluation.get("type")
    if result_type == "exception":
        details = evaluation.get("exceptionDetails") or {}
        if isinstance(details, dict):
            raise BrowserSessionError(str(details.get("text") or details))
        raise BrowserSessionError(str(details))
    if result_type != "success":
        raise BrowserSessionError(
            f"Unexpected BiDi evaluation result type: {result_type}"
        )
    return _extract_bidi_remote_value(evaluation.get("result"))


def _parse_json_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        raise BrowserSessionError(
            f"Expected serialized JSON string from browser evaluation, got {type(value).__name__}"
        )
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise BrowserSessionError(
            f"Failed to parse browser evaluation payload: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise BrowserSessionError("Browser evaluation payload was not an object")
    return parsed


def _javascript_string_literal(value: str) -> str:
    return json.dumps(value)


def _make_firefox_activity_marker() -> str:
    return f"gw-{random.randint(100_000, 999_999)}"


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


def select_gengo_context(
    contexts: list[dict[str, Any]],
    preferred_url_fragments: tuple[str, ...] = (),
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for context in contexts:
        raw_url = str(context.get("url", ""))
        parsed = urlparse(raw_url)
        hostname = parsed.hostname or ""
        if not (hostname == "gengo.com" or hostname.endswith(".gengo.com")):
            continue
        if not context.get("context"):
            continue
        candidates.append(context)
    for fragment in preferred_url_fragments:
        for context in candidates:
            if fragment in str(context.get("url", "")):
                return context
    if candidates:
        return candidates[0]
    raise BrowserSessionError("No open gengo.com browsing context found in browser")


@asynccontextmanager
async def _firefox_bidi_session(debug_url: str | None):
    websocket_url = _firefox_bidi_url(debug_url)
    async with websockets.connect(websocket_url, max_size=5_000_000) as websocket:
        session = _FirefoxBiDiSession(websocket)
        await session.call(
            "session.new",
            {"capabilities": {}},
        )
        try:
            yield session
        finally:
            try:
                await session.call("session.end", {})
            except Exception as exc:
                logger.debug(
                    "Failed to end Firefox BiDi session: %s",
                    exc,
                    exc_info=True,
                )


async def _firefox_get_gengo_context(
    session: _FirefoxBiDiSession,
    *,
    preferred_url_fragments: tuple[str, ...] = (),
) -> dict[str, Any]:
    tree = await session.call("browsingContext.getTree", {})
    contexts = tree.get("contexts")
    if not isinstance(contexts, list):
        raise BrowserSessionError("Browser did not return a browsing context tree")
    return select_gengo_context(
        contexts,
        preferred_url_fragments=preferred_url_fragments,
    )


async def _firefox_evaluate_json(
    session: _FirefoxBiDiSession,
    context_id: str,
    expression: str,
) -> dict[str, Any]:
    evaluation = await session.call(
        "script.evaluate",
        {
            "expression": expression,
            "target": {"context": context_id},
            "awaitPromise": True,
        },
    )
    return _parse_json_object(_extract_bidi_evaluation_value(evaluation))


async def _open_firefox_rdp_client(debug_url: str | None) -> _FirefoxRdpClient:
    websocket = await websockets.connect(
        _normalize_debug_url(debug_url), max_size=5_000_000
    )
    try:
        raw_message = await asyncio.wait_for(websocket.recv(), timeout=5)
        hello_packet = json.loads(raw_message)
    except asyncio.TimeoutError as exc:
        await websocket.close()
        raise BrowserSessionError(
            "Firefox DevTools socket opened but did not send an RDP hello packet. "
            "Check devtools.debugger.prompt-connection=false and "
            "devtools.debugger.remote-websocket=true, then restart Firefox."
        ) from exc
    except Exception:
        await websocket.close()
        raise

    if not isinstance(hello_packet, dict) or hello_packet.get("from") != "root":
        await websocket.close()
        raise BrowserSessionError("Firefox DevTools did not send a root hello packet")
    return _FirefoxRdpClient(websocket, hello_packet)


async def _firefox_rdp_list_tabs(client: _FirefoxRdpClient) -> dict[str, Any]:
    return await client.request("root", "listTabs")


def select_gengo_tab(
    tabs: list[dict[str, Any]],
    preferred_url_fragments: tuple[str, ...] = (),
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for tab in tabs:
        raw_url = str(tab.get("url", ""))
        parsed = urlparse(raw_url)
        hostname = parsed.hostname or ""
        if not (hostname == "gengo.com" or hostname.endswith(".gengo.com")):
            continue
        candidates.append(tab)

    for fragment in preferred_url_fragments:
        for tab in candidates:
            if fragment in str(tab.get("url", "")):
                return tab
    if candidates:
        return candidates[0]
    raise BrowserSessionError("No open gengo.com tab found in Firefox DevTools session")


def _firefox_tab_console_actor(tab: dict[str, Any]) -> str:
    console_actor = str(tab.get("consoleActor") or "").strip()
    if not console_actor:
        raise BrowserSessionError(
            "Firefox DevTools did not expose a console actor for the gengo.com tab"
        )
    return console_actor


async def _firefox_rdp_resolve_tab(
    client: _FirefoxRdpClient,
    tab: dict[str, Any],
) -> dict[str, Any]:
    console_actor = str(tab.get("consoleActor") or "").strip()
    if console_actor:
        return tab

    descriptor_actor = str(tab.get("actor") or "").strip()
    if not descriptor_actor:
        return tab

    target_response = await client.request(descriptor_actor, "getTarget")
    frame = target_response.get("frame")
    if not isinstance(frame, dict):
        return tab

    resolved_tab = dict(tab)
    resolved_tab["targetActor"] = str(frame.get("actor") or "").strip()
    resolved_tab["consoleActor"] = str(frame.get("consoleActor") or "").strip()
    resolved_tab["innerWindowId"] = frame.get("innerWindowId")
    resolved_tab["browsingContextID"] = frame.get(
        "browsingContextID",
        resolved_tab.get("browsingContextID"),
    )
    if frame.get("title"):
        resolved_tab["title"] = frame["title"]
    if frame.get("url"):
        resolved_tab["url"] = frame["url"]
    return resolved_tab


async def _firefox_rdp_get_browser_console_actor(client: _FirefoxRdpClient) -> str:
    process_response = await client.request("root", "getProcess", id=0)
    process_descriptor = process_response.get("processDescriptor")
    if not isinstance(process_descriptor, dict):
        raise BrowserSessionError(
            "Firefox DevTools did not return the parent process descriptor"
        )

    descriptor_actor = str(process_descriptor.get("actor") or "").strip()
    if not descriptor_actor:
        raise BrowserSessionError(
            "Firefox DevTools parent process descriptor did not include an actor"
        )

    target_response = await client.request(descriptor_actor, "getTarget")
    process_target = target_response.get("process")
    if not isinstance(process_target, dict):
        raise BrowserSessionError(
            "Firefox DevTools did not return the parent process target"
        )

    console_actor = str(process_target.get("consoleActor") or "").strip()
    if not console_actor:
        raise BrowserSessionError(
            "Firefox DevTools did not expose the browser console actor"
        )
    return console_actor


async def _firefox_rdp_get_gengo_tab(
    client: _FirefoxRdpClient,
    *,
    preferred_url_fragments: tuple[str, ...] = (),
    actor_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tabs_response = await _firefox_rdp_list_tabs(client)
    tabs = tabs_response.get("tabs")
    if not isinstance(tabs, list):
        raise BrowserSessionError("Firefox DevTools did not return a tab list")

    if actor_id:
        for tab in tabs:
            if str(tab.get("actor") or "").strip() != actor_id:
                continue
            raw_url = str(tab.get("url", ""))
            hostname = urlparse(raw_url).hostname or ""
            if hostname == "gengo.com" or hostname.endswith(".gengo.com"):
                return await _firefox_rdp_resolve_tab(client, tab), tabs_response

    tab = select_gengo_tab(
        tabs,
        preferred_url_fragments=preferred_url_fragments,
    )
    return await _firefox_rdp_resolve_tab(client, tab), tabs_response


async def _firefox_rdp_wait_for_evaluation_result(
    client: _FirefoxRdpClient,
    actor: str,
) -> dict[str, Any]:
    while True:
        try:
            raw_message = await asyncio.wait_for(
                client.websocket.recv(),
                timeout=DEFAULT_CDP_RECEIVE_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError as exc:
            raise BrowserSessionError(
                "Firefox DevTools evaluation timed out waiting for result"
            ) from exc

        try:
            response = json.loads(raw_message)
        except json.JSONDecodeError as exc:
            raise BrowserSessionError(
                f"Failed to parse Firefox DevTools evaluation result as JSON: {exc}"
            ) from exc

        if response.get("from") != actor:
            continue
        if response.get("type") in _FirefoxRdpClient._NOTIFICATION_TYPES:
            continue
        if response.get("type") != "evaluationResult":
            continue
        if response.get("error"):
            detail = response.get("message") or response.get("error")
            raise BrowserSessionError(
                str(detail or "unknown Firefox DevTools evaluation error")
            )
        return response


def _extract_rdp_async_evaluation_value(packet: dict[str, Any]) -> Any:
    if packet.get("hasException"):
        raise BrowserSessionError(
            str(packet.get("exceptionMessage") or packet.get("exception") or "")
        )

    result = packet.get("result")
    if isinstance(result, dict):
        result_type = str(result.get("type") or "")
        if result_type == "longString":
            initial = str(result.get("initial") or "")
            total_length = int(result.get("length") or len(initial))
            if len(initial) < total_length:
                raise BrowserSessionError(
                    "Firefox DevTools returned a truncated long string result"
                )
            return initial
        if result_type in {"string", "number", "boolean", "bigint"}:
            return result.get("value")
        if result_type in {"null", "undefined"}:
            return None
    return result


async def _firefox_rdp_evaluate_json(
    client: _FirefoxRdpClient,
    actor: str,
    expression: str,
    *,
    inner_window_id: int | None = None,
) -> dict[str, Any]:
    await client.request(
        actor,
        "evaluateJSAsync",
        text=expression,
        frameActor=None,
        url=None,
        selectedNodeActor=None,
        selectedObjectActor=None,
        innerWindowID=inner_window_id,
        mapped=None,
        eager=False,
        disableBreaks=True,
        preferConsoleCommandsOverLocalSymbols=False,
        evalInTracer=False,
    )
    packet = await _firefox_rdp_wait_for_evaluation_result(client, actor)
    return _parse_json_object(_extract_rdp_async_evaluation_value(packet))


async def _open_url_in_firefox_rdp(debug_url: str | None, url: str) -> str:
    client = await _open_firefox_rdp_client(debug_url)
    try:
        result = await _firefox_rdp_evaluate_json(
            client,
            await _firefox_rdp_get_browser_console_actor(client),
            _firefox_open_tab_expression(url),
        )
    finally:
        await client.websocket.close()

    if not result.get("opened"):
        reason = str(result.get("reason") or "unknown error")
        raise BrowserSessionError(f"Firefox did not open {url}: {reason}")
    return str(result.get("url") or url)


def _firefox_cookie_lookup_expression() -> str:
    return """(() => {
const names = ["myG_myGSession_", "my_gengo_session", "myG_rdsessID"];
for (const expectedName of names) {
  for (const cookie of Services.cookies.cookies) {
    const host = String(cookie.host || "");
    if (
      cookie.name === expectedName &&
      (host === "gengo.com" || host === ".gengo.com" || host.endsWith(".gengo.com"))
    ) {
      const value = String(cookie.value || "");
      if (value) {
        return JSON.stringify({ sessionToken: value });
      }
    }
  }
}
return JSON.stringify({ sessionToken: "" });
})()"""


def _firefox_page_state_expression() -> str:
    return (
        "JSON.stringify({"
        f'userKey: window.localStorage.getItem("{GENGO_LOCAL_STORAGE_USER_KEY}") || "",'
        'userAgent: navigator.userAgent || "",'
        "acceptLanguage: (Array.isArray(navigator.languages) && navigator.languages.length"
        ' ? navigator.languages.join(",") : (navigator.language || "")),'
        'origin: location.origin || "",'
        'url: location.href || "",'
        'title: document.title || "",'
        'readyState: document.readyState || "",'
        'jobHref: (document.querySelector(\'a[href*="/jobs/details/"]\')?.href || "")'
        "})"
    )


def _firefox_activity_state_expression() -> str:
    return (
        "JSON.stringify({"
        'href: location.href || "",'
        'readyState: document.readyState || "",'
        f'activityMarker: sessionStorage.getItem("{GENGO_ACTIVITY_MARKER_STORAGE_KEY}") || "",'
        'jobHref: (document.querySelector(\'a[href*="/jobs/details/"]\')?.href || "")'
        "})"
    )


def _firefox_queue_reload_expression(marker: str) -> str:
    marker_literal = _javascript_string_literal(marker)
    return (
        "(() => {"
        f"const marker = {marker_literal};"
        f'sessionStorage.setItem("{GENGO_ACTIVITY_MARKER_STORAGE_KEY}", marker);'
        "setTimeout(() => { location.reload(); }, 0);"
        "return JSON.stringify({ queued: true, marker });"
        "})()"
    )


def _firefox_queue_navigation_expression(url: str, marker: str) -> str:
    url_literal = _javascript_string_literal(url)
    marker_literal = _javascript_string_literal(marker)
    return (
        "(() => {"
        f"const targetUrl = {url_literal};"
        f"const marker = {marker_literal};"
        f'sessionStorage.setItem("{GENGO_ACTIVITY_MARKER_STORAGE_KEY}", marker);'
        "setTimeout(() => { location.href = targetUrl; }, 0);"
        "return JSON.stringify({ queued: true, marker, url: targetUrl });"
        "})()"
    )


def _firefox_open_tab_expression(url: str) -> str:
    url_literal = _javascript_string_literal(url)
    return (
        "(() => {"
        f"const targetUrl = {url_literal};"
        'const browserWindow = Services.wm.getMostRecentWindow("navigator:browser");'
        "if (!browserWindow || !browserWindow.gBrowser) {"
        'return JSON.stringify({opened: false, reason: "no_browser_window"});'
        "}"
        "if (typeof browserWindow.openTrustedLinkIn === 'function') {"
        "browserWindow.openTrustedLinkIn(targetUrl, 'tab', {"
        "inBackground: false, relatedToCurrent: false"
        "});"
        "} else {"
        "const tab = browserWindow.gBrowser.addTab(targetUrl, {"
        "triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()"
        "});"
        "browserWindow.gBrowser.selectedTab = tab;"
        "}"
        "browserWindow.focus();"
        "return JSON.stringify({opened: true, url: targetUrl});"
        "})()"
    )


async def _fetch_browser_session_snapshot_firefox_rdp(
    debug_url: str | None,
    _cookie_name: str | tuple[str, ...],
) -> BrowserSessionSnapshot:
    client = await _open_firefox_rdp_client(debug_url)
    try:
        tab, _tabs_response = await _firefox_rdp_get_gengo_tab(
            client,
            preferred_url_fragments=(GENGO_REALTIME_PATH, GENGO_SUMMARY_PATH),
        )
        page_state = await _firefox_rdp_evaluate_json(
            client,
            _firefox_tab_console_actor(tab),
            _firefox_page_state_expression(),
            inner_window_id=tab.get("innerWindowId"),
        )
        cookie_state = await _firefox_rdp_evaluate_json(
            client,
            await _firefox_rdp_get_browser_console_actor(client),
            _firefox_cookie_lookup_expression(),
        )
    finally:
        await client.websocket.close()

    session_token = str(cookie_state.get("sessionToken", "") or "").strip()
    if not session_token:
        raise BrowserSessionError("No Gengo session cookie found in Firefox")

    return BrowserSessionSnapshot(
        session_token=session_token,
        user_key=str(page_state.get("userKey", "") or "").strip(),
        user_agent=str(page_state.get("userAgent", "") or "").strip(),
        accept_language=str(page_state.get("acceptLanguage", "") or "").strip(),
        origin=str(page_state.get("origin", "") or DEFAULT_GENGO_ORIGIN).strip(),
        target_url=str(page_state.get("url", "") or tab.get("url", "")).strip(),
        target_title=str(page_state.get("title", "") or tab.get("title", "")).strip(),
    )


async def _fetch_browser_session_token_firefox_rdp(
    debug_url: str | None,
    _cookie_name: str | tuple[str, ...],
) -> str:
    client = await _open_firefox_rdp_client(debug_url)
    try:
        _tab, _tabs_response = await _firefox_rdp_get_gengo_tab(client)
        cookie_state = await _firefox_rdp_evaluate_json(
            client,
            await _firefox_rdp_get_browser_console_actor(client),
            _firefox_cookie_lookup_expression(),
        )
    finally:
        await client.websocket.close()

    session_token = str(cookie_state.get("sessionToken", "") or "").strip()
    if not session_token:
        raise BrowserSessionError("No Gengo session cookie found in Firefox")
    return session_token


async def _fetch_browser_session_snapshot_firefox_bidi(
    debug_url: str | None,
    cookie_name: str | tuple[str, ...],
) -> BrowserSessionSnapshot:
    async with _firefox_bidi_session(debug_url) as session:
        context = await _firefox_get_gengo_context(
            session,
            preferred_url_fragments=(GENGO_REALTIME_PATH, GENGO_SUMMARY_PATH),
        )
        context_id = str(context.get("context") or "").strip()
        if not context_id:
            raise BrowserSessionError("Selected gengo.com browsing context has no id")

        cookie_result = await session.call(
            "storage.getCookies",
            {
                "partition": {
                    "type": "context",
                    "context": context_id,
                }
            },
        )
        cookies = cookie_result.get("cookies")
        if not isinstance(cookies, list):
            raise BrowserSessionError("Browser did not return a cookie list")

        try:
            page_state = await _firefox_evaluate_json(
                session,
                context_id,
                (
                    "JSON.stringify({"
                    f'userKey: window.localStorage.getItem("{GENGO_LOCAL_STORAGE_USER_KEY}") || "",'
                    'userAgent: navigator.userAgent || "",'
                    "acceptLanguage: (Array.isArray(navigator.languages) && navigator.languages.length"
                    ' ? navigator.languages.join(",") : (navigator.language || "")),'
                    'origin: location.origin || "",'
                    'url: location.href || "",'
                    'title: document.title || "",'
                    "})"
                ),
            )
        except BrowserSessionError:
            page_state = {}

    session_token = extract_cookie_value(cookies, cookie_name=cookie_name)
    return BrowserSessionSnapshot(
        session_token=session_token,
        user_key=str(page_state.get("userKey", "") or "").strip(),
        user_agent=str(page_state.get("userAgent", "") or "").strip(),
        accept_language=str(page_state.get("acceptLanguage", "") or "").strip(),
        origin=str(page_state.get("origin", "") or DEFAULT_GENGO_ORIGIN).strip(),
        target_url=str(page_state.get("url", "") or context.get("url", "")).strip(),
        target_title=str(page_state.get("title", "") or "").strip(),
    )


async def _fetch_browser_session_token_firefox_bidi(
    debug_url: str | None,
    cookie_name: str | tuple[str, ...],
) -> str:
    async with _firefox_bidi_session(debug_url) as session:
        context = await _firefox_get_gengo_context(session)
        context_id = str(context.get("context") or "").strip()
        if not context_id:
            raise BrowserSessionError("Selected gengo.com browsing context has no id")

        result = await session.call(
            "storage.getCookies",
            {
                "partition": {
                    "type": "context",
                    "context": context_id,
                }
            },
        )

    cookies = result.get("cookies")
    if not isinstance(cookies, list):
        raise BrowserSessionError("Browser did not return a cookie list")
    return extract_cookie_value(cookies, cookie_name=cookie_name)


async def fetch_browser_session_snapshot(
    debug_url: str | None = None,
    cookie_name: str | tuple[str, ...] = PRIMARY_GENGO_COOKIE_NAMES,
) -> BrowserSessionSnapshot:
    endpoint = _resolve_browser_endpoint(debug_url)
    if endpoint.backend == "firefox-rdp":
        return await _fetch_browser_session_snapshot_firefox_rdp(
            endpoint.url,
            cookie_name,
        )
    if endpoint.backend == "firefox-bidi":
        return await _fetch_browser_session_snapshot_firefox_bidi(
            endpoint.url,
            cookie_name,
        )

    target = select_gengo_target(
        _load_cdp_targets(endpoint.url),
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
        try:
            runtime_result = await _evaluate_expression(
                websocket,
                (
                    "(() => ({"
                    f'userKey: window.localStorage.getItem("{GENGO_LOCAL_STORAGE_USER_KEY}") || "",'
                    'userAgent: navigator.userAgent || "",'
                    "acceptLanguage: (Array.isArray(navigator.languages) && navigator.languages.length"
                    ' ? navigator.languages.join(",") : (navigator.language || "")),'
                    'origin: location.origin || "",'
                    'url: location.href || "",'
                    'title: document.title || "",'
                    "}))()"
                ),
                call_id=2,
                expected_type="object",
            )
        except BrowserSessionError:
            runtime_result = {}

    cookies = cookie_result.get("cookies")
    if not isinstance(cookies, list):
        raise BrowserSessionError("Browser did not return a cookie list")

    session_token = extract_cookie_value(cookies, cookie_name=cookie_name)
    page_state = runtime_result
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
    endpoint = _resolve_browser_endpoint(debug_url)
    if endpoint.backend == "firefox-rdp":
        return await _fetch_browser_session_token_firefox_rdp(
            endpoint.url,
            cookie_name,
        )
    if endpoint.backend == "firefox-bidi":
        return await _fetch_browser_session_token_firefox_bidi(
            endpoint.url,
            cookie_name,
        )

    target = select_gengo_target(_load_cdp_targets(endpoint.url))
    websocket_url = str(target.get("webSocketDebuggerUrl", "")).strip()
    if not websocket_url:
        raise BrowserSessionError(
            "Selected gengo.com page target has no CDP websocket URL"
        )

    async with websockets.connect(websocket_url, max_size=5_000_000) as websocket:
        result = await _cdp_call(
            websocket,
            "Network.getCookies",
            {"urls": [DEFAULT_GENGO_ORIGIN]},
        )

    cookies = result.get("cookies")
    if not isinstance(cookies, list):
        raise BrowserSessionError("Browser did not return a cookie list")
    return extract_cookie_value(cookies, cookie_name=cookie_name)


def fetch_browser_session_snapshot_sync(
    debug_url: str | None = None,
    cookie_name: str | tuple[str, ...] = PRIMARY_GENGO_COOKIE_NAMES,
) -> BrowserSessionSnapshot:
    return run_coroutine_sync(
        fetch_browser_session_snapshot,
        debug_url=debug_url,
        cookie_name=cookie_name,
    )


def fetch_browser_session_token_sync(
    debug_url: str | None = None,
    cookie_name: str | tuple[str, ...] = PRIMARY_GENGO_COOKIE_NAMES,
) -> str:
    return run_coroutine_sync(
        fetch_browser_session_token,
        debug_url=debug_url,
        cookie_name=cookie_name,
    )


async def _open_url_in_firefox_bidi(debug_url: str | None, url: str) -> str:
    async with _firefox_bidi_session(debug_url) as session:
        context_result = await session.call(
            "browsingContext.create",
            {"type": "tab", "background": False},
        )
        context_id = str(context_result.get("context") or "").strip()
        if not context_id:
            raise BrowserSessionError("Firefox BiDi did not return a new tab context")

        navigate_result = await session.call(
            "browsingContext.navigate",
            {
                "context": context_id,
                "url": url,
                "wait": "none",
            },
        )
        return str(navigate_result.get("url") or url)


async def open_url_in_browser_debug(
    debug_url: str | None,
    url: str,
) -> str:
    """Open a URL in an already managed browser debug session."""
    target_url = str(url or "").strip()
    if not target_url:
        raise BrowserSessionError("Cannot open an empty browser URL")

    endpoint = _resolve_browser_endpoint(debug_url)
    if endpoint.backend == "firefox-rdp":
        return await _open_url_in_firefox_rdp(endpoint.url, target_url)
    if endpoint.backend == "firefox-bidi":
        return await _open_url_in_firefox_bidi(endpoint.url, target_url)
    raise BrowserSessionError(
        f"Opening URLs through {endpoint.backend} debug endpoints is not supported"
    )


def open_url_in_browser_debug_sync(
    debug_url: str | None,
    url: str,
) -> str:
    return run_coroutine_sync(open_url_in_browser_debug, debug_url, url)


async def _firefox_rdp_read_activity_state(
    client: _FirefoxRdpClient,
    *,
    actor_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tab, _tabs_response = await _firefox_rdp_get_gengo_tab(client, actor_id=actor_id)
    state = await _firefox_rdp_evaluate_json(
        client,
        _firefox_tab_console_actor(tab),
        _firefox_activity_state_expression(),
        inner_window_id=tab.get("innerWindowId"),
    )
    return tab, state


async def _wait_for_firefox_rdp_page_state(
    client: _FirefoxRdpClient,
    *,
    actor_id: str,
    location_fragment: str,
    activity_marker: str,
    attempts: int = 12,
    sleep_sec: float = 0.35,
) -> tuple[dict[str, Any], dict[str, Any]]:
    last_tab: dict[str, Any] = {}
    last_state: dict[str, Any] = {}

    for _ in range(attempts):
        try:
            tab, state = await _firefox_rdp_read_activity_state(
                client,
                actor_id=actor_id,
            )
            last_tab = tab
            last_state = state
        except BrowserSessionError:
            last_tab = {}
            last_state = {}

        href = str(last_state.get("href", "") or last_tab.get("url", "") or "").strip()
        ready_state = str(last_state.get("readyState", "") or "").strip()
        marker = str(last_state.get("activityMarker", "") or "").strip()
        if (
            location_fragment in href
            and ready_state == "complete"
            and marker == activity_marker
        ):
            return last_tab, last_state
        await asyncio.sleep(sleep_sec)

    return last_tab, last_state


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
    descriptions = {
        "reload": "reloading the realtime dashboard",
        "summary_roundtrip": "opening the summary dashboard and returning to realtime",
        "job_roundtrip": "opening a visible job details page and returning to realtime",
    }
    return descriptions.get(action, action.replace("_", " "))


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
            (name, weight)
            for name, weight in weighted_actions
            if name != previous_action
        ]
        if filtered_actions:
            weighted_actions = filtered_actions

    actions = [name for name, _weight in weighted_actions]
    weights = [weight for _name, weight in weighted_actions]
    return random.choices(actions, weights=weights, k=1)[0]


async def _refresh_browser_page_activity_firefox_rdp(
    debug_url: str | None,
    *,
    action: str = "auto",
    previous_action: str | None = None,
) -> str:
    client = await _open_firefox_rdp_client(debug_url)
    try:
        tab, _tabs_response = await _firefox_rdp_get_gengo_tab(
            client,
            preferred_url_fragments=(GENGO_REALTIME_PATH, GENGO_SUMMARY_PATH),
        )
        tab_actor = str(tab.get("actor") or "").strip()
        if not tab_actor:
            raise BrowserSessionError("Firefox DevTools did not expose a tab actor")
        state = await _firefox_rdp_evaluate_json(
            client,
            _firefox_tab_console_actor(tab),
            _firefox_activity_state_expression(),
            inner_window_id=tab.get("innerWindowId"),
        )

        current_href = str(state.get("href", "") or tab.get("url", "") or "").strip()
        job_href = str(state.get("jobHref", "") or "").strip()
        if action == "auto":
            action = _choose_browser_activity_action(
                job_href=job_href,
                previous_action=previous_action,
            )

        if action == "reload":
            activity_marker = _make_firefox_activity_marker()
            await _firefox_rdp_evaluate_json(
                client,
                _firefox_tab_console_actor(tab),
                _firefox_queue_reload_expression(activity_marker),
                inner_window_id=tab.get("innerWindowId"),
            )
            wait_fragment = urlparse(current_href).path or "gengo.com"
            await _wait_for_firefox_rdp_page_state(
                client,
                actor_id=tab_actor,
                location_fragment=wait_fragment,
                activity_marker=activity_marker,
            )
            return "reload"

        if action == "job_roundtrip" and job_href:
            outbound_marker = _make_firefox_activity_marker()
            await _firefox_rdp_evaluate_json(
                client,
                _firefox_tab_console_actor(tab),
                _firefox_queue_navigation_expression(job_href, outbound_marker),
                inner_window_id=tab.get("innerWindowId"),
            )
            tab, _state = await _wait_for_firefox_rdp_page_state(
                client,
                actor_id=tab_actor,
                location_fragment="/t/jobs/details/",
                activity_marker=outbound_marker,
            )
            await asyncio.sleep(0.6)

            return_marker = _make_firefox_activity_marker()
            await _firefox_rdp_evaluate_json(
                client,
                _firefox_tab_console_actor(tab),
                _firefox_queue_navigation_expression(
                    GENGO_REALTIME_URL,
                    return_marker,
                ),
                inner_window_id=tab.get("innerWindowId"),
            )
            await _wait_for_firefox_rdp_page_state(
                client,
                actor_id=tab_actor,
                location_fragment=GENGO_REALTIME_PATH,
                activity_marker=return_marker,
            )
            return "job_roundtrip"

        outbound_marker = _make_firefox_activity_marker()
        await _firefox_rdp_evaluate_json(
            client,
            _firefox_tab_console_actor(tab),
            _firefox_queue_navigation_expression(
                GENGO_SUMMARY_URL,
                outbound_marker,
            ),
            inner_window_id=tab.get("innerWindowId"),
        )
        tab, _state = await _wait_for_firefox_rdp_page_state(
            client,
            actor_id=tab_actor,
            location_fragment=GENGO_SUMMARY_PATH,
            activity_marker=outbound_marker,
        )
        await asyncio.sleep(0.6)

        return_marker = _make_firefox_activity_marker()
        await _firefox_rdp_evaluate_json(
            client,
            _firefox_tab_console_actor(tab),
            _firefox_queue_navigation_expression(
                GENGO_REALTIME_URL,
                return_marker,
            ),
            inner_window_id=tab.get("innerWindowId"),
        )
        await _wait_for_firefox_rdp_page_state(
            client,
            actor_id=tab_actor,
            location_fragment=GENGO_REALTIME_PATH,
            activity_marker=return_marker,
        )
        return "summary_roundtrip"
    finally:
        await client.websocket.close()


async def _refresh_browser_page_activity_firefox_bidi(
    debug_url: str | None,
    *,
    action: str = "auto",
    previous_action: str | None = None,
) -> str:
    async with _firefox_bidi_session(debug_url) as session:
        context = await _firefox_get_gengo_context(
            session,
            preferred_url_fragments=(GENGO_REALTIME_PATH, GENGO_SUMMARY_PATH),
        )
        context_id = str(context.get("context") or "").strip()
        if not context_id:
            raise BrowserSessionError("Selected gengo.com browsing context has no id")

        page_state = await _firefox_evaluate_json(
            session,
            context_id,
            (
                "JSON.stringify({"
                'href: location.href || "",'
                'jobHref: (document.querySelector(\'a[href*="/jobs/details/"]\')?.href || "")'
                "})"
            ),
        )

        job_href = str(page_state.get("jobHref", "") or "").strip()
        if action == "auto":
            action = _choose_browser_activity_action(
                job_href=job_href,
                previous_action=previous_action,
            )

        if action == "reload":
            await session.call(
                "browsingContext.reload",
                {
                    "context": context_id,
                    "ignoreCache": False,
                    "wait": "complete",
                },
            )
            return "reload"

        if action == "job_roundtrip" and job_href:
            await session.call(
                "browsingContext.navigate",
                {
                    "context": context_id,
                    "url": job_href,
                    "wait": "complete",
                },
            )
            await asyncio.sleep(0.6)
            await session.call(
                "browsingContext.navigate",
                {
                    "context": context_id,
                    "url": GENGO_REALTIME_URL,
                    "wait": "complete",
                },
            )
            return "job_roundtrip"

        await session.call(
            "browsingContext.navigate",
            {
                "context": context_id,
                "url": GENGO_SUMMARY_URL,
                "wait": "complete",
            },
        )
        await asyncio.sleep(0.6)
        await session.call(
            "browsingContext.navigate",
            {
                "context": context_id,
                "url": GENGO_REALTIME_URL,
                "wait": "complete",
            },
        )
        return "summary_roundtrip"


async def refresh_browser_page_activity(
    debug_url: str | None = None,
    *,
    action: str = "auto",
    previous_action: str | None = None,
) -> str:
    endpoint = _resolve_browser_endpoint(debug_url)
    if endpoint.backend == "firefox-rdp":
        return await _refresh_browser_page_activity_firefox_rdp(
            endpoint.url,
            action=action,
            previous_action=previous_action,
        )
    if endpoint.backend == "firefox-bidi":
        return await _refresh_browser_page_activity_firefox_bidi(
            endpoint.url,
            action=action,
            previous_action=previous_action,
        )

    target = select_gengo_target(
        _load_cdp_targets(endpoint.url),
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
            await _wait_for_location_contains(
                websocket,
                "gengo.com",
                call_id_start=call_id + 1,
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
            await _wait_for_location_contains(
                websocket,
                GENGO_REALTIME_PATH,
                call_id_start=call_id + 1,
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
        await _wait_for_location_contains(
            websocket,
            GENGO_REALTIME_PATH,
            call_id_start=call_id + 1,
        )
        return "summary_roundtrip"


def refresh_browser_page_activity_sync(
    debug_url: str | None = None,
    *,
    action: str = "auto",
    previous_action: str | None = None,
) -> str:
    return run_coroutine_sync(
        refresh_browser_page_activity,
        debug_url=debug_url,
        action=action,
        previous_action=previous_action,
    )


def build_browser_aligned_websocket_headers(
    *,
    session_token: str,
    user_agent: str = "",
    origin: str = DEFAULT_GENGO_ORIGIN,
    accept_language: str = "",
) -> dict[str, str]:
    headers = {"Origin": origin or DEFAULT_GENGO_ORIGIN}
    if session_token:
        headers["Cookie"] = (
            f"myG_myGSession_={session_token}; myG_rdsessID={session_token}"
        )
    headers["Pragma"] = "no-cache"
    headers["Cache-Control"] = "no-cache"
    if user_agent:
        headers["User-Agent"] = user_agent
    if accept_language:
        headers["Accept-Language"] = accept_language
    headers["Accept-Encoding"] = "gzip, deflate, br, zstd"
    return headers


def build_websocket_auth_payload(
    *,
    user_id: Any,
    session_token: str,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "user_session": session_token,
    }
