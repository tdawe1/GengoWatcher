"""Comprehensive tests for src/gengowatcher/watcher.py - additional coverage."""

import pytest
import logging
import concurrent.futures
from unittest.mock import MagicMock, patch, mock_open
import collections
import asyncio
import threading

from gengowatcher.watcher import GengoWatcher
from gengowatcher.config import AppConfig
from gengowatcher.state import AppState


@pytest.fixture
def logger():
    """Create a test logger."""
    return logging.getLogger("test")


@pytest.fixture
def mock_config(tmp_path):
    """Create a comprehensive mock config."""
    config = MagicMock(spec=AppConfig)
    config_data = {
        "Watcher": {
            "min_reward": 5.0,
            "use_custom_user_agent": False,
            "feed_url": "https://example.com/feed",
            "check_interval": 60,
            "gengo_rss_interval_min_sec": 31,
            "gengo_rss_interval_max_sec": 60,
            "enable_notifications": True,
            "enable_sound": True,
        },
        "Paths": {
            "browser_path": "",
            "browser_args": "{url}",
            "notification_icon_path": "/path/to/icon.png",
            "sound_file": "/path/to/sound.mp3",
            "all_entries_log": str(tmp_path / "entries.csv"),
        },
        "Network": {
            "user_agent_email": "test@example.com",
            "max_backoff": 300,
            "clean_close_backoff_min": 20,
            "clean_close_backoff_max": 45,
            "reconnect_jitter_max": 5,
            "browser_user_agent": "Test Browser",
        },
        "Logging": {"log_all_entries_enabled": False},
        "AutoAccept": {
            "enabled": False,
            "job_sources": "rss,websocket",
            "min_reward": 0.0,
            "max_reward": 999999.0,
        },
        "WebSocket": {
            "enable_websocket": False,
            "user_id": 12345,
            "user_session": "test_session",
            "user_key": "test_key",
            "wss_url": "wss://test.example.com",
            "browser_debug_url": "",
            "session_quiet_probe_sec": 90,
            "session_quiet_stale_after_sec": 300,
            "planned_reconnect_min_sec": 300,
            "planned_reconnect_max_sec": 3600,
            "browser_activity_min_sec": 300,
            "browser_activity_max_sec": 3600,
        },
        "EmailMonitor": {"enabled": False},
        "WebsiteMonitor": {"enabled": False},
        "Cancellation": {
            "enabled": True,
            "min_improvement_ratio": 2.0,
            "extreme_threshold": 1000.0,
        },
        "DebugCategories": {"raw": False},
    }

    def get_side_effect(section, key, **kwargs):
        fallback = kwargs.get("fallback", None)
        return config_data.get(section, {}).get(key, fallback)

    config.get.side_effect = get_side_effect
    config.getint.side_effect = lambda s, k, **_: int(get_side_effect(s, k, **_) or 0)
    config.getboolean.side_effect = lambda s, k, **_: bool(get_side_effect(s, k, **_))
    config.getfloat.side_effect = lambda s, k, **_: float(
        get_side_effect(s, k, **_) or 0.0
    )
    config.config = config_data
    config.CONFIG_FILE = "test_config.ini"
    config._config_parser = MagicMock()
    config._config_parser.sections.return_value = list(config_data.keys())
    config._config_parser.options.side_effect = lambda s: list(
        config_data.get(s, {}).keys()
    )

    return config


@pytest.fixture
def mock_state():
    """Create a mock state."""
    state = MagicMock(spec=AppState)
    state.seen_job_ids = collections.deque(maxlen=50)
    state.last_seen_rss_link = None
    state.last_seen_link = None
    state.total_new_entries_found = 0
    state.accepted_jobs = []
    state.failed_jobs = []
    return state


@pytest.fixture
def watcher_instance(mock_config, mock_state, logger):
    """Create a watcher instance for testing."""
    return GengoWatcher(mock_config, mock_state, logger)


