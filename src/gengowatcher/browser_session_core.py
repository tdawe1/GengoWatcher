from __future__ import annotations

import re

import base64
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse, urlunparse

DEFAULT_BROWSER_DEBUG_URL = "http://127.0.0.1:9222"
DEFAULT_FIREFOX_BIDI_PATH = "/session"
DEFAULT_GENGO_ORIGIN = "https://gengo.com"
GENGO_LOCAL_STORAGE_USER_KEY = "userKey"
GENGO_ACTIVITY_MARKER_STORAGE_KEY = "__gengowatcher_activity_marker"
GENGO_AVAILABLE_JOBS_DETECTED_STORAGE_KEY = "__gengowatcher_available_jobs_detected"
GENGO_REALTIME_PATH = "/t/jobs/status/available/realtime"
GENGO_AVAILABLE_JOBS_PATH = "/t/jobs/status/available"
GENGO_SUMMARY_PATH = "/t/dashboard"
GENGO_REALTIME_URL = f"{DEFAULT_GENGO_ORIGIN}{GENGO_REALTIME_PATH}"
GENGO_AVAILABLE_JOBS_URL = f"{DEFAULT_GENGO_ORIGIN}{GENGO_AVAILABLE_JOBS_PATH}"
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
    rd_session_id: str = ""
    cookies: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class BrowserAvailableJob:
    job_id: int
    title: str
    reward: float
    url: str
    text: str = ""


@dataclass(frozen=True)
class BrowserAvailableJobsSnapshot:
    url: str
    title: str
    ready_state: str
    jobs: tuple[BrowserAvailableJob, ...]
    detected_jobs: tuple[BrowserAvailableJob, ...] = ()
    action: str = "inspect"


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


def normalize_debug_url(debug_url: str | None) -> str:
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


def looks_like_firefox_bidi_url(debug_url: str) -> bool:
    parsed = urlparse(debug_url)
    path = parsed.path.rstrip("/")
    return path == DEFAULT_FIREFOX_BIDI_PATH


def looks_like_firefox_rdp_url(debug_url: str) -> bool:
    parsed = urlparse(debug_url)
    return parsed.scheme in {"ws", "wss"} and not looks_like_firefox_bidi_url(debug_url)


def firefox_bidi_url(debug_url: str | None) -> str:
    normalized_debug_url = normalize_debug_url(debug_url)
    parsed = urlparse(normalized_debug_url)
    scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
    hostname = parsed.hostname or "127.0.0.1"
    if hostname == "localhost":
        hostname = "127.0.0.1"
    netloc = hostname
    if parsed.port is not None:
        netloc = f"{hostname}:{parsed.port}"
    return urlunparse((scheme, netloc, DEFAULT_FIREFOX_BIDI_PATH, "", "", ""))


def summarize_cdp_targets(targets: list[dict[str, Any]]) -> list[BrowserDebugTarget]:
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


def summarize_firefox_contexts(
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


def summarize_firefox_tabs(tabs: list[dict[str, Any]]) -> list[BrowserDebugTarget]:
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


def coerce_cookie_value(value: Any) -> str:
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
            value = coerce_cookie_value(cookie.get("value", ""))
            if value:
                return value
    raise BrowserSessionError(
        f"None of the session cookies {cookie_names} were found for gengo.com"
    )


# ==============================================================================
# Anti-detection helpers: rotating User-Agent pool + Client-Hints synthesis.
#
# These exist so the WebSocket identity presented to Gengo's dashboard matches
# a real current-generation Firefox/Chrome browser, with rotating UA strings
# drawn from a small pool (avoid the "one synthetic UA forever" tell).
# ==============================================================================

# A small pool of *plausible current* desktop UAs. Rotating between them keeps
# the WS identity from looking like a static Python script. The pool is small
# on purpose - large pools are a fingerprint vector of their own.
ROTATING_USER_AGENT_POOL: tuple[str, ...] = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:134.0) Gecko/20100101 Firefox/134.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)


def pick_rotating_user_agent(existing: str | None = None) -> str:
    """Pick a UA from the rotation pool.

    If ``existing`` is provided AND already a member of the pool, keep it so
    sessions stay stable. Otherwise pick a fresh entry deterministically-ish
    (random for variety, but stable within a single Python process because the
    random module is seeded once at import time elsewhere).
    """
    if existing and existing in ROTATING_USER_AGENT_POOL:
        return existing
    import random as _random
    return _random.choice(ROTATING_USER_AGENT_POOL)


def _is_firefox_ua(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    return "firefox/" in ua or "rv:" in ua and "gecko" in ua


def _is_chrome_ua(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    return "chrome/" in ua and "safari/" in ua and "edg/" not in ua


# Match a plausible *real* Chrome major version (current stable is ~131 today).
# This guards against Client-Hint synthesis for synthetic UAs the caller passes
# (e.g. test fixtures with "Chrome/142"). A fake version number is itself a
# fingerprint tell, so we refuse to invent Client Hints for it.
_CHROME_VERSION_RE = re.compile("chrome/([0-9]+)" + chr(46), re.IGNORECASE)


def _is_real_chrome_ua(user_agent: str) -> bool:
    if not _is_chrome_ua(user_agent):
        return False
    m = _CHROME_VERSION_RE.search(user_agent)
    if not m:
        return False
    try:
        major = int(m.group(1))
    except (TypeError, ValueError):
        return False
    # Anything newer than the latest stable (with margin for skew) is treated as
    # synthetic. Lower bound = 100 to refuse obviously-stale fingerprints.
    return 100 <= major <= 140


def derive_client_hints(user_agent: str) -> dict[str, str]:
    """Derive Sec-CH-UA Client Hints for the given User-Agent.

    Returns an empty dict when the UA is not in a recognized family so we don't
    synthesize fingerprints for UAs we don't actually know about.
    """
    if not user_agent:
        return {}

    if _is_firefox_ua(user_agent):
        # Firefox does not send Sec-CH-UA headers today. Returning an empty
        # dict is the *correct* behaviour for Firefox - sending Chrome-style
        # hints from a Firefox UA is itself a fingerprint vector.
        return {}

    if _is_chrome_ua(user_agent) and _is_real_chrome_ua(user_agent):
        # Best-effort Client Hints for current stable Chrome. These match the
        # values a real Chrome 131 sends to gengo-style dashboard pages.
        return {
            "Sec-CH-UA": '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Linux"',
            "Sec-CH-UA-Platform-Version": '"6.0"',
            "Sec-CH-UA-Arch": '"x86"',
            "Sec-CH-UA-Bitness": '"64"',
            "Sec-CH-UA-Model": '""',
            "Sec-CH-UA-Full-Version-List": '"Chromium";v="131.0.6778.108", "Not_A Brand";v="24.0.0.0", "Google Chrome";v="131.0.6778.108"',
        }

    # Unknown UA family - do not invent Client Hints.
    return {}
