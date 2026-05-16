import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

from gengowatcher.browser_debug_launcher import (
    DEFAULT_FIREFOX_DEBUG_URL,
    FirefoxDebugLaunchSpec,
    _detect_locked_remote_debug_pref,
    build_firefox_debug_command,
    can_connect_to_firefox_debug_server,
    ensure_managed_firefox_profile,
    get_firefox_debug_launch_spec,
    get_firefox_debug_retry_window,
    launch_managed_firefox_debug,
    maybe_launch_managed_firefox_debug,
    wait_for_firefox_debug_server,
)


def test_get_firefox_debug_launch_spec_requires_local_ws_url():
    config = MagicMock()
    config.getboolean.return_value = True
    config.get.side_effect = lambda section, option, fallback=None: {
        ("Paths", "browser_debug_browser_path"): "firefox-bin",
        ("WebSocket", "browser_debug_profile_path"): "profiles/firefox-debug",
        ("WebSocket", "browser_debug_start_url"): "https://gengo.com/t/jobs/",
    }.get((section, option), fallback)

    spec = get_firefox_debug_launch_spec(config, "ws://127.0.0.1:6000")

    assert spec is not None
    assert spec.debug_url == "ws://127.0.0.1:6000"
    assert spec.browser_path == "firefox-bin"
    assert spec.profile_path == Path("profiles/firefox-debug")
    assert spec.seed_profile_path is None
    assert spec.port == 6000


def test_get_firefox_debug_launch_spec_uses_default_url_for_explicit_start():
    config = MagicMock()
    config.get.side_effect = lambda _section, _option, fallback=None: fallback

    spec = get_firefox_debug_launch_spec(
        config,
        "",
        require_enabled=False,
        allow_default_debug_url=True,
    )

    assert spec is not None
    assert spec.debug_url == DEFAULT_FIREFOX_DEBUG_URL


def test_get_firefox_debug_launch_spec_reads_seed_profile_path():
    config = MagicMock()
    config.getboolean.return_value = True
    config.get.side_effect = lambda section, option, fallback=None: {
        ("Paths", "browser_debug_browser_path"): "firefox-bin",
        ("WebSocket", "browser_debug_profile_path"): "profiles/firefox-debug",
        ("WebSocket", "browser_debug_seed_profile_path"): "profiles/zen-main",
        ("WebSocket", "browser_debug_start_url"): "https://gengo.com/t/jobs/",
    }.get((section, option), fallback)

    spec = get_firefox_debug_launch_spec(config, "ws://127.0.0.1:6000")

    assert spec is not None
    assert spec.seed_profile_path == Path("profiles/zen-main")


def test_build_firefox_debug_command_includes_debug_server_and_profile(tmp_path):
    config = MagicMock()
    config.getboolean.return_value = True
    config.get.side_effect = lambda section, option, fallback=None: {
        ("Paths", "browser_debug_browser_path"): "/usr/bin/firefox",
        ("WebSocket", "browser_debug_profile_path"): str(tmp_path / "profile"),
        (
            "WebSocket",
            "browser_debug_start_url",
        ): "https://gengo.com/t/jobs/status/available/realtime",
    }.get((section, option), fallback)

    spec = get_firefox_debug_launch_spec(config, "ws://127.0.0.1:6100")
    assert spec is not None

    command = build_firefox_debug_command(spec)

    assert command == [
        "/usr/bin/firefox",
        "--new-instance",
        "--profile",
        str(tmp_path / "profile"),
        "--start-debugger-server",
        "ws:6100",
        "--new-window",
        "https://gengo.com/t/jobs/status/available",
    ]


def test_ensure_managed_firefox_profile_writes_required_prefs(tmp_path):
    config = MagicMock()
    config.getboolean.return_value = True
    config.get.side_effect = lambda section, option, fallback=None: {
        ("Paths", "browser_debug_browser_path"): "firefox",
        ("WebSocket", "browser_debug_profile_path"): str(tmp_path / "profile"),
        ("WebSocket", "browser_debug_start_url"): "https://gengo.com/t/jobs/",
    }.get((section, option), fallback)

    spec = get_firefox_debug_launch_spec(config, "ws://127.0.0.1:6123")
    assert spec is not None

    profile_path = ensure_managed_firefox_profile(spec)
    user_js = (profile_path / "user.js").read_text(encoding="utf-8")
    prefs_js = (profile_path / "prefs.js").read_text(encoding="utf-8")

    assert 'user_pref("devtools.chrome.enabled", true);' in user_js
    assert 'user_pref("devtools.debugger.remote-enabled", true);' in user_js
    assert 'user_pref("devtools.debugger.remote-port", 6123);' in user_js
    assert 'user_pref("devtools.chrome.enabled", true);' in prefs_js
    assert 'user_pref("devtools.debugger.remote-enabled", true);' in prefs_js
    assert 'user_pref("devtools.debugger.remote-port", 6123);' in prefs_js