class TestWatcherInitialization:
    """Test GengoWatcher initialization."""

    def test_initialization_with_valid_config(self, mock_config, mock_state, logger):
        """Test successful initialization."""
        watcher = GengoWatcher(mock_config, mock_state, logger)
        assert watcher.config == mock_config
        assert watcher.state == mock_state
        assert watcher.logger == logger
        assert watcher.start_time > 0
        assert watcher.session_new_entries == 0
        assert watcher.websocket_status == "Disabled"

    def test_run_launches_managed_debug_browser_for_native_listener_gateway_mode(
        self, watcher_instance
    ):
        """Gateway mode still needs the native debug browser for page observation."""
        watcher_instance.config.config["WebSocket"].update(
            {
                "use_gateway": True,
                "gateway_url": "http://127.0.0.1:8000",
                "browser_debug_auto_launch": True,
            }
        )
        watcher_instance.config.config["Browser"] = {
            "backend": "native",
            "debug_url": "ws://127.0.0.1:6000",
        }
        watcher_instance.config.config["NativeBrowserListener"] = {
            "enabled": True,
            "capture_interval_ms": 750,
        }
        watcher_instance.shutdown_event.wait = MagicMock(return_value=True)

        with (
            patch(
                "gengowatcher.watcher.maybe_launch_managed_firefox_debug",
                return_value=True,
            ) as launch_debug_browser,
            patch("threading.Thread"),
        ):
            watcher_instance.run()

        launch_debug_browser.assert_called_once_with(
            watcher_instance.config,
            "ws://127.0.0.1:6000",
            logger=watcher_instance.logger,
        )
        assert watcher_instance.websocket_status == "Gateway Connected"
        assert watcher_instance.native_browser_status == "Started"

    def test_initialization_warns_when_browser_session_differs(
        self, mock_config, mock_state
    ):
        """Warn when config token differs from the live browser token."""
        logger = MagicMock()
        mock_config.config["WebSocket"]["browser_debug_url"] = "http://127.0.0.1:9222"

        with patch(
            "gengowatcher.watcher.fetch_browser_session_snapshot_sync",
            return_value=MagicMock(
                session_token="fresh-browser-token",
            ),
        ):
            GengoWatcher(mock_config, mock_state, logger)

        warning_messages = [str(call.args[0]) for call in logger.warning.call_args_list]
        assert any(
            "user_session differs from the live browser session" in message
            for message in warning_messages
        )

    def test_initialization_skips_browser_session_check_without_debug_url(
        self, mock_config, mock_state
    ):
        """No browser session lookup should happen without a debug URL."""
        logger = MagicMock()

        with patch(
            "gengowatcher.watcher_session_sync.fetch_browser_session_snapshot_sync"
        ) as mock_fetch:
            GengoWatcher(mock_config, mock_state, logger)

        mock_fetch.assert_not_called()

    @pytest.mark.parametrize(
        ("secret", "expected"),
        [
            ("", ""),
            ("abc", "***"),
            ("abcdefgh", "a******h"),
            ("abcdefghij", "abcd...ghij"),
        ],
    )
    def test_mask_secret_masks_short_values(self, secret, expected):
        assert GengoWatcher._mask_secret(secret) == expected

    def test_sync_session_from_browser_updates_config(self, watcher_instance):
        """Browser session sync should persist a newer token."""
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("WebSocket", "browser_debug_url"): "http://127.0.0.1:9222",
            ("WebSocket", "user_session"): "stale-token",
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )

        with patch(
            "gengowatcher.watcher_session_sync.fetch_browser_session_snapshot_sync",
            return_value=MagicMock(
                session_token="fresh-token",
                user_agent="Helium Browser",
                accept_language="en-GB,en-US;q=0.9",
            ),
        ):
            changed = watcher_instance._sync_session_from_browser()

        assert changed is True
        watcher_instance.config.set.assert_any_call(
            "WebSocket", "user_session", "fresh-token"
        )
        watcher_instance.config.set.assert_any_call(
            "Network", "browser_user_agent", "Helium Browser"
        )
        watcher_instance.config.set.assert_any_call(
            "Network", "browser_accept_language", "en-GB,en-US;q=0.9"
        )
        watcher_instance.config.save_config.assert_called()

    def test_sync_session_before_websocket_connect_runs_initial_sync(
        self, watcher_instance
    ):
        """Websocket startup should sync once so session health is not stale."""
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("WebSocket", "browser_debug_url"): "http://127.0.0.1:9222",
        }.get((s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback")))
        watcher_instance._sync_session_from_browser = MagicMock(return_value=False)

        assert watcher_instance._sync_session_before_websocket_connect() is True

        watcher_instance._sync_session_from_browser.assert_called_once_with(
            fail_hard=True,
            alert_on_failure=True,
        )

    def test_sync_session_before_websocket_connect_skips_without_debug_url(
        self, watcher_instance
    ):
        """No browser debug URL means there is nothing to sync before connect."""
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("WebSocket", "browser_debug_url"): "",
        }.get((s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback")))
        watcher_instance._sync_session_from_browser = MagicMock()

        assert watcher_instance._sync_session_before_websocket_connect() is True
        watcher_instance._sync_session_from_browser.assert_not_called()

    def test_sync_session_from_browser_fail_hard_alerts_and_stops_without_cache(
        self, watcher_instance
    ):
        """Strict sync failures remain fatal when no cached websocket auth exists."""
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("WebSocket", "browser_debug_url"): "http://127.0.0.1:9222",
            ("WebSocket", "user_session"): "REPLACE_WITH_YOUR_SESSION_TOKEN",
            ("WebSocket", "user_id"): 0,
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )
        watcher_instance.show_notification = MagicMock()

        with patch(
            "gengowatcher.watcher_session_sync.fetch_browser_session_snapshot_sync",
            side_effect=RuntimeError("browser gone"),
        ):
            changed = watcher_instance._sync_session_from_browser(
                fail_hard=True,
                alert_on_failure=True,
            )

        assert changed is False
        assert watcher_instance._websocket_sync_failed is True
        watcher_instance.show_notification.assert_called_once()

    def test_sync_session_from_browser_fail_hard_falls_back_to_cached_credentials(
        self, watcher_instance
    ):
        """Cached websocket auth should keep realtime alive when browser sync is flaky."""
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("WebSocket", "browser_debug_url"): "http://127.0.0.1:9222",
            ("WebSocket", "user_session"): "cached-session-token",
            ("WebSocket", "user_id"): 12345,
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )
        watcher_instance.show_notification = MagicMock()

        with patch(
            "gengowatcher.watcher_session_sync.fetch_browser_session_snapshot_sync",
            side_effect=RuntimeError("browser gone"),
        ):
            changed = watcher_instance._sync_session_from_browser(
                fail_hard=True,
                alert_on_failure=True,
            )

        assert changed is False
        assert watcher_instance._websocket_sync_failed is False
        assert watcher_instance._websocket_sync_failure_reason is None
        assert watcher_instance.websocket_status != "Session Sync Failed"
        watcher_instance.show_notification.assert_not_called()

    def test_sync_session_from_browser_uses_dedicated_failure_sound_override(
        self, watcher_instance
    ):
        """Browser sync failures should use the dedicated sound override when set."""
        watcher_instance.show_notification = MagicMock()
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("WebSocket", "browser_debug_url"): "http://127.0.0.1:9222",
            ("WebSocket", "user_session"): "REPLACE_WITH_YOUR_SESSION_TOKEN",
            (
                "Paths",
                "browser_session_sync_failed_sound_file",
            ): "assets/sync-failed.wav",
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )

        with patch(
            "gengowatcher.watcher_session_sync.fetch_browser_session_snapshot_sync",
            side_effect=RuntimeError("browser gone"),
        ):
            changed = watcher_instance._sync_session_from_browser(
                fail_hard=False,
                alert_on_failure=True,
            )

        assert changed is False
        watcher_instance.show_notification.assert_called_once_with(
            message="Browser session sync failed: browser gone",
            title="GengoWatcher Session Sync Failed",
            play_sound=True,
            sound_file="assets/sync-failed.wav",
        )

    def test_sync_session_from_browser_does_not_touch_user_key(self, watcher_instance):
        """Browser sync should remain session-only and leave user_key untouched."""
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("WebSocket", "browser_debug_url"): "http://127.0.0.1:9222",
            ("WebSocket", "user_session"): "fresh-token",
            ("WebSocket", "user_key"): "REPLACE_WITH_YOUR_USER_KEY",
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )

        with patch(
            "gengowatcher.watcher_session_sync.fetch_browser_session_snapshot_sync",
            return_value=MagicMock(
                session_token="fresh-token",
                user_agent="Helium Browser",
                accept_language="en-GB,en-US;q=0.9",
            ),
        ):
            changed = watcher_instance._sync_session_from_browser()

        assert changed is True
        assert ("WebSocket", "user_key", "") not in [
            call.args for call in watcher_instance.config.set.call_args_list
        ]

    def test_sync_session_from_browser_launches_managed_firefox_when_attach_fails(
        self, watcher_instance
    ):
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("WebSocket", "browser_debug_url"): "ws://127.0.0.1:6000",
            ("WebSocket", "user_session"): "stale-token",
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )

        with (
            patch(
                "gengowatcher.watcher_session_sync.fetch_browser_session_snapshot_sync",
                side_effect=[
                    RuntimeError("attach failed"),
                    MagicMock(
                        session_token="fresh-token",
                        user_agent="Firefox",
                        accept_language="en-GB",
                    ),
                ],
            ) as mock_fetch,
            patch(
                "gengowatcher.watcher_session_sync.maybe_launch_managed_firefox_debug",
                return_value=True,
            ) as mock_launch,
            patch(
                "gengowatcher.watcher_session_sync.get_firefox_debug_retry_window",
                return_value=(2.0, 0.01),
            ),
            patch("gengowatcher.watcher.time.sleep"),
        ):
            changed = watcher_instance._sync_session_from_browser()

        assert changed is True
        assert mock_fetch.call_count == 2
        mock_launch.assert_called_once()
        watcher_instance.config.set.assert_any_call(
            "WebSocket", "user_session", "fresh-token"
        )

    def test_get_effective_rss_wait_range_uses_randomized_gengo_window(
        self, watcher_instance
    ):
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("Watcher", "check_interval"): 45,
            ("Watcher", "feed_url"): "https://gengo.com/rss/available_jobs/token",
            ("Watcher", "gengo_rss_interval_min_sec"): 31,
            ("Watcher", "gengo_rss_interval_max_sec"): 60,
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )

        assert watcher_instance._get_effective_rss_wait_range_seconds() == (31.0, 60.0)
        assert watcher_instance._get_effective_rss_check_interval() == 60.0

    def test_pick_next_rss_wait_seconds_randomizes_gengo_feed_window(
        self, watcher_instance
    ):
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("Watcher", "check_interval"): 45,
            ("Watcher", "feed_url"): "https://gengo.com/rss/available_jobs/token",
            ("Watcher", "gengo_rss_interval_min_sec"): 31,
            ("Watcher", "gengo_rss_interval_max_sec"): 60,
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )

        with patch(
            "gengowatcher.watcher.random.uniform", return_value=44.5
        ) as mock_uniform:
            wait_time = watcher_instance._pick_next_rss_wait_seconds()

        assert wait_time == 44.5
        mock_uniform.assert_called_once_with(31.0, 60.0)

    def test_get_effective_rss_check_interval_leaves_non_gengo_feeds_unchanged(
        self, watcher_instance
    ):
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("Watcher", "check_interval"): 45,
            ("Watcher", "feed_url"): "https://example.com/feed.xml",
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )

        assert watcher_instance._get_effective_rss_check_interval() == 45.0

    def test_pick_planned_websocket_reconnect_delay_uses_configured_window(
        self, watcher_instance
    ):
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("WebSocket", "planned_reconnect_min_sec"): 300,
            ("WebSocket", "planned_reconnect_max_sec"): 3600,
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )

        with patch(
            "gengowatcher.watcher.random.uniform", return_value=1800.0
        ) as mock_uniform:
            delay = watcher_instance._pick_planned_websocket_reconnect_delay_seconds()

        assert delay == 1800.0
        mock_uniform.assert_called_once_with(300.0, 3600.0)

    def test_pick_browser_activity_delay_uses_configured_window(self, watcher_instance):
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("WebSocket", "browser_activity_min_sec"): 300,
            ("WebSocket", "browser_activity_max_sec"): 3600,
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )

        with patch(
            "gengowatcher.watcher.random.uniform", return_value=900.0
        ) as mock_uniform:
            delay = watcher_instance._pick_browser_activity_delay_seconds()

        assert delay == 900.0
        mock_uniform.assert_called_once_with(300.0, 3600.0)

    def test_perform_browser_activity_uses_browser_debug_url(self, watcher_instance):
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("WebSocket", "browser_debug_url"): "http://127.0.0.1:9222",
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )
        watcher_instance._last_browser_activity_action = "reload"

        with patch(
            "gengowatcher.watcher.refresh_browser_page_activity_sync",
            return_value="summary_roundtrip",
        ) as mock_refresh:
            action = watcher_instance._perform_browser_activity()

        assert action == "summary_roundtrip"
        assert watcher_instance._last_browser_activity_action == "summary_roundtrip"
        mock_refresh.assert_called_once_with(
            "http://127.0.0.1:9222",
            previous_action="reload",
        )

    def test_get_health_snapshot_marks_websocket_stale_and_auto_disabled(
        self, watcher_instance
    ):
        """Health snapshot should surface stale and disabled states honestly."""
        watcher_instance.websocket_status = "Live"
        watcher_instance.websocket_last_pong_ts = None
        watcher_instance.last_check_time = None
        watcher_instance.rss_action = "Waiting"
        watcher_instance.is_processing = False
        watcher_instance._browser_session_last_sync_ts = None
        watcher_instance._browser_session_last_sync_state = "idle"
        watcher_instance._browser_session_last_sync_detail = "never synced"
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("Watcher", "check_interval"): 45,
            ("WebSocket", "enable_websocket"): True,
            ("WebSocket", "browser_debug_url"): "http://127.0.0.1:9222",
            ("EmailMonitor", "enabled"): False,
            ("WebsiteMonitor", "enabled"): True,
            ("AutoAccept", "enabled"): False,
            ("AutoAccept", "browser_profile_path"): "",
            ("BrowserWorker", "enabled"): False,
            ("Cancellation", "enabled"): False,
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )
        watcher_instance.config.getboolean.side_effect = lambda s, k, **kw: bool(
            {
                ("WebSocket", "enable_websocket"): True,
                ("EmailMonitor", "enabled"): False,
                ("WebsiteMonitor", "enabled"): True,
                ("AutoAccept", "enabled"): False,
                ("BrowserWorker", "enabled"): False,
                ("Cancellation", "enabled"): False,
            }.get((s, k), kw.get("fallback", False))
        )
        watcher_instance.website_monitor_status = "Monitoring"
        watcher_instance.website_last_check_time = 999_996.0

        health = watcher_instance.get_health_snapshot(now=1_000_000.0)

        assert health["websocket"]["state"] == "stale"
        assert health["session"]["state"] == "stale"
        assert health["email"]["state"] == "disabled"
        assert health["browser"]["state"] == "healthy"
        assert health["auto"]["state"] == "disabled"
        assert health["workflow"]["state"] == "disabled"
        assert health["api_events"]["state"] in {"disabled", "healthy"}
        assert "webhooks" not in health

    def test_get_health_snapshot_reports_native_browser_listener(
        self, watcher_instance
    ):
        """Native browser mode should not show the deprecated browser scraper as off."""
        watcher_instance.websocket_status = "Disabled"
        watcher_instance.last_check_time = 999_996.0
        watcher_instance.rss_action = "Waiting"
        watcher_instance.is_processing = False
        watcher_instance._browser_session_last_sync_ts = None
        watcher_instance._browser_session_last_sync_state = "idle"
        watcher_instance._browser_session_last_sync_detail = "never synced"
        watcher_instance.native_browser_status = "Started"

        class FakeThread:
            def is_alive(self):
                return True

        class FakeNativeListener:
            debug_url = "ws://127.0.0.1:6000"
            last_success_ts = 999_998.0
            last_poll_ts = 999_998.0
            last_error = ""
            detected_collection_id = "34178179"
            last_workbench_url = "https://gengo.com/t/workbench/34178179#!/"
            workbench_detected_count = 1

        watcher_instance._native_listener = FakeNativeListener()
        watcher_instance._monitor_threads = {"native_browser": FakeThread()}
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("Watcher", "check_interval"): 45,
            ("WebSocket", "enable_websocket"): False,
            ("WebSocket", "browser_debug_url"): "ws://127.0.0.1:6000",
            ("EmailMonitor", "enabled"): False,
            ("WebsiteMonitor", "enabled"): False,
            ("NativeBrowserListener", "enabled"): True,
            ("AutoAccept", "enabled"): False,
            ("AutoAccept", "browser_profile_path"): "",
            ("BrowserWorker", "enabled"): False,
            ("Cancellation", "enabled"): False,
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )
        watcher_instance.config.getboolean.side_effect = lambda s, k, **kw: bool(
            {
                ("WebSocket", "enable_websocket"): False,
                ("EmailMonitor", "enabled"): False,
                ("WebsiteMonitor", "enabled"): False,
                ("NativeBrowserListener", "enabled"): True,
                ("AutoAccept", "enabled"): False,
                ("BrowserWorker", "enabled"): False,
                ("Cancellation", "enabled"): False,
            }.get((s, k), kw.get("fallback", False))
        )

        health = watcher_instance.get_health_snapshot(now=1_000_000.0)

        assert health["browser"]["state"] == "healthy"
        assert health["browser"]["detail"] == "workbench 34178179"
        assert health["browser"]["native_enabled"] is True
        assert health["browser"]["native_thread_alive"] is True
        assert health["browser"]["collection_id"] == "34178179"

    def test_sync_browser_session_for_quiet_socket_triggers_after_silence(
        self, watcher_instance
    ):
        """Quiet live sockets should proactively re-check the browser session."""
        watcher_instance.websocket_status = "Live"
        watcher_instance.websocket_connected_at_ts = 100.0
        watcher_instance.websocket_last_message_ts = None
        watcher_instance._browser_session_last_sync_ts = None
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("WebSocket", "browser_debug_url"): "http://127.0.0.1:9222",
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )
        watcher_instance.config.getint.side_effect = lambda s, k, **kw: int(
            {
                ("WebSocket", "session_quiet_probe_sec"): 90,
                ("WebSocket", "session_quiet_stale_after_sec"): 300,
            }.get(
                (s, k),
                watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
                or 0,
            )
        )

        with (
            patch.object(
                watcher_instance,
                "_pick_quiet_socket_sync_delay_seconds",
                return_value=900.0,
            ),
            patch.object(
                watcher_instance,
                "_sync_session_from_browser",
                return_value=True,
            ) as mock_sync,
        ):
            changed = watcher_instance._sync_browser_session_for_quiet_socket(
                current_time=450.0
            )

        assert changed is True
        assert watcher_instance._next_quiet_socket_sync_ts is None
        mock_sync.assert_called_once_with(fail_hard=False, alert_on_failure=False)

    def test_sync_browser_session_for_quiet_socket_respects_randomized_cooldown(
        self, watcher_instance
    ):
        watcher_instance.websocket_status = "Live"
        watcher_instance.websocket_connected_at_ts = 100.0
        watcher_instance.websocket_last_message_ts = None
        watcher_instance._browser_session_last_sync_ts = None
        watcher_instance._next_quiet_socket_sync_ts = None
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("WebSocket", "browser_debug_url"): "http://127.0.0.1:9222",
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )
        watcher_instance.config.getint.side_effect = lambda s, k, **kw: int(
            {
                ("WebSocket", "session_quiet_probe_sec"): 90,
                ("WebSocket", "session_quiet_stale_after_sec"): 300,
            }.get(
                (s, k),
                watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
                or 0,
            )
        )

        with (
            patch.object(
                watcher_instance,
                "_pick_quiet_socket_sync_delay_seconds",
                return_value=900.0,
            ),
            patch.object(
                watcher_instance,
                "_sync_session_from_browser",
                return_value=False,
            ) as mock_sync,
        ):
            first = watcher_instance._sync_browser_session_for_quiet_socket(
                current_time=450.0
            )
            second = watcher_instance._sync_browser_session_for_quiet_socket(
                current_time=800.0
            )

        assert first is False
        assert second is False
        assert watcher_instance._next_quiet_socket_sync_ts == 1350.0
        mock_sync.assert_called_once_with(fail_hard=False, alert_on_failure=False)

    def test_get_health_snapshot_marks_quiet_live_websocket_stale(
        self, watcher_instance
    ):
        """Quiet live sockets should be stale without using the hard stale sound."""
        watcher_instance.websocket_status = "Live"
        watcher_instance.websocket_connected_at_ts = 999_600.0
        watcher_instance.websocket_last_message_ts = None
        watcher_instance.websocket_last_pong_ts = 999_995.0
        watcher_instance.last_check_time = 999_980.0
        watcher_instance.rss_action = "Waiting"
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("Watcher", "check_interval"): 45,
            ("WebSocket", "browser_debug_url"): "http://127.0.0.1:9222",
            ("EmailMonitor", "enabled"): False,
            ("WebsiteMonitor", "enabled"): False,
            ("AutoAccept", "enabled"): False,
            ("AutoAccept", "browser_profile_path"): "",
            ("BrowserWorker", "enabled"): False,
            ("Cancellation", "enabled"): False,
        }.get(
            (s, k), watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
        )
        watcher_instance.config.getboolean.side_effect = lambda s, k, **kw: bool(
            {
                ("WebSocket", "enable_websocket"): True,
                ("EmailMonitor", "enabled"): False,
                ("WebsiteMonitor", "enabled"): False,
                ("AutoAccept", "enabled"): False,
                ("BrowserWorker", "enabled"): False,
                ("Cancellation", "enabled"): False,
            }.get((s, k), kw.get("fallback", False))
        )
        watcher_instance.config.getint.side_effect = lambda s, k, **kw: int(
            {
                ("WebSocket", "session_sync_interval_sec"): 14400,
                ("WebSocket", "session_quiet_stale_after_sec"): 300,
            }.get(
                (s, k),
                watcher_instance.config.config.get(s, {}).get(k, kw.get("fallback"))
                or 0,
            )
        )

        health = watcher_instance.get_health_snapshot(now=1_000_000.0)

        assert health["websocket"]["state"] == "stale"
        assert health["websocket"]["detail"] == "quiet 400s"
        assert health["websocket"]["quiet_age_sec"] == 400.0

    def test_initialization_validates_check_interval(
        self, mock_config, mock_state, logger
    ):
        """Test that check_interval is validated."""
        mock_config.get.side_effect = lambda s, k, **_: (
            0
            if (s, k) == ("Watcher", "check_interval")
            else mock_config.config.get(s, {}).get(k)
        )

        GengoWatcher(mock_config, mock_state, logger)
        # Should have been corrected to minimum of 5
        mock_config.set.assert_called()

    def test_csv_logging_setup_when_enabled(self, mock_config, mock_state, logger):
        """Test CSV logging setup."""
        mock_config.get.side_effect = lambda s, k, **kw: (
            True
            if (s, k) == ("Logging", "log_all_entries_enabled")
            else mock_config.config.get(s, {}).get(k, kw.get("fallback"))
        )

        with patch("builtins.open", mock_open()):
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 0
                watcher = GengoWatcher(mock_config, mock_state, logger)
                # CSV writer should be initialized
                assert watcher._csv_writer is not None


