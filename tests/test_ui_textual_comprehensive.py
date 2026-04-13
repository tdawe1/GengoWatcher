"""Comprehensive tests for src/gengowatcher/ui_textual.py"""

import pytest
from unittest.mock import MagicMock, patch, call
import tempfile
import pathlib
import time
import datetime
import logging
import re

from gengowatcher.logging_setup import UILoggingHandler
from gengowatcher.ui_textual import (
    TitleBar,
    MetricCard,
    MetricsRow,
    StatusIndicator,
    StatusRow,
    ActivityPreview,
    JobsPreview,
    HourlyActivity,
    ConfigPreview,
    SessionStats as SessionStatsWidget,
    StatsPanel,
    TelemetryPanel,
    GengoWatcherApp,
    TextualLogHandler,
    Icons,
    _build_semantic_color_palette,
    _with_timestamp_prefix,
    BAR_CHARS,
)
from gengowatcher.stats import StatsManager
from textual.css.query import NoMatches
from textual.theme import Theme
from textual.color import Color


@pytest.fixture
def mock_config():
    """Create a mock config for testing."""
    config = MagicMock()
    config.get.side_effect = lambda section, key: {
        ("Watcher", "source_lang"): "JA",
        ("Watcher", "target_lang"): "EN",
        ("Watcher", "check_interval"): 60,
        ("Watcher", "min_reward"): 10.0,
    }.get((section, key), "test_value")
    config.list_all.return_value = {
        "Watcher": {
            "source_lang": "JA",
            "target_lang": "EN",
            "check_interval": 60,
            "min_reward": 10.0,
        },
        "WebSocket": {"enable_websocket": True, "user_id": 12345},
    }
    return config


@pytest.fixture
def mock_state():
    """Create a mock state for testing."""
    state = MagicMock()
    state.session_start = time.time()
    state.total_new_entries_found = 42
    state.get_recent_jobs.return_value = [
        {
            "id": "123",
            "title": "JA→EN | Test Job",
            "reward": 10.50,
            "word_count": 100,
            "lang_pair": "JA→EN",
            "accepted": False,
            "source": "websocket",
        },
        {
            "id": "456",
            "title": "EN→JA | Another Job",
            "reward": 25.00,
            "word_count": 200,
            "lang_pair": "EN→JA",
            "accepted": True,
            "source": "email",
        },
    ]
    return state


@pytest.fixture
def mock_watcher():
    """Create a mock watcher for testing."""
    watcher = MagicMock()
    watcher.start_time = time.time()
    watcher.session_new_entries = 5
    watcher.session_total_value = 50.00
    watcher.websocket_status = "Live"
    watcher.rss_action = "Checking"
    watcher.websocket_connected = True
    watcher.email_monitor_status = "Polling"
    watcher.website_monitor_status = "Monitoring"
    watcher.captcha_enabled = False
    watcher.captcha_solving = False
    watcher.is_processing = False
    watcher.auto_accept_enabled = True
    watcher._email_monitor = MagicMock()
    watcher._website_monitor = MagicMock()
    return watcher


