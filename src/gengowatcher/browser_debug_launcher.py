from __future__ import annotations

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import websockets

from .browser_session import GENGO_REALTIME_URL

DEFAULT_FIREFOX_DEBUG_URL = "ws://127.0.0.1:6000"
DEFAULT_FIREFOX_DEBUG_BROWSER_PATH = "firefox"
DEFAULT_FIREFOX_DEBUG_PROFILE_PATH = "profiles/firefox-debug"
DEFAULT_FIREFOX_DEBUG_LAUNCH_TIMEOUT_SEC = 15.0
DEFAULT_FIREFOX_DEBUG_RETRY_INTERVAL_SEC = 1.0

_MANAGED_FIREFOX_PROFILE_PREFS = {
    "devtools.chrome.enabled": True,
    "devtools.debugger.prompt-connection": False,
    "devtools.debugger.remote-enabled": True,
    "devtools.debugger.remote-websocket": True,
}


@dataclass(frozen=True)
class FirefoxDebugLaunchSpec:
    debug_url: str
    browser_path: str
    profile_path: Path
    start_url: str
    port: int


def _config_get(config: Any, section: str, option: str, fallback: Any) -> Any:
    getter = getattr(config, "get", None)
    if getter is None:
        return fallback
    return getter(section, option, fallback=fallback)


def _config_getboolean(config: Any, section: str, option: str, fallback: bool) -> bool:
    getter = getattr(config, "getboolean", None)
    if getter is None:
        return fallback
    return bool(getter(section, option, fallback=fallback))


def _config_getfloat(config: Any, section: str, option: str, fallback: float) -> float:
    getter = getattr(config, "getfloat", None)
    if getter is None:
        return fallback
    return float(getter(section, option, fallback=fallback))


def _looks_like_local_firefox_rdp_url(debug_url: str) -> bool:
    parsed = urlparse(str(debug_url or "").strip())
    if parsed.scheme != "ws":
        return False
    if parsed.path.rstrip("/") == "/session":
        return False
    return (parsed.hostname or "127.0.0.1") in {"127.0.0.1", "localhost"}


def _firefox_debug_port(debug_url: str) -> int:
    parsed = urlparse(debug_url)
    return int(parsed.port or 6000)


def get_firefox_debug_launch_spec(
    config: Any,
    debug_url: str | None,
    *,
    require_enabled: bool = True,
    allow_default_debug_url: bool = False,
) -> FirefoxDebugLaunchSpec | None:
    resolved_debug_url = str(debug_url or "").strip()
    if not resolved_debug_url and allow_default_debug_url:
        resolved_debug_url = DEFAULT_FIREFOX_DEBUG_URL

    if require_enabled and not _config_getboolean(
        config,
        "WebSocket",
        "browser_debug_auto_launch",
        fallback=False,
    ):
        return None
    if not _looks_like_local_firefox_rdp_url(resolved_debug_url):
        return None

    browser_path = str(
        _config_get(
            config,
            "Paths",
            "browser_debug_browser_path",
            DEFAULT_FIREFOX_DEBUG_BROWSER_PATH,
        )
        or DEFAULT_FIREFOX_DEBUG_BROWSER_PATH
    ).strip()
    profile_path = Path(
        str(
            _config_get(
                config,
                "WebSocket",
                "browser_debug_profile_path",
                DEFAULT_FIREFOX_DEBUG_PROFILE_PATH,
            )
            or DEFAULT_FIREFOX_DEBUG_PROFILE_PATH
        )
    ).expanduser()
    start_url = str(
        _config_get(
            config,
            "WebSocket",
            "browser_debug_start_url",
            GENGO_REALTIME_URL,
        )
        or GENGO_REALTIME_URL
    ).strip()
    return FirefoxDebugLaunchSpec(
        debug_url=resolved_debug_url,
        browser_path=browser_path,
        profile_path=profile_path,
        start_url=start_url or GENGO_REALTIME_URL,
        port=_firefox_debug_port(resolved_debug_url),
    )