class TestRewardExtraction:
    """Test _extract_reward method."""

    def test_extract_reward_from_title(self, watcher_instance):
        """Test reward extraction from title."""
        entry = {"title": "Job - Reward: $12.34", "summary": ""}
        assert watcher_instance._extract_reward(entry) == 12.34

    def test_extract_reward_from_summary(self, watcher_instance):
        """Test reward extraction from summary."""
        entry = {"title": "Job", "summary": "Reward: US$ 5.50"}
        assert watcher_instance._extract_reward(entry) == 5.50

    def test_extract_reward_no_match(self, watcher_instance):
        """Test when no reward found."""
        entry = {"title": "Job", "summary": "No reward info"}
        assert watcher_instance._extract_reward(entry) == 0.0

    def test_extract_reward_invalid_format(self, watcher_instance):
        """Test handling of invalid reward format."""
        entry = {"title": "Reward: $invalid", "summary": ""}
        assert watcher_instance._extract_reward(entry) == 0.0

    def test_extract_reward_with_commas(self, watcher_instance):
        """Test extraction of large rewards with commas."""
        entry = {"title": "Reward: $1,234.56", "summary": ""}
        # The regex should handle this
        result = watcher_instance._extract_reward(entry)
        assert result > 0


class TestNotifications:
    """Test show_notification and related methods."""

    def test_show_notification_when_enabled(self, watcher_instance):
        """Test notification when enabled."""
        with patch("gengowatcher.notifier.send_notification") as mock_notify:
            with patch("gengowatcher.notifier.play_sound") as mock_sound:
                watcher_instance.show_notification(
                    "Test message", title="Test", play_sound=True
                )
                mock_notify.assert_called_once()
                mock_sound.assert_called_once()

    def test_show_notification_uses_override_sound_when_provided(
        self, watcher_instance
    ):
        """Explicit sound overrides should bypass the default alert sound."""
        with patch("gengowatcher.notifier.send_notification"):
            with patch("gengowatcher.notifier.play_sound") as mock_sound:
                watcher_instance.show_notification(
                    "Test message",
                    title="Test",
                    play_sound=True,
                    sound_file="assets/ws-stale.wav",
                )
                mock_sound.assert_called_once_with("assets/ws-stale.wav")

    def test_alert_on_health_snapshot_uses_websocket_stale_sound_override(
        self, watcher_instance
    ):
        """Websocket stale alerts should use the dedicated sound override when set."""
        watcher_instance.config.get.side_effect = lambda section, key, **kwargs: {
            ("Paths", "websocket_stale_sound_file"): "assets/ws-stale.wav",
        }.get((section, key), kwargs.get("fallback", ""))

        with patch.object(watcher_instance, "show_notification") as mock_notify:
            watcher_instance.alert_on_health_snapshot(
                {"websocket": {"state": "stale", "detail": "pong overdue"}}
            )

        mock_notify.assert_called_once_with(
            message="Websocket is stale: pong overdue",
            title="GengoWatcher Telemetry Alert",
            play_sound=True,
            sound_file="assets/ws-stale.wav",
        )

    def test_alert_on_health_snapshot_quiet_websocket_stale_is_silent(
        self, watcher_instance
    ):
        """Quiet websocket periods should not play the stale alert sound."""
        watcher_instance.config.get.side_effect = lambda section, key, **kwargs: {
            ("Paths", "websocket_stale_sound_file"): "assets/ws-stale.wav",
        }.get((section, key), kwargs.get("fallback", ""))

        with patch.object(watcher_instance, "show_notification") as mock_notify:
            watcher_instance.alert_on_health_snapshot(
                {"websocket": {"state": "stale", "detail": "quiet 300s"}}
            )

        mock_notify.assert_called_once_with(
            message="Websocket is stale: quiet 300s",
            title="GengoWatcher Telemetry Alert",
            play_sound=False,
            sound_file="assets/ws-stale.wav",
        )

    def test_show_notification_with_link(self, watcher_instance):
        """Test notification with link opening."""
        with patch("gengowatcher.notifier.send_notification"):
            with patch.object(watcher_instance, "open_in_browser") as mock_open:
                watcher_instance.show_notification(
                    "Test", open_link=True, url="http://example.com"
                )
                mock_open.assert_called_once_with("http://example.com")

    def test_open_in_browser_with_default_browser(self, watcher_instance):
        """Test opening URL with default browser."""
        with patch("gengowatcher.watcher.webbrowser.open") as mock_open:
            watcher_instance.open_in_browser("http://example.com")
            mock_open.assert_called_once_with("http://example.com")

    def test_open_in_browser_with_custom_browser(self, watcher_instance):
        """Test opening URL with custom browser."""
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("Paths", "browser_path"): "/usr/bin/browser",
            ("Paths", "browser_args"): "--new-window {url}",
        }.get((s, k), kw.get("fallback", ""))

        with patch("pathlib.Path.is_file", return_value=True):
            with patch("gengowatcher.watcher.subprocess.Popen") as mock_popen:
                watcher_instance.open_in_browser("http://example.com")
                mock_popen.assert_called_once()

    def test_open_in_browser_exception_handling(self, watcher_instance):
        """Test browser opening exception handling."""
        with patch(
            "gengowatcher.watcher.webbrowser.open",
            side_effect=Exception("Browser error"),
        ):
            # Should not raise exception
            watcher_instance.open_in_browser("http://example.com")