@pytest.fixture
def mock_stats():
    """Create a mock stats manager for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_path = pathlib.Path(tmpdir) / "stats.json"
        stats = StatsManager(stats_path=stats_path)
        stats.session.jobs_found = 10
        stats.session.jobs_accepted = 3
        stats.session.total_value = 75.50
        stats.all_time.total_jobs = 100
        stats.all_time.total_value = 1500.00
        stats.hourly_counts = {9: 5, 10: 8, 11: 12, 12: 15, 13: 10, 14: 6}
        yield stats


class TestIcons:
    """Test icon constants."""

    def test_icon_constants_defined(self):
        """Verify all icon constants are defined."""
        assert hasattr(Icons, "FOUND")
        assert hasattr(Icons, "ACCEPTED")
        assert hasattr(Icons, "VALUE")
        assert hasattr(Icons, "RATE")
        assert hasattr(Icons, "MIN_WORDS")
        assert hasattr(Icons, "WEBSOCKET")
        assert hasattr(Icons, "EMAIL")
        assert hasattr(Icons, "WEB")
        assert hasattr(Icons, "RSS")
        assert hasattr(Icons, "CAPTCHA")
        assert hasattr(Icons, "WORKFLOW")
        assert hasattr(Icons, "AUTO")

    def test_icon_values_are_strings(self):
        """Verify all icon values are strings."""
        assert isinstance(Icons.FOUND, str)
        assert isinstance(Icons.WEBSOCKET, str)
        assert isinstance(Icons.IDLE, str)


class TestThemeIntegration:
    """Theme integration tests for Textual palette compatibility."""

    def test_semantic_palette_is_derived_from_textual_theme(self):
        """Semantic UI colors should come from Theme-generated variables."""
        theme = Theme(
            name="test-theme",
            primary="#1a2b3c",
            secondary="#2b3c4d",
            warning="#3c4d5e",
            error="#4d5e6f",
            success="#5e6f70",
            accent="#6f7081",
            foreground="#d0d1d2",
            background="#101112",
            surface="#202122",
            panel="#303132",
            dark=True,
        )

        generated = theme.to_color_system().generate()
        palette = _build_semantic_color_palette(theme)

        assert palette["job_id"] == Color.parse(generated["primary"]).hex6
        assert palette["lang_pair"] == Color.parse(generated["secondary"]).hex6
        assert palette["money"] == Color.parse(generated["warning"]).hex6
        assert palette["success"] == Color.parse(generated["success"]).hex6
        assert palette["error_word"] == Color.parse(generated["error"]).hex6
        assert palette["url"] == Color.parse(generated["accent"]).hex6
        assert palette["default"] == Color.parse(generated["foreground"]).hex6
        assert palette["timestamp"] == Color.parse(generated["foreground-muted"]).hex6

    def test_css_uses_textual_variables_not_hardcoded_hex(self):
        """TUI CSS should reference Textual theme variables directly."""
        css_path = (
            pathlib.Path(__file__).resolve().parents[1]
            / "src"
            / "gengowatcher"
            / "gengo_watcher.tcss"
        )
        css = css_path.read_text(encoding="utf-8")

        assert "$primary" in css
        assert "$secondary" in css
        assert "$warning" in css
        assert "$error" in css
        assert "$success" in css
        assert "$accent" in css

        # Screen background should be explicitly controlled by theme color
        # (or transparent if inheriting terminal in future variants).
        assert re.search(
            r"Screen\s*\{[^}]*background:\s*(?:\$background|transparent)\s*;",
            css,
            re.DOTALL,
        )

        # No hardcoded hex color literals in the main stylesheet.
        assert re.search(r"#[0-9A-Fa-f]{3,8}", css) is None

    def test_css_restores_balanced_dashboard_grid_layout(self):
        """The dashboard grid should use two balanced rows again."""
        css_path = (
            pathlib.Path(__file__).resolve().parents[1]
            / "src"
            / "gengowatcher"
            / "gengo_watcher.tcss"
        )
        css = css_path.read_text(encoding="utf-8")

        assert "grid-rows: 1fr 1fr;" in css
        assert ".metric-label" in css


class TestTitleBar:
    """Test TitleBar widget."""

    @pytest.mark.asyncio
    async def test_title_bar_renders(self, mock_config):
        """Test that TitleBar renders with config."""
        title_bar = TitleBar(config=mock_config)
        assert title_bar.config == mock_config

    @pytest.mark.asyncio
    async def test_title_bar_without_config(self):
        """Test that TitleBar handles missing config."""
        title_bar = TitleBar(config=None)
        assert title_bar.config is None

    @pytest.mark.asyncio
    async def test_update_clock_without_widget_mounted(self, mock_config):
        """Test update_clock when widget isn't mounted yet."""
        title_bar = TitleBar(config=mock_config)
        # Should not raise exception
        title_bar.update_clock()