def test_ensure_managed_firefox_profile_clones_seed_profile(tmp_path):
    seed_profile = tmp_path / "seed"
    seed_profile.mkdir()
    (seed_profile / "cookies.sqlite").write_text("seed-cookie-db", encoding="utf-8")
    (seed_profile / "SingletonLock").write_text("locked", encoding="utf-8")
    spec = FirefoxDebugLaunchSpec(
        debug_url="ws://127.0.0.1:6123",
        browser_path="firefox",
        profile_path=tmp_path / "profile",
        seed_profile_path=seed_profile,
        start_url="https://gengo.com/t/jobs/",
        port=6123,
    )

    profile_path = ensure_managed_firefox_profile(spec)

    assert (profile_path / "cookies.sqlite").read_text(encoding="utf-8") == (
        "seed-cookie-db"
    )
    assert not (profile_path / "SingletonLock").exists()
    assert (profile_path / "user.js").exists()
    assert (profile_path / "prefs.js").exists()


def test_maybe_launch_managed_firefox_debug_starts_when_endpoint_is_down():
    config = MagicMock()
    config.getboolean.side_effect = lambda section, option, fallback=None: (
        True
        if (section, option) == ("WebSocket", "browser_debug_auto_launch")
        else fallback
    )
    config.get.side_effect = lambda section, option, fallback=None: {
        ("Paths", "browser_debug_browser_path"): "firefox",
        ("WebSocket", "browser_debug_profile_path"): "profiles/firefox-debug",
        (
            "WebSocket",
            "browser_debug_start_url",
        ): "https://gengo.com/t/jobs/status/available/realtime",
    }.get((section, option), fallback)

    with (
        patch(
            "gengowatcher.browser_debug_launcher.can_connect_to_firefox_debug_server",
            return_value=False,
        ),
        patch(
            "gengowatcher.browser_debug_launcher.wait_for_firefox_debug_server",
            return_value=True,
        ),
        patch(
            "gengowatcher.browser_debug_launcher.launch_managed_firefox_debug"
        ) as mock_launch,
    ):
        launched = maybe_launch_managed_firefox_debug(
            config,
            "ws://127.0.0.1:6000",
        )

    assert launched is True
    mock_launch.assert_called_once()


def test_maybe_launch_managed_firefox_debug_returns_false_if_server_stays_down():
    config = MagicMock()
    config.getboolean.side_effect = lambda section, option, fallback=None: (
        True
        if (section, option) == ("WebSocket", "browser_debug_auto_launch")
        else fallback
    )
    config.get.side_effect = lambda section, option, fallback=None: {
        ("Paths", "browser_debug_browser_path"): "firefox",
        ("WebSocket", "browser_debug_profile_path"): "profiles/firefox-debug",
        (
            "WebSocket",
            "browser_debug_start_url",
        ): "https://gengo.com/t/jobs/status/available/realtime",
    }.get((section, option), fallback)
    config.getfloat.side_effect = lambda _section, _option, fallback=None: fallback
    logger = MagicMock()

    with (
        patch(
            "gengowatcher.browser_debug_launcher.can_connect_to_firefox_debug_server",
            return_value=False,
        ),
        patch(
            "gengowatcher.browser_debug_launcher.wait_for_firefox_debug_server",
            return_value=False,
        ),
        patch(
            "gengowatcher.browser_debug_launcher.launch_managed_firefox_debug"
        ) as mock_launch,
    ):
        launched = maybe_launch_managed_firefox_debug(
            config,
            "ws://127.0.0.1:6000",
            logger=logger,
        )

    assert launched is False
    mock_launch.assert_called_once()
    logger.warning.assert_called()


def test_get_firefox_debug_retry_window_applies_reasonable_minimums():
    config = MagicMock()
    config.getfloat.side_effect = lambda section, option, fallback=None: {
        ("WebSocket", "browser_debug_launch_timeout_sec"): 0.0,
        ("WebSocket", "browser_debug_retry_interval_sec"): 0.0,
    }.get((section, option), fallback)

    timeout_sec, retry_interval_sec = get_firefox_debug_retry_window(config)

    assert timeout_sec == 1.0
    assert retry_interval_sec == 0.1