class TestJobProcessing:
    """Test job processing logic."""

    def test_process_new_job_deduplication(self, watcher_instance):
        """Test that duplicate jobs are ignored."""
        watcher_instance.show_notification = MagicMock()

        # Process job first time
        watcher_instance._process_new_job(
            123, "Job 1", 10.0, "http://example.com/123", "RSS"
        )
        assert 123 in watcher_instance.state.seen_job_ids
        assert watcher_instance.session_new_entries == 1

        # Process same job again
        watcher_instance._process_new_job(
            123, "Job 1", 10.0, "http://example.com/123", "RSS"
        )
        assert watcher_instance.session_new_entries == 1  # Should not increment

    def test_process_new_job_min_reward_filter(self, watcher_instance):
        """Test minimum reward filtering."""
        watcher_instance.config.get.side_effect = lambda s, k, **_: (
            20.0
            if (s, k) == ("Watcher", "min_reward")
            else watcher_instance.config.config.get(s, {}).get(k)
        )
        watcher_instance.show_notification = MagicMock()

        # Job below minimum reward
        watcher_instance._process_new_job(
            456, "Low Value", 10.0, "http://example.com/456", "RSS"
        )
        assert watcher_instance.session_new_entries == 0
        assert 456 not in watcher_instance.state.seen_job_ids

    def test_process_new_job_filtered_event_does_not_block_later_eligible_copy(
        self, watcher_instance
    ):
        """A filtered event must not prevent a later eligible update for the same job."""
        min_reward = 20.0

        def config_get(section, key, **_):
            if (section, key) == ("Watcher", "min_reward"):
                return min_reward
            return watcher_instance.config.config.get(section, {}).get(key)

        watcher_instance.config.get.side_effect = config_get
        watcher_instance.show_notification = MagicMock()

        watcher_instance._process_new_job(
            456, "Low Value", 10.0, "http://example.com/456", "WebSocket"
        )
        assert watcher_instance.show_notification.call_count == 0
        assert 456 not in watcher_instance.state.seen_job_ids

        min_reward = 5.0
        watcher_instance._process_new_job(
            456, "Eligible Value", 25.0, "http://example.com/456", "RSS"
        )

        assert watcher_instance.show_notification.call_count == 1
        assert 456 in watcher_instance.state.seen_job_ids

    def test_process_new_job_stores_in_state(self, watcher_instance):
        """Test that jobs are stored in state."""
        watcher_instance.show_notification = MagicMock()
        watcher_instance._process_new_job(
            789, "Job", 15.0, "http://example.com/789", "WebSocket"
        )

        watcher_instance.state.add_job.assert_called_once()
        job_data = watcher_instance.state.add_job.call_args[0][0]
        assert job_data["id"] == "789"
        assert job_data["reward"] == 15.0
        assert job_data["source"] == "WebSocket"

    def test_process_new_job_auto_accept_check(self, watcher_instance):
        """Test auto-accept eligibility check."""
        watcher_instance.show_notification = MagicMock()
        watcher_instance.job_acceptance_engine.is_job_eligible = MagicMock(
            return_value=True
        )
        watcher_instance.config.config["AutoAccept"]["allow_http_fallback"] = True

        with patch("threading.Thread") as mock_thread:
            watcher_instance._process_new_job(
                999, "High Value", 100.0, "http://example.com/999", "RSS"
            )
            # Should spawn acceptance thread
            mock_thread.assert_called()