class TestMetricCard:
    """Test MetricCard widget."""

    def test_metric_card_initialization(self):
        """Test MetricCard initialization."""
        card = MetricCard("Test", "X", "42")
        assert card.label == "Test"
        assert card.icon == "X"
        assert card.value == "42"

    def test_metric_card_border_title(self):
        """Test that border_title is set."""
        card = MetricCard("Found", "▲", "10")
        assert card.border_title == "Found"

    @pytest.mark.asyncio
    async def test_update_value_not_mounted(self):
        """Test update_value when widget not mounted."""
        card = MetricCard("Test", "X", "0")
        # Should not raise exception
        card.update_value("42")


class TestMetricsRow:
    """Test MetricsRow widget."""

    @pytest.mark.asyncio
    async def test_metrics_row_initialization(self, mock_state):
        """Test MetricsRow initialization."""
        row = MetricsRow(state=mock_state)
        assert row.state == mock_state

    @pytest.mark.asyncio
    async def test_refresh_metrics_with_jobs(self, mock_state):
        """Test refresh_metrics with job data."""
        mock_state.session_start = time.time() - 3600  # 1 hour ago
        row = MetricsRow(state=mock_state)

        # Should not raise exception even if widgets not mounted
        row.refresh_metrics()

    @pytest.mark.asyncio
    async def test_refresh_metrics_without_state(self):
        """Test refresh_metrics with no state."""
        row = MetricsRow(state=None)
        # Should not raise exception
        row.refresh_metrics()

    @pytest.mark.asyncio
    async def test_metrics_calculation(self, mock_state):
        """Test metrics calculation logic."""
        mock_state.session_start = time.time() - 7200  # 2 hours ago
        MetricsRow(state=mock_state).refresh_metrics()

        jobs = mock_state.get_recent_jobs(limit=1000)
        found = len(jobs)
        accepted = sum(1 for j in jobs if j.get("accepted", False))
        total_value = sum(j.get("reward", 0) for j in jobs)

        assert found == 2
        assert accepted == 1
        assert total_value == 35.50


class TestStatusIndicator:
    """Test StatusIndicator widget."""

    def test_status_indicator_initialization(self):
        """Test StatusIndicator initialization."""
        indicator = StatusIndicator("●", "WS", id="test-ws")
        assert indicator.base_icon == "●"
        assert indicator.label_text == "WS"
        assert indicator.current_state == "idle"

    def test_status_state_constants(self):
        """Test that status icons are defined."""
        assert "idle" in StatusIndicator.ICONS
        assert "live" in StatusIndicator.ICONS
        assert "working" in StatusIndicator.ICONS
        assert "error" in StatusIndicator.ICONS

    def test_pulse_frames_defined(self):
        """Test that pulse animation frames exist."""
        assert len(StatusIndicator.PULSE_FRAMES) > 0

    def test_set_state(self):
        """Test state changes."""
        indicator = StatusIndicator("●", "WS", id="test-ws")
        indicator.set_state("live")
        assert indicator.current_state == "live"

        indicator.set_state("error")
        assert indicator.current_state == "error"

    def test_pulse_tick_when_not_live(self):
        """Test pulse tick in non-live state."""
        indicator = StatusIndicator("●", "WS", id="test-ws")
        indicator.set_state("idle")
        # Pulse tick shouldn't change anything in idle state
        indicator._pulse_tick()
        assert indicator._pulse_index == 0


class TestStatusRow:
    """Test StatusRow widget."""

    @pytest.mark.asyncio
    async def test_status_row_initialization(self, mock_watcher):
        """Test StatusRow initialization."""
        row = StatusRow(watcher=mock_watcher)
        assert row.watcher == mock_watcher

    @pytest.mark.asyncio
    async def test_refresh_status_without_watcher(self):
        """Test refresh when watcher is None."""
        row = StatusRow(watcher=None)
        # Should not raise exception
        row.refresh_status()

    @pytest.mark.asyncio
    async def test_websocket_status_detection(self, mock_watcher):
        """Test WebSocket status detection logic."""
        row = StatusRow(watcher=mock_watcher)

        # Test live status
        mock_watcher.websocket_connected = True
        mock_watcher.websocket_status = "Live"
        row.refresh_status()

        # Test connecting status
        mock_watcher.websocket_connected = False
        mock_watcher.websocket_status = "Connecting"
        row.refresh_status()

        # Test error status
        mock_watcher.websocket_status = "Connection error"
        row.refresh_status()