def get_firefox_debug_retry_window(config: Any) -> tuple[float, float]:
    timeout_sec = _config_getfloat(
        config,
        "WebSocket",
        "browser_debug_launch_timeout_sec",
        DEFAULT_FIREFOX_DEBUG_LAUNCH_TIMEOUT_SEC,
    )
    retry_interval_sec = _config_getfloat(
        config,
        "WebSocket",
        "browser_debug_retry_interval_sec",
        DEFAULT_FIREFOX_DEBUG_RETRY_INTERVAL_SEC,
    )
    return max(1.0, timeout_sec), max(0.1, retry_interval_sec)


def _managed_firefox_profile_prefs(port: int) -> str:
    lines = ["// Managed by GengoWatcher for Firefox DevTools attach."]
    prefs = dict(_MANAGED_FIREFOX_PROFILE_PREFS)
    prefs["devtools.debugger.remote-port"] = port
    for key, value in prefs.items():
        lines.append(f"user_pref({json.dumps(key)}, {json.dumps(value)});")
    lines.append("")
    return "\n".join(lines)


def ensure_managed_firefox_profile(spec: FirefoxDebugLaunchSpec) -> Path:
    spec.profile_path.mkdir(parents=True, exist_ok=True)
    user_js_path = spec.profile_path / "user.js"
    user_js_path.write_text(
        _managed_firefox_profile_prefs(spec.port),
        encoding="utf-8",
    )
    return spec.profile_path


def build_firefox_debug_command(spec: FirefoxDebugLaunchSpec) -> list[str]:
    return [
        spec.browser_path,
        "--new-instance",
        "--profile",
        str(spec.profile_path),
        "--start-debugger-server",
        f"ws:{spec.port}",
        spec.start_url,
    ]


def launch_managed_firefox_debug(spec: FirefoxDebugLaunchSpec) -> subprocess.Popen:
    ensure_managed_firefox_profile(spec)
    try:
        return subprocess.Popen(
            build_firefox_debug_command(spec),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Firefox executable not found: {spec.browser_path}"
        ) from exc


async def _probe_firefox_debug_server(debug_url: str) -> bool:
    try:
        async with websockets.connect(debug_url, max_size=1_000_000) as websocket:
            raw_message = await asyncio.wait_for(websocket.recv(), timeout=2)
    except Exception:
        return False

    try:
        packet = json.loads(raw_message)
    except json.JSONDecodeError:
        return False
    return isinstance(packet, dict) and packet.get("from") == "root"


def can_connect_to_firefox_debug_server(debug_url: str) -> bool:
    if not _looks_like_local_firefox_rdp_url(debug_url):
        return False
    return bool(asyncio.run(_probe_firefox_debug_server(debug_url)))


def wait_for_firefox_debug_server(
    debug_url: str,
    *,
    timeout_sec: float,
    retry_interval_sec: float,
) -> bool:
    if not _looks_like_local_firefox_rdp_url(debug_url):
        return False

    deadline = time.monotonic() + max(0.0, timeout_sec)
    retry_interval = max(0.1, retry_interval_sec)
    while True:
        if can_connect_to_firefox_debug_server(debug_url):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(retry_interval)


def maybe_launch_managed_firefox_debug(
    config: Any,
    debug_url: str | None,
    *,
    logger: Any | None = None,
) -> bool:
    spec = get_firefox_debug_launch_spec(config, debug_url)
    if spec is None:
        return False
    if can_connect_to_firefox_debug_server(spec.debug_url):
        return False

    try:
        launch_managed_firefox_debug(spec)
    except Exception as exc:
        if logger is not None:
            logger.warning(
                "Failed to start managed Firefox debug session for %s: %s",
                spec.debug_url,
                exc,
            )
        return False
    if logger is not None:
        logger.info(
            "Started managed Firefox debug session at %s using profile %s",
            spec.debug_url,
            spec.profile_path,
        )
    return True