class TestFeedProcessing:
    """Test RSS feed processing."""

    def test_process_feed_entries_no_new_entries(self, watcher_instance):
        """Test when all entries are already seen."""
        watcher_instance.state.last_seen_rss_link = "http://example.com/job/100"
        watcher_instance._process_new_job = MagicMock()

        entries = [{"link": "http://example.com/job/100"}]
        watcher_instance._process_feed_entries(entries)

        watcher_instance._process_new_job.assert_not_called()

    def test_process_feed_entries_with_new_entries(self, watcher_instance):
        """Test processing new entries."""
        watcher_instance.state.last_seen_rss_link = None
        watcher_instance._process_new_job = MagicMock()

        entries = [
            {"link": "https://gengo.com/t/jobs/details/101/", "title": "Job 1"},
            {"link": "https://gengo.com/t/jobs/details/102/", "title": "Job 2"},
        ]
        watcher_instance._process_feed_entries(entries)

        assert watcher_instance._process_new_job.call_count == 2

    def test_process_feed_entries_invalid_link(self, watcher_instance):
        """Test handling of entries with invalid links."""
        watcher_instance._process_new_job = MagicMock()

        entries = [
            {"link": "http://invalid.com/no-job-id", "title": "Bad Entry"},
        ]
        watcher_instance._process_feed_entries(entries)

        watcher_instance._process_new_job.assert_not_called()

    def test_process_feed_entries_empty_list(self, watcher_instance):
        """Test with empty entries list."""
        watcher_instance._process_new_job = MagicMock()
        watcher_instance._process_feed_entries([])
        watcher_instance._process_new_job.assert_not_called()