class TestActivityPreview:
    """Test ActivityPreview widget."""

    def test_activity_preview_initialization(self):
        """Test ActivityPreview initialization."""
        preview = ActivityPreview()
        assert preview.border_title == f"{Icons.PANEL_ACTIVITY} Recent Activity"

    def test_with_timestamp_prefix(self):
        """Messages without a timestamp should be prefixed once."""
        now = datetime.datetime(2026, 2, 24, 13, 45, 6)
        assert (
            _with_timestamp_prefix("Test message", now=now) == "[13:45:06] Test message"
        )
        assert (
            _with_timestamp_prefix("[13:45:06] Existing timestamp", now=now)
            == "[13:45:06] Existing timestamp"
        )
        assert (
            _with_timestamp_prefix("13:45:06 Existing timestamp", now=now)
            == "13:45:06 Existing timestamp"
        )

    def test_patterns_compiled(self):
        """Test that regex patterns are compiled."""
        preview = ActivityPreview()
        assert len(preview._compiled_patterns) > 0
        for pattern, _ in preview._compiled_patterns:
            assert hasattr(pattern, "finditer")

    def test_colorize_message_basic(self):
        """Test message colorization."""
        preview = ActivityPreview()
        text = preview._colorize_message("Test message", "info")
        assert text is not None

    def test_colorize_message_with_job_id(self):
        """Test colorization with job ID."""
        preview = ActivityPreview()
        message = "Found job #123456 with reward $50.00"
        text = preview._colorize_message(message, "info")
        assert text is not None

    def test_colorize_message_levels(self):
        """Test different log levels."""
        preview = ActivityPreview()
        for level in ["debug", "info", "warning", "error", "success", "job"]:
            text = preview._colorize_message("Test message", level)
            assert text is not None

    @pytest.mark.asyncio
    async def test_add_line_not_mounted(self):
        """Test add_line when widget not mounted."""
        preview = ActivityPreview()
        # Should not raise exception
        preview.add_line("Test message", "info")


class TestJobsPreview:
    """Test JobsPreview widget."""

    @pytest.mark.asyncio
    async def test_jobs_preview_initialization(self, mock_state):
        """Test JobsPreview initialization."""
        preview = JobsPreview(state=mock_state)
        assert preview.state == mock_state
        assert preview.border_title == f"{Icons.PANEL_JOBS} Jobs Preview"

    @pytest.mark.asyncio
    async def test_refresh_jobs_with_data(self, mock_state):
        """Test refresh_jobs with job data."""
        preview = JobsPreview(state=mock_state)
        # Should not raise exception even if not mounted
        preview.refresh_jobs()

    @pytest.mark.asyncio
    async def test_refresh_jobs_without_state(self):
        """Test refresh_jobs without state."""
        preview = JobsPreview(state=None)
        # Should not raise exception
        preview.refresh_jobs()


