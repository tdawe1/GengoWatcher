from __future__ import annotations

import asyncio
import json
import re
import shutil
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


def _resolve_browser_binary_path(browser_path: str) -> Path | None:
    resolved = shutil.which(browser_path) or browser_path
    path = Path(resolved).expanduser()
    try:
        return path.resolve()
    except OSError:
        return path


def _detect_locked_remote_debug_pref(browser_path: str) -> Path | None:
    binary_path = _resolve_browser_binary_path(browser_path)
    if binary_path is None:
        return None

    candidate_dirs = [
        binary_path.parent / "browser" / "defaults" / "preferences",
        binary_path.parent.parent / "browser" / "defaults" / "preferences",
    ]
    pattern = re.compile(
        r'pref\("devtools\.debugger\.remote-enabled",\s*false,\s*locked\);'
    )

    for candidate_dir in candidate_dirs:
        if not candidate_dir.is_dir():
            continue
        for pref_file in sorted(candidate_dir.glob("*.js")):
            try:
                content = pref_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if pattern.search(content):
                return pref_file
    return None


def _upsert_firefox_pref_file(path: Path, prefs_text: str) -> None:
    managed_lines = [
        line
        for line in prefs_text.splitlines()
        if line.startswith('user_pref("')
    ]
    managed_keys = []
    managed_map: dict[str, str] = {}
    for line in managed_lines:
        match = re.match(r'user_pref\("([^"]+)",\s*(.+)\);$', line)
        if not match:
            continue
        key = match.group(1)
        managed_keys.append(key)
        managed_map[key] = line

    existing_lines: list[str] = []
    if path.exists():
        existing_lines = path.read_text(encoding="utf-8").splitlines()

    updated_lines: list[str] = []
    seen_keys: set[str] = set()
    for line in existing_lines:
        match = re.match(r'user_pref\("([^"]+)",\s*(.+)\);$', line)
        key = match.group(1) if match else None
        if key and key in managed_map:
            updated_lines.append(managed_map[key])
            seen_keys.add(key)
        else:
            updated_lines.append(line)

    missing_lines = [
        managed_map[key] for key in managed_keys if key not in seen_keys
    ]
    if missing_lines:
        if updated_lines and updated_lines[-1] != "":
            updated_lines.append("")
        updated_lines.extend(missing_lines)

    if not updated_lines:
        updated_lines = prefs_text.splitlines()

    rendered = "\n".join(updated_lines).rstrip() + "\n"
    path.write_text(rendered, encoding="utf-8")


def ensure_managed_firefox_profile(spec: FirefoxDebugLaunchSpec) -> Path:
    spec.profile_path.mkdir(parents=True, exist_ok=True)
    prefs_text = _managed_firefox_profile_prefs(spec.port)
    _upsert_firefox_pref_file(spec.profile_path / "user.js", prefs_text)
    _upsert_firefox_pref_file(spec.profile_path / "prefs.js", prefs_text)
    return spec.profile_path


def build_firefox_debug_command(spec: FirefoxDebugLaunchSpec) -> list[str]:
    return [
        spec.browser_path,
        "--new-instance",
        "--profile",
        str(spec.profile_path),
        "--start-debugger-server",
        f"ws:{spec.port}",
        "--new-window",
        spec.start_url,
    ]


def launch_managed_firefox_debug(spec: FirefoxDebugLaunchSpec) -> subprocess.Popen:
    locked_pref_file = _detect_locked_remote_debug_pref(spec.browser_path)
    if locked_pref_file is not None:
        raise RuntimeError(
            "This Firefox build disables DevTools remote debugging via a locked "
            f"preference in {locked_pref_file}. Use a Firefox build without that "
            "lock and point Paths.browser_debug_browser_path at it."
        )

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

    timeout_sec, retry_interval_sec = get_firefox_debug_retry_window(config)
    if not wait_for_firefox_debug_server(
        spec.debug_url,
        timeout_sec=timeout_sec,
        retry_interval_sec=retry_interval_sec,
    ):
        if logger is not None:
            logger.warning(
                "Managed Firefox launch did not expose a debug server at %s"
                " within %.1fs",
                spec.debug_url,
                timeout_sec,
            )
        return False

    if logger is not None:
        logger.info(
            "Started managed Firefox debug session at %s using profile %s",
            spec.debug_url,
            spec.profile_path,
        )
    return True