class TestRSSFetching:
    """Test RSS fetching."""

    @patch("gengowatcher.watcher.feedparser.parse")
    def test_fetch_rss_success(self, mock_parse, watcher_instance):
        """Test successful RSS fetch."""
        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.status = 200
        mock_feed.entries = [{"title": "Job 1"}]
        mock_parse.return_value = mock_feed

        result = watcher_instance.fetch_rss()

        assert result == mock_feed
        mock_parse.assert_called_once()

    @patch("gengowatcher.watcher.feedparser.parse")
    def test_fetch_rss_rate_limited(self, mock_parse, watcher_instance):
        """Test handling of rate limit (429)."""
        mock_feed = MagicMock()
        mock_feed.status = 429
        mock_parse.return_value = mock_feed

        result = watcher_instance.fetch_rss()

        assert result is None

    @patch("gengowatcher.watcher.feedparser.parse")
    def test_fetch_rss_http_error(self, mock_parse, watcher_instance):
        """Test handling of HTTP errors."""
        mock_feed = MagicMock()
        mock_feed.status = 500
        mock_parse.return_value = mock_feed

        result = watcher_instance.fetch_rss()

        assert result is None

    @patch("gengowatcher.watcher.feedparser.parse")
    def test_fetch_rss_parse_error(self, mock_parse, watcher_instance):
        """Test handling of parse errors."""
        mock_feed = MagicMock()
        mock_feed.bozo = True
        mock_feed.bozo_exception = Exception("mismatched tag")
        mock_parse.return_value = mock_feed

        result = watcher_instance.fetch_rss()

        assert result is None

    @patch("gengowatcher.watcher.feedparser.parse")
    def test_fetch_rss_with_custom_user_agent(self, mock_parse, watcher_instance):
        """Test RSS fetch with custom user agent."""
        watcher_instance.config.get.side_effect = lambda s, k, **kw: {
            ("Watcher", "use_custom_user_agent"): True,
            ("Network", "user_agent_email"): "custom@example.com",
            ("Watcher", "feed_url"): "https://example.com/feed",
        }.get((s, k), kw.get("fallback", ""))

        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_parse.return_value = mock_feed

        watcher_instance.fetch_rss()

        # Check that custom headers were used
        call_args = mock_parse.call_args
        assert "request_headers" in call_args.kwargs
        assert "User-Agent" in call_args.kwargs["request_headers"]

    def test_fetch_rss_timeout_does_not_spawn_new_worker_threads(
        self, watcher_instance
    ):
        """Test that repeated timeouts reuse the same in-flight future."""

        class HangingFuture:
            def cancel(self):
                return False

            def done(self):
                return False

            def result(self, timeout):
                raise concurrent.futures.TimeoutError()

        hanging_future = HangingFuture()
        mock_executor = MagicMock()
        mock_executor.submit.return_value = hanging_future

        with patch(
            "gengowatcher.watcher.concurrent.futures.ThreadPoolExecutor",
            return_value=mock_executor,
        ):
            assert watcher_instance.fetch_rss() is None
            assert watcher_instance.fetch_rss() is None

        # Second call should detect the in-flight future and avoid submitting again.
        assert mock_executor.submit.call_count == 1
        mock_executor.shutdown.assert_not_called()