class TestHourlyActivity:
    """Test HourlyActivity widget."""

    def test_hourly_activity_initialization(self, mock_stats):
        """Test HourlyActivity initialization."""
        chart = HourlyActivity(stats=mock_stats)
        assert chart.stats == mock_stats
        assert chart.border_title == f"{Icons.PANEL_CHART} Jobs/Hour"

    @pytest.mark.asyncio
    async def test_hourly_activity_refresh(self, mock_stats):
        """Test HourlyActivity refresh with stats data."""
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield HourlyActivity(stats=mock_stats)

        app = TestApp()
        async with app.run_test() as pilot:
            chart = app.query_one(HourlyActivity)
            chart.refresh_hourly()
            await pilot.pause(0.1)

    @pytest.mark.asyncio
    async def test_hourly_activity_without_stats(self):
        """Test HourlyActivity without stats."""
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield HourlyActivity(stats=None)

        app = TestApp()
        async with app.run_test() as pilot:
            chart = app.query_one(HourlyActivity)
            chart.refresh_hourly()
            await pilot.pause(0.1)

    @pytest.mark.asyncio
    async def test_hourly_activity_falls_back_to_state_jobs(self):
        """If stats have no activity, Jobs/Hour should use persisted state jobs."""
        from textual.app import App
        from textual.widgets import Static

        now_ts = time.time()
        state = MagicMock()
        state.get_recent_jobs.return_value = [
            {"timestamp": now_ts - 2 * 3600},
            {"timestamp": now_ts - 2 * 3600 + 300},
            {"timestamp": now_ts - 1 * 3600},
        ]

        class TestApp(App):
            def compose(self):
                yield HourlyActivity(stats=None, state=state)

        app = TestApp()
        async with app.run_test() as pilot:
            chart = app.query_one(HourlyActivity)
            chart.refresh_hourly()
            await pilot.pause(0.1)
            content = chart.query_one("#hourly-content", Static)
            text = str(content.render())
            assert "Peak:" in text
            assert "Jobs: 2" in text
            assert "24h" in text
            assert "12h" in text
            assert "now" in text
            assert any(ch in text for ch in ("┌", "┐", "└", "┘", "┤", "┼", "█"))

    def test_hourly_activity_builds_rolling_hourly_buckets(self):
        """Rolling buckets should represent the most recent hours left->right."""
        now_ts = 1_700_000_000.0
        state = MagicMock()
        state.get_recent_jobs.return_value = [
            {"timestamp": now_ts - 60},  # current hour
            {"timestamp": now_ts - 2 * 3600},
            {"timestamp": now_ts - 2 * 3600 - 10},
            {"timestamp": now_ts - 26 * 3600},  # out of window
        ]

        chart = HourlyActivity(stats=None, state=state)
        with patch("gengowatcher.ui_textual.time.time", return_value=now_ts):
            buckets = chart._rolling_hourly_counts_from_state(window_hours=24)

        assert len(buckets) == 24
        assert buckets[-1] == 1.0
        assert buckets[-3] == 2.0
        assert sum(buckets) == 3.0

    @pytest.mark.asyncio
    async def test_hourly_activity_shows_chart_when_data_exists(self, mock_stats):
        """Jobs/Hour should render a chart (not just plain text) when data exists."""
        from textual.app import App
        from textual.widgets import Static

        class TestApp(App):
            def compose(self):
                yield HourlyActivity(stats=mock_stats)

        app = TestApp()
        async with app.run_test() as pilot:
            chart = app.query_one(HourlyActivity)
            chart.refresh_hourly()
            await pilot.pause(0.1)
            content = chart.query_one("#hourly-content", Static)
            text = str(content.render())
            assert "Peak:" in text
            assert "Jobs:" in text
            assert "00:00" in text
            assert "23:59" in text
            assert any(ch in text for ch in ("┌", "┐", "└", "┘", "┤", "┼", "█"))