def test_wait_for_firefox_debug_server_retries_until_online():
    with (
        patch(
            "gengowatcher.browser_debug_launcher.can_connect_to_firefox_debug_server",
            side_effect=[False, False, True],
        ) as mock_connect,
        patch("gengowatcher.browser_debug_launcher.time.sleep") as mock_sleep,
    ):
        ready = wait_for_firefox_debug_server(
            "ws://127.0.0.1:6000",
            timeout_sec=3.0,
            retry_interval_sec=0.5,
        )

    assert ready is True
    assert mock_connect.call_count == 3
    assert mock_sleep.call_count == 2


async def _fake_probe_firefox_debug_server(debug_url: str) -> bool:
    return debug_url == "ws://127.0.0.1:9222"


def test_can_connect_to_firefox_debug_server_runs_without_existing_event_loop():
    with patch(
        "gengowatcher.browser_debug_launcher._probe_firefox_debug_server",
        side_effect=_fake_probe_firefox_debug_server,
    ):
        assert can_connect_to_firefox_debug_server("ws://127.0.0.1:9222") is True


def test_can_connect_to_firefox_debug_server_runs_inside_existing_event_loop():
    async def run_check():
        with patch(
            "gengowatcher.browser_debug_launcher._probe_firefox_debug_server",
            side_effect=_fake_probe_firefox_debug_server,
        ):
            return can_connect_to_firefox_debug_server("ws://127.0.0.1:9222")

    assert asyncio.run(run_check()) is True


def test_detect_locked_remote_debug_pref_finds_distribution_lock(tmp_path):
    browser_root = tmp_path / "firefox"
    prefs_dir = browser_root / "browser" / "defaults" / "preferences"
    prefs_dir.mkdir(parents=True)
    browser_bin = browser_root / "firefox"
    browser_bin.write_text("", encoding="utf-8")
    (prefs_dir / "vendor.js").write_text(
        'pref("devtools.debugger.remote-enabled", false, locked);\n',
        encoding="utf-8",
    )

    locked_file = _detect_locked_remote_debug_pref(str(browser_bin))

    assert locked_file == prefs_dir / "vendor.js"


def test_launch_managed_firefox_debug_rejects_locked_firefox_build(tmp_path):
    browser_root = tmp_path / "firefox"
    prefs_dir = browser_root / "browser" / "defaults" / "preferences"
    prefs_dir.mkdir(parents=True)
    browser_bin = browser_root / "firefox"
    browser_bin.write_text("", encoding="utf-8")
    (prefs_dir / "vendor.js").write_text(
        'pref("devtools.debugger.remote-enabled", false, locked);\n',
        encoding="utf-8",
    )
    spec = FirefoxDebugLaunchSpec(
        debug_url="ws://127.0.0.1:6000",
        browser_path=str(browser_bin),
        profile_path=tmp_path / "profile",
        seed_profile_path=None,
        start_url="https://gengo.com/t/jobs/status/available/realtime",
        port=6000,
    )

    with patch("gengowatcher.browser_debug_launcher.subprocess.Popen") as mock_popen:
        try:
            launch_managed_firefox_debug(spec)
            assert False, "Expected locked Firefox build to be rejected"
        except RuntimeError as exc:
            assert "disables DevTools remote debugging" in str(exc)

    mock_popen.assert_not_called()


def test_launch_managed_firefox_debug_checks_binary_before_profile_write(tmp_path):
    spec = FirefoxDebugLaunchSpec(
        debug_url="ws://127.0.0.1:6000",
        browser_path=str(tmp_path / "missing-firefox"),
        profile_path=tmp_path / "profile",
        seed_profile_path=None,
        start_url="https://gengo.com/t/jobs/status/available/realtime",
        port=6000,
    )

    with (
        patch(
            "gengowatcher.browser_debug_launcher.ensure_managed_firefox_profile"
        ) as mock_ensure,
        patch("gengowatcher.browser_debug_launcher.subprocess.Popen") as mock_popen,
    ):
        try:
            launch_managed_firefox_debug(spec)
            assert False, "Expected missing Firefox executable to be rejected"
        except RuntimeError as exc:
            assert "Firefox executable not found" in str(exc)
            assert isinstance(exc.__cause__, FileNotFoundError)

    mock_ensure.assert_not_called()
    mock_popen.assert_not_called()