class TestConfigManagement:
    """Test configuration management."""

    def test_set_config_value(self, watcher_instance):
        """Test setting config values."""
        watcher_instance.set_config_value("Watcher", "check_interval", 120)
        watcher_instance.config.set.assert_called_with("Watcher", "check_interval", 120)
        watcher_instance.config.save_config.assert_called_once()

    def test_get_config_value(self, watcher_instance):
        """Test getting config values."""
        watcher_instance.config.get.return_value = 60
        value = watcher_instance.get_config_value("Watcher", "check_interval")
        assert value == 60

    def test_list_config_values(self, watcher_instance):
        """Test listing all config values."""
        result = watcher_instance.list_config_values()
        assert isinstance(result, dict)


class TestShutdown:
    """Test shutdown and cleanup."""

    def test_handle_exit_saves_state(self, watcher_instance):
        """Test that state is saved on exit."""
        watcher_instance.handle_exit()
        watcher_instance.state.save_state.assert_called_once()

    def test_handle_exit_closes_csv_log(self, watcher_instance):
        """Test that CSV log is closed on exit."""
        mock_file = MagicMock()
        watcher_instance._all_entries_log_file = mock_file

        watcher_instance.handle_exit()

        mock_file.flush.assert_called()
        mock_file.close.assert_called()

    def test_handle_exit_sets_shutdown_event(self, watcher_instance):
        """Test that shutdown event is set."""
        watcher_instance.handle_exit()
        assert watcher_instance.shutdown_event.is_set()

    def test_handle_exit_idempotent(self, watcher_instance):
        """Test that multiple calls to handle_exit are safe."""
        watcher_instance.handle_exit()
        watcher_instance.handle_exit()
        # Should not raise exception