class TestConfigPreview:
    """Test ConfigPreview widget."""

    def test_config_preview_initialization(self, mock_config):
        """Test ConfigPreview initialization."""
        preview = ConfigPreview(config=mock_config)
        assert preview.config == mock_config
        assert preview.border_title == f"{Icons.PANEL_CONFIG} Configuration"

    def test_sensitive_keys_defined(self):
        """Test that sensitive keys are defined."""
        assert len(ConfigPreview.SENSITIVE_KEYS) > 0
        assert "password" in ConfigPreview.SENSITIVE_KEYS
        assert "user_session" in ConfigPreview.SENSITIVE_KEYS

    def test_is_sensitive(self, mock_config):
        """Test sensitive key detection."""
        preview = ConfigPreview(config=mock_config)
        assert preview._is_sensitive("password")
        assert preview._is_sensitive("user_session")
        assert preview._is_sensitive("user_key")
        assert not preview._is_sensitive("check_interval")

    def test_mask_value(self, mock_config):
        """Test value masking."""
        preview = ConfigPreview(config=mock_config)
        masked = preview._mask_value("secret123456")
        assert "se" in masked
        assert "56" in masked
        assert "..." in masked

    def test_mask_value_short(self, mock_config):
        """Test masking short values."""
        preview = ConfigPreview(config=mock_config)
        masked = preview._mask_value("abc")
        assert masked == "****"

    def test_format_value_boolean(self, mock_config):
        """Test boolean formatting."""
        preview = ConfigPreview(config=mock_config)
        assert preview._format_value("test", True) == "✓"
        assert preview._format_value("test", False) == "✗"

    def test_format_value_list(self, mock_config):
        """Test list formatting."""
        preview = ConfigPreview(config=mock_config)
        formatted = preview._format_value("test", ["a", "b", "c"])
        assert "a" in formatted
        assert "b" in formatted
        assert "c" in formatted

    def test_format_value_float(self, mock_config):
        """Test float formatting."""
        preview = ConfigPreview(config=mock_config)
        assert "10.50" in preview._format_value("test", 10.50)
        assert "10" in preview._format_value("test", 10.00)

    def test_render_config(self, mock_config):
        """Test config rendering."""
        preview = ConfigPreview(config=mock_config)
        text = preview._render_config()
        assert text is not None


class TestSessionStatsWidget:
    """Test SessionStats widget."""

    @pytest.mark.asyncio
    async def test_session_stats_initialization(self, mock_watcher, mock_state):
        """Test SessionStats initialization."""
        stats = SessionStatsWidget(watcher=mock_watcher, state=mock_state)
        assert stats.watcher == mock_watcher
        assert stats.state == mock_state
        assert stats.border_title == f"{Icons.PANEL_SESSION} Session"

    @pytest.mark.asyncio
    async def test_refresh_stats_not_mounted(self, mock_watcher, mock_state):
        """Test refresh_stats when not mounted."""
        stats = SessionStatsWidget(watcher=mock_watcher, state=mock_state)
        # Should not raise exception
        stats.refresh_stats()


class TestStatsPanel:
    """Test StatsPanel widget."""

    def test_stats_panel_initialization(self, mock_stats):
        """Test StatsPanel initialization."""
        panel = StatsPanel(stats=mock_stats)
        assert panel.stats == mock_stats

    @pytest.mark.asyncio
    async def test_refresh_stats_not_mounted(self, mock_stats):
        """Test refresh_stats when not mounted."""
        panel = StatsPanel(stats=mock_stats)
        # Should not raise exception
        panel.refresh_stats()


class TestTextualLogHandler:
    """Test TextualLogHandler."""

    def test_log_handler_initialization(self):
        """Test log handler initialization."""
        app = MagicMock()
        handler = TextualLogHandler(app)
        assert handler.app == app

    def test_patterns_compiled(self):
        """Test that patterns are compiled."""
        app = MagicMock()
        handler = TextualLogHandler(app)
        assert len(handler._compiled_patterns) > 0

    def test_colorize_message(self):
        """Test message colorization."""
        app = MagicMock()
        handler = TextualLogHandler(app)
        import logging

        text = handler._colorize_message("Test message", logging.INFO)
        assert text is not None

    def test_colorize_with_patterns(self):
        """Test colorization with various patterns."""
        app = MagicMock()
        handler = TextualLogHandler(app)
        import logging

        message = "Found job #12345 with $50.00 reward JA→EN"
        text = handler._colorize_message(message, logging.INFO)
        assert text is not None

    def test_emit_exception_handling(self):
        """Test emit doesn't crash on exceptions."""
        app = MagicMock()
        app.call_from_thread.side_effect = Exception("Thread error")
        handler = TextualLogHandler(app)

        import logging

        record = logging.LogRecord(
            "test", logging.INFO, "test.py", 1, "Test message", (), None
        )
        # Should not raise exception
        handler.emit(record)

    def test_emit_collapses_traceback_for_ui_log(self):
        """UI log should keep exception signal without dumping full traceback."""
        app = MagicMock()
        handler = TextualLogHandler(app)

        try:
            raise TimeoutError("open timed out")
        except TimeoutError:
            import sys

            record = logging.LogRecord(
                "test",
                logging.ERROR,
                "test.py",
                1,
                "WebSocket: Unexpected error",
                (),
                sys.exc_info(),
            )

        handler.emit(record)

        _, args, _ = app.call_from_thread.mock_calls[0]
        assert args[1] == "WebSocket: Unexpected error | TimeoutError: open timed out"
        assert "\n" not in args[1]


class TestGengoWatcherApp:
    """Test main GengoWatcherApp."""

    @pytest.mark.asyncio
    async def test_app_initialization(
        self, mock_config, mock_state, mock_watcher, mock_stats
    ):
        """Test app initialization."""
        app = GengoWatcherApp(
            config=mock_config, state=mock_state, watcher=mock_watcher, stats=mock_stats
        )
        assert app.config == mock_config
        assert app.state == mock_state
        assert app.watcher == mock_watcher
        assert app.stats == mock_stats
        assert app.theme == "nord"

    @pytest.mark.asyncio
    async def test_app_initialization_uses_saved_theme(
        self, mock_config, mock_state, mock_watcher, mock_stats
    ):
        mock_config.get.side_effect = lambda section, key: {
            ("UI", "theme_name"): "gruvbox",
        }.get((section, key), "test_value")

        app = GengoWatcherApp(
            config=mock_config, state=mock_state, watcher=mock_watcher, stats=mock_stats
        )

        assert app.theme == "gruvbox"

    def test_watch_theme_persists_selection(
        self, mock_config, mock_state, mock_watcher, mock_stats
    ):
        app = GengoWatcherApp(
            config=mock_config, state=mock_state, watcher=mock_watcher, stats=mock_stats
        )

        app.watch_theme("gruvbox")

        mock_config.set.assert_called_with("UI", "theme_name", "gruvbox")
        mock_config.save_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_app_has_bindings(
        self, mock_config, mock_state, mock_watcher, mock_stats
    ):
        """Test that app has key bindings."""
        app = GengoWatcherApp(
            config=mock_config, state=mock_state, watcher=mock_watcher, stats=mock_stats
        )
        assert hasattr(app, "BINDINGS")
        assert len(app.BINDINGS) > 0

    def test_setup_logging_attaches_handler_to_watcher_logger(
        self, mock_config, mock_state, mock_watcher, mock_stats
    ):
        watcher_logger = logging.getLogger("test_ui_textual_comprehensive_app")
        watcher_logger.handlers = []
        watcher_logger.propagate = False
        mock_watcher.logger = watcher_logger

        app = GengoWatcherApp(
            config=mock_config, state=mock_state, watcher=mock_watcher, stats=mock_stats
        )

        try:
            app._setup_logging()
            assert app._textual_log_handler in watcher_logger.handlers
            assert app._logging_attached is True
        finally:
            app.on_unmount()

        assert app._textual_log_handler not in watcher_logger.handlers
        assert mock_watcher.on_job_added_callback is None

    def test_on_mount_replays_buffered_startup_logs(
        self, mock_config, mock_state, mock_watcher, mock_stats
    ):
        watcher_logger = logging.getLogger("test_ui_textual_comprehensive_replay")
        watcher_logger.handlers = []
        watcher_logger.propagate = False
        mock_watcher.logger = watcher_logger

        buffered_handler = UILoggingHandler()
        record = logging.LogRecord(
            "gengowatcher",
            logging.INFO,
            __file__,
            1,
            "WebSocket: Connection established and authenticated.",
            (),
            None,
        )
        buffered_handler.emit(record)

        app = GengoWatcherApp(
            config=mock_config,
            state=mock_state,
            watcher=mock_watcher,
            stats=mock_stats,
            ui_log_handler=buffered_handler,
        )
        app._setup_jobs_table = MagicMock()
        app._refresh_dashboard_panels = MagicMock()
        app.set_interval = MagicMock()
        app._textual_log_handler._write_to_log = MagicMock()

        try:
            app.on_mount()

            replay_calls = app._textual_log_handler._write_to_log.call_args_list
            assert replay_calls
            assert replay_calls[0].args[0] == "#activity-log"
            assert replay_calls[1].args[0] == "#activity-log-full"
            assert "WebSocket: Connection established and authenticated." in str(
                replay_calls[0].args[1]
            )
        finally:
            app.on_unmount()

    def test_refresh_dashboard_panels_dispatches_widget_refreshes(
        self, mock_config, mock_state, mock_watcher, mock_stats
    ):
        """Dashboard panel refresh helper should refresh all session-driven widgets."""
        app = GengoWatcherApp(
            config=mock_config, state=mock_state, watcher=mock_watcher, stats=mock_stats
        )
        app._refresh_widget = MagicMock()

        expected_targets = [
            (MetricsRow, "refresh_metrics"),
            (JobsPreview, "refresh_jobs"),
            (HourlyActivity, "refresh_hourly"),
            (TelemetryPanel, "refresh_telemetry"),
        ]

        assert app._dashboard_refresh_targets() == expected_targets

        app._refresh_dashboard_panels()

        assert app._refresh_widget.call_args_list == [
            call(*target, missing_level=logging.WARNING) for target in expected_targets
        ]

    def test_refresh_widget_warns_for_required_missing_widget(
        self, mock_config, mock_state, mock_watcher, mock_stats, caplog
    ):
        """Required dashboard widgets should not disappear quietly."""
        app = GengoWatcherApp(
            config=mock_config, state=mock_state, watcher=mock_watcher, stats=mock_stats
        )

        with patch.object(app, "query_one", side_effect=NoMatches):
            with caplog.at_level(logging.WARNING):
                app._refresh_widget(
                    MetricsRow,
                    "refresh_metrics",
                    missing_level=logging.WARNING,
                )

        assert (
            "Widget MetricsRow missing while refreshing refresh_metrics" in caplog.text
        )