class TestWebSocketIntegration:
    """Test WebSocket-related functionality."""

    def test_websocket_timeout_is_logged_as_warning(self, watcher_instance):
        """Handshake timeout should not fall through as an unexpected error."""
        watcher_instance.logger.warning = MagicMock()
        watcher_instance.logger.error = MagicMock()

        with patch(
            "gengowatcher.watcher.websockets.connect",
            side_effect=TimeoutError("open timed out"),
        ) as mock_connect:
            asyncio.run(watcher_instance._websocket_logic())

        assert mock_connect.call_args.kwargs["open_timeout"] == 20
        watcher_instance.logger.warning.assert_any_call(
            "WebSocket: Connection timed out during handshake/open: open timed out"
        )
        watcher_instance.logger.error.assert_not_called()
        assert watcher_instance.websocket_status == "Offline"

    def test_capture_raw_ws_message(self, watcher_instance):
        """Test raw message capture."""
        watcher_instance.config.get.side_effect = lambda s, k, **kw: (
            True if (s, k) == ("DebugCategories", "raw") else kw.get("fallback", False)
        )

        watcher_instance._capture_raw_ws_message('{"type": "test"}', "recv")

        messages = watcher_instance.get_raw_ws_messages()
        assert len(messages) == 1
        assert "test" in messages[0]

    def test_clear_raw_ws_messages(self, watcher_instance):
        """Test clearing raw message buffer."""
        watcher_instance.config.get.side_effect = lambda s, k, **kw: (
            True if (s, k) == ("DebugCategories", "raw") else kw.get("fallback", False)
        )
        watcher_instance._capture_raw_ws_message("test", "recv")

        watcher_instance.clear_raw_ws_messages()

        messages = watcher_instance.get_raw_ws_messages()
        assert len(messages) == 0

    def test_get_monitor_status(self, watcher_instance):
        """Test monitor status retrieval."""
        status = watcher_instance.get_monitor_status()
        assert isinstance(status, dict)
        assert "rss" in status
        assert "websocket" in status


class TestCancellationManager:
    """Test job cancellation functionality."""

    def test_get_cancellation_stats(self, watcher_instance):
        """Test cancellation stats retrieval."""
        watcher_instance.cancellation_manager.get_stats = MagicMock(
            return_value={"cancelled": 0}
        )
        stats = watcher_instance.get_cancellation_stats()
        assert stats is not None

    def test_configure_cancellation_manager(self, watcher_instance):
        """Test cancellation manager configuration."""
        watcher_instance.cancellation_manager.update_settings = MagicMock()
        watcher_instance._configure_cancellation_manager()
        watcher_instance.cancellation_manager.update_settings.assert_called_once()


class TestPromptConfiguration:
    """Test interactive configuration prompt."""

    def test_is_config_complete_with_placeholders(self, watcher_instance):
        """Test detection of incomplete config."""
        watcher_instance.config.get.side_effect = lambda *_, **__: (
            "REPLACE_WITH_YOUR_SESSION_TOKEN"
        )

        result = watcher_instance.is_config_complete([("WebSocket", "user_session")])
        assert result is False

    def test_is_config_complete_with_valid_config(self, watcher_instance):
        """Test detection of complete config."""
        watcher_instance.config.get.side_effect = lambda *_, **__: "valid_value"

        result = watcher_instance.is_config_complete([("Watcher", "feed_url")])
        assert result is True


class TestThreadSafety:
    """Test thread safety of watcher operations."""

    def test_process_new_job_thread_safe(self, watcher_instance):
        """Test that job processing is thread-safe."""
        watcher_instance.show_notification = MagicMock()

        def process_jobs(thread_idx):
            for i in range(10):
                job_id = f"{thread_idx}-{i}"
                watcher_instance._process_new_job(
                    job_id,
                    f"Job {job_id}",
                    10.0,
                    f"http://example.com/{job_id}",
                    "RSS",
                )

        threads = [
            threading.Thread(target=process_jobs, args=(thread_idx,))
            for thread_idx in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 50 jobs should be processed
        assert watcher_instance.session_new_entries == 50


class TestStateMachine:
    """Test watcher state transitions."""

    def test_websocket_status_transitions(self, watcher_instance):
        """Test WebSocket status changes."""
        assert watcher_instance.websocket_status == "Disabled"
        watcher_instance.websocket_status = "Connecting"
        assert watcher_instance.websocket_status == "Connecting"
        watcher_instance.websocket_status = "Live"
        assert watcher_instance.websocket_status == "Live"

    def test_rss_action_states(self, watcher_instance):
        """Test RSS action state changes."""
        watcher_instance.rss_action = "Fetching RSS"
        assert watcher_instance.rss_action == "Fetching RSS"


class TestEdgeCasesAndBoundaries:
    """Test edge cases and boundary conditions."""

    def test_extract_reward_with_zero(self, watcher_instance):
        """Test reward extraction with zero value."""
        entry = {"title": "Reward: $0.00", "summary": ""}
        assert watcher_instance._extract_reward(entry) == 0.0

    def test_process_new_job_with_zero_reward(self, watcher_instance):
        """Test processing job with zero reward."""
        watcher_instance.config.get.side_effect = lambda s, k, **_: (
            0.0
            if (s, k) == ("Watcher", "min_reward")
            else watcher_instance.config.config.get(s, {}).get(k)
        )
        watcher_instance.show_notification = MagicMock()
        watcher_instance._process_new_job(
            1, "Free Job", 0.0, "http://example.com/1", "RSS"
        )
        assert watcher_instance.session_new_entries == 1

    def test_process_feed_entries_with_missing_title(self, watcher_instance):
        """Test feed entry without title."""
        watcher_instance._process_new_job = MagicMock()
        entries = [{"link": "https://gengo.com/t/jobs/details/999/"}]
        watcher_instance._process_feed_entries(entries)
        # Should still process with default title

    def test_notify_test(self, watcher_instance):
        """Test notification test functionality."""
        with patch.object(watcher_instance, "show_notification") as mock_notify:
            watcher_instance.run_notify_test()
            mock_notify.assert_called_once()

    def test_simulate_new_job_notification(self, watcher_instance):
        """Test simulated job notification."""
        with patch.object(watcher_instance, "_process_new_job") as mock_process:
            watcher_instance._simulate_new_job_notification()
            mock_process.assert_called_once()
            # Check that it used test data
            call_args = mock_process.call_args[0]
            assert "TEST JOB" in call_args[1]