class TestRegressionCases:
    """Test regression and edge cases."""

    def test_metric_card_with_empty_label(self):
        """Test MetricCard with empty label."""
        card = MetricCard("", "X", "0")
        assert card.label == ""

    def test_status_indicator_rapid_state_changes(self):
        """Test rapid state changes."""
        indicator = StatusIndicator("●", "WS", id="test")
        for _ in range(100):
            indicator.set_state("live")
            indicator.set_state("idle")
            indicator.set_state("working")
        # Should not crash

    @pytest.mark.asyncio
    async def test_metrics_row_with_negative_elapsed_time(self):
        """Test handling of edge case timing."""
        state = MagicMock()
        state.session_start = time.time() + 3600  # Future time
        state.get_recent_jobs.return_value = []
        row = MetricsRow(state=state)
        # Should handle gracefully
        row.refresh_metrics()

    def test_config_preview_with_very_long_value(self, mock_config):
        """Test formatting of very long config values."""
        preview = ConfigPreview(config=mock_config)
        long_value = "x" * 1000
        formatted = preview._format_value("test", long_value)
        # _format_value should preserve the full value; truncation is handled later.
        assert formatted == long_value

    def test_activity_preview_with_special_characters(self):
        """Test colorization with special regex characters."""
        preview = ActivityPreview()
        message = "Job found: $100.50 (special chars: []{}<>)"
        # Should not raise regex errors
        text = preview._colorize_message(message, "info")
        assert text is not None
