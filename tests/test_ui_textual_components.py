"""Tests for additional ui_textual.py components and features."""

import pytest
import time
import tempfile
import pathlib
from unittest.mock import MagicMock, patch
from datetime import datetime

from gengowatcher.ui_textual import (
    TitleBar,
    MetricCard,
    MetricsRow,
    StatusIndicator,
    StatusRow,
    TelemetryPanel,
    TelemetryTab,
    ActivityPreview,
    JobsPreview,
    HourlyActivity,
    ConfigPreview,
    SessionStats,
    StatsPanel,
    TextualLogHandler,
    Icons,
    _derive_display_word_count,
)


@pytest.fixture
def mock_config():
    """Create mock config for testing."""
    config = MagicMock()
    config.get.side_effect = lambda section, key, **kwargs: {
        ("Watcher", "source_lang"): "JA",
        ("Watcher", "target_lang"): "EN",
        ("Watcher", "check_interval"): 60,
        ("Watcher", "min_reward"): 5.0,
    }.get((section, key), kwargs.get("fallback", ""))
    config.config = {}
    config.list_all.return_value = {
        "Watcher": {"check_interval": 60, "min_reward": 5.0},
        "WebSocket": {"enable_websocket": True},
    }
    return config


@pytest.fixture
def mock_state():
    """Create mock state for testing."""
    state = MagicMock()
    state.session_start = time.time()
    state.total_new_entries_found = 10
    state.get_recent_jobs.return_value = []
    return state


@pytest.fixture
def mock_watcher():
    """Create mock watcher for testing."""
    watcher = MagicMock()
    watcher.start_time = time.time()
    watcher.websocket_status = "Live"
    watcher.websocket_connected = True
    watcher.email_monitor_status = "Polling"
    watcher.website_monitor_status = "Monitoring"
    watcher.rss_action = "Checking"
    watcher.captcha_enabled = False
    watcher.is_processing = False
    watcher.auto_accept_enabled = True
    watcher._email_monitor = MagicMock()
    watcher._website_monitor = MagicMock()
    return watcher


@pytest.fixture
def mock_stats():
    """Create mock stats for testing."""
    from gengowatcher.stats import StatsManager, SessionStats, AllTimeStats

    with tempfile.TemporaryDirectory() as tmpdir:
        stats_path = pathlib.Path(tmpdir) / "stats.json"
        stats = StatsManager(stats_path=stats_path)
        stats.session = SessionStats()
        stats.all_time = AllTimeStats()
        stats.hourly_counts = {0: 5, 1: 3, 8: 10, 12: 7}
        yield stats


class TestIcons:
    """Tests for icon constants."""

    def test_icons_are_defined(self):
        """Test that all icons are properly defined."""
        assert hasattr(Icons, "FOUND")
        assert hasattr(Icons, "ACCEPTED")
        assert hasattr(Icons, "VALUE")
        assert hasattr(Icons, "RATE")
        assert hasattr(Icons, "WEBSOCKET")
        assert hasattr(Icons, "EMAIL")
        assert hasattr(Icons, "WEB")
        assert hasattr(Icons, "RSS")
        assert hasattr(Icons, "CAPTCHA")
        assert hasattr(Icons, "WORKFLOW")
        assert hasattr(Icons, "AUTO")

    def test_icons_are_strings(self):
        """Test that icons are string values."""
        assert isinstance(Icons.FOUND, str)
        assert isinstance(Icons.WEBSOCKET, str)
        assert isinstance(Icons.LIVE, str)


class TestWordCountDerivation:
    """Tests for table word-count derivation helper."""

    def test_prefers_explicit_count_fields(self):
        assert _derive_display_word_count({"word_count": "320", "reward": 10.0}) == 320
        assert _derive_display_word_count({"unit_count": "480", "reward": 10.0}) == 480

    def test_estimates_from_reward_and_tier(self):
        assert _derive_display_word_count({"reward": 10.0, "tier": "standard"}) == 500
        assert _derive_display_word_count({"reward": 5.0, "tier": "pro"}) == 100

    def test_estimates_with_standard_default_when_tier_missing(self):
        assert _derive_display_word_count({"reward": 1.92}) == 96


class TestTitleBar:
    """Tests for TitleBar widget."""

    @pytest.mark.asyncio
    async def test_title_bar_initialization(self, mock_config):
        """Test TitleBar initializes with config."""
        title_bar = TitleBar(config=mock_config)
        assert title_bar.config == mock_config

    @pytest.mark.asyncio
    async def test_title_bar_clock_update(self, mock_config):
        """Test that clock updates periodically."""
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield TitleBar(config=mock_config)

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            # Clock should be mounted and updating
            title_bar = app.query_one(TitleBar)
            assert title_bar is not None


class TestMetricCard:
    """Tests for MetricCard widget."""

    @pytest.mark.asyncio
    async def test_metric_card_creation(self):
        """Test MetricCard can be created with label and icon."""
        card = MetricCard("Test", "★", value="42")
        assert card.label == "Test"
        assert card.icon == "★"
        assert card.value == "42"

    @pytest.mark.asyncio
    async def test_metric_card_update_value(self):
        """Test MetricCard value can be updated."""
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield MetricCard("Test", "★", id="test-card")

        app = TestApp()
        async with app.run_test() as pilot:
            card = app.query_one("#test-card", MetricCard)
            card.update_value("100")
            await pilot.pause(0.1)
            # Value should be updated


class TestMetricsRow:
    """Tests for MetricsRow widget."""

    @pytest.mark.asyncio
    async def test_metrics_row_displays_cards(self, mock_state):
        """Test MetricsRow displays all metric cards."""
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield MetricsRow(state=mock_state)

        app = TestApp()
        async with app.run_test() as pilot:
            metrics_row = app.query_one(MetricsRow)
            cards = metrics_row.query(MetricCard)
            assert len(cards) == 5  # Found, Accepted, Value, Rate, Today

    @pytest.mark.asyncio
    async def test_metrics_row_refresh(self, mock_state):
        """Test MetricsRow refresh updates values."""
        mock_state.get_recent_jobs.return_value = [
            {"reward": 10.0, "accepted": True},
            {"reward": 15.0, "accepted": False},
        ]

        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield MetricsRow(state=mock_state)

        app = TestApp()
        async with app.run_test() as pilot:
            metrics_row = app.query_one(MetricsRow)
            metrics_row.refresh_metrics()
            await pilot.pause(0.1)
            # Metrics should be updated based on jobs


class TestStatusIndicator:
    """Tests for StatusIndicator widget."""

    @pytest.mark.asyncio
    async def test_status_indicator_states(self):
        """Test StatusIndicator can switch between states."""
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield StatusIndicator("●", "Test", id="test-indicator")

        app = TestApp()
        async with app.run_test() as pilot:
            indicator = app.query_one("#test-indicator", StatusIndicator)

            # Test different states
            indicator.set_state("idle")
            await pilot.pause(0.1)
            assert indicator.current_state == "idle"

            indicator.set_state("live")
            await pilot.pause(0.1)
            assert indicator.current_state == "live"

            indicator.set_state("error")
            await pilot.pause(0.1)
            assert indicator.current_state == "error"

    @pytest.mark.asyncio
    async def test_status_indicator_pulse_animation(self):
        """Test StatusIndicator pulse animation for live state."""
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield StatusIndicator("●", "Test", id="test-indicator")

        app = TestApp()
        async with app.run_test() as pilot:
            indicator = app.query_one("#test-indicator", StatusIndicator)
            indicator.set_state("live")
            await pilot.pause(1.0)  # Wait for pulse animation
            # Pulse index should have changed


class TestStatusRow:
    """Tests for StatusRow widget."""

    @pytest.mark.asyncio
    async def test_status_row_displays_indicators(self, mock_watcher):
        """Test StatusRow displays all status indicators."""
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield StatusRow(watcher=mock_watcher)

        app = TestApp()
        async with app.run_test() as pilot:
            status_row = app.query_one(StatusRow)
            indicators = status_row.query(StatusIndicator)
            assert len(indicators) == 7  # WS, RSS, Mail, Web, Captcha, Workflow, Auto

    @pytest.mark.asyncio
    async def test_status_row_refresh_websocket_live(self, mock_watcher):
        """Test StatusRow refresh sets WebSocket to live when connected."""
        from textual.app import App

        mock_watcher.websocket_connected = True
        mock_watcher.websocket_status = "Live"

        class TestApp(App):
            def compose(self):
                yield StatusRow(watcher=mock_watcher)

        app = TestApp()
        async with app.run_test() as pilot:
            status_row = app.query_one(StatusRow)
            status_row.refresh_status()
            await pilot.pause(0.1)
            ws_indicator = app.query_one("#ind-ws", StatusIndicator)
            assert ws_indicator.current_state == "live"

    @pytest.mark.asyncio
    async def test_status_row_prefers_health_snapshot_states(self, mock_watcher):
        """Health snapshot should drive honest indicator states."""
        from textual.app import App

        mock_watcher.get_health_snapshot.return_value = {
            "websocket": {"state": "stale", "detail": "pong overdue"},
            "rss": {"state": "healthy", "detail": "last check 4s ago"},
            "auto": {"state": "disabled", "detail": "off"},
            "workflow": {"state": "error", "detail": "broken pipeline"},
        }

        class TestApp(App):
            def compose(self):
                yield StatusRow(watcher=mock_watcher)

        app = TestApp()
        async with app.run_test() as pilot:
            status_row = app.query_one(StatusRow)
            status_row.refresh_status()
            await pilot.pause(0.1)
            assert app.query_one("#ind-ws", StatusIndicator).current_state == "stale"
            assert app.query_one("#ind-rss", StatusIndicator).current_state == "live"
            assert (
                app.query_one("#ind-auto", StatusIndicator).current_state == "disabled"
            )
            assert app.query_one("#ind-work", StatusIndicator).current_state == "error"

    @pytest.mark.asyncio
    async def test_telemetry_panel_renders_health_snapshot(self, mock_watcher):
        """Telemetry panel should group enabled/disabled modules with details."""
        from textual.app import App
        from textual.widgets import Static

        mock_watcher.get_health_snapshot.return_value = {
            "websocket": {
                "state": "stale",
                "detail": "pong 52s",
                "last_pong_age_sec": 52,
                "last_message_age_sec": 4,
            },
            "rss": {
                "state": "healthy",
                "detail": "ok",
                "last_success_age_sec": 4,
                "failure_count": 0,
            },
            "session": {
                "state": "error",
                "detail": "sync failed",
                "last_sync_age_sec": 12,
            },
            "workflow": {
                "state": "disabled",
                "detail": "manual",
                "processing": False,
            },
            "email": {
                "state": "disabled",
                "detail": "off",
            },
            "browser": {
                "state": "healthy",
                "detail": "ready",
                "last_check_age_sec": 6,
            },
        }

        class TestApp(App):
            def compose(self):
                yield TelemetryPanel(watcher=mock_watcher)

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one(TelemetryPanel)
            panel.refresh_telemetry()
            await pilot.pause(0.1)
            content = panel.query_one("#telemetry-content", Static)
            rendered = str(content.render())
            rich_text = content.render()
            assert "Enabled" in rendered
            assert "Disabled" in rendered
            assert "WS" in rendered
            assert "Browser" in rendered
            assert "Email" in rendered
            assert "RSS" in rendered
            assert "Session" in rendered
            assert "sync failed" in rendered
            assert "52s" in rendered
            assert "4s" in rendered
            assert getattr(rich_text, "spans", [])

    @pytest.mark.asyncio
    async def test_telemetry_tab_renders_detailed_sections(self, mock_watcher):
        """Telemetry tab should render enabled/disabled sections and details."""
        from textual.app import App
        from textual.widgets import Static

        mock_watcher.get_health_snapshot.return_value = {
            "websocket": {
                "state": "stale",
                "detail": "pong 52s",
                "status": "Live",
                "last_pong_age_sec": 52,
                "last_message_age_sec": 4,
                "ping_latency_ms": 91,
            },
            "rss": {
                "state": "healthy",
                "detail": "ok",
                "status": "Waiting",
                "last_success_age_sec": 4,
                "failure_count": 0,
            },
            "email": {
                "state": "disabled",
                "detail": "off",
            },
            "browser": {
                "state": "healthy",
                "detail": "ready",
                "last_check_age_sec": 6,
            },
        }

        class TestApp(App):
            def compose(self):
                yield TelemetryTab(watcher=mock_watcher)

        app = TestApp()
        async with app.run_test() as pilot:
            tab = app.query_one(TelemetryTab)
            tab.refresh_telemetry()
            await pilot.pause(0.1)
            content = tab.query_one("#telemetry-tab-content", Static)
            rendered = str(content.render())
            assert "ENABLED MODULES" in rendered
            assert "DISABLED MODULES" in rendered
            assert "WEBSOCKET" in rendered
            assert "BROWSER" in rendered
            assert "EMAIL" in rendered
            assert "last_pong_age_sec" in rendered
            assert "ping_latency_ms" in rendered
            assert "RSS" in rendered

    @pytest.mark.asyncio
    async def test_telemetry_panel_pulse_tick_animates_status_icons(self, mock_watcher):
        """Telemetry panel should re-render animated icons as the pulse timer advances."""
        from textual.app import App
        from textual.widgets import Static

        mock_watcher.get_health_snapshot.return_value = {
            "websocket": {
                "state": "stale",
                "detail": "pong 52s",
                "last_pong_age_sec": 52,
            },
            "rss": {
                "state": "working",
                "detail": "processing",
                "last_success_age_sec": 4,
            },
        }

        class TestApp(App):
            def compose(self):
                yield TelemetryPanel(watcher=mock_watcher)

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one(TelemetryPanel)
            panel.refresh_telemetry()
            await pilot.pause(0.1)
            content = panel.query_one("#telemetry-content", Static)
            first_render = str(content.render())

            panel._pulse_tick()
            panel._pulse_tick()
            await pilot.pause(0.1)
            second_render = str(content.render())

            assert first_render != second_render

    def test_status_indicator_uses_distinct_pulse_cadence_by_state(self):
        """Critical states should pulse faster than non-critical ones."""
        indicator = StatusIndicator("x", "Test")

        assert indicator._pulse_step_for_state(
            "live"
        ) > indicator._pulse_step_for_state("working")
        assert indicator._pulse_step_for_state(
            "working"
        ) > indicator._pulse_step_for_state("stale")
        assert indicator._pulse_step_for_state(
            "stale"
        ) >= indicator._pulse_step_for_state("error")

    @pytest.mark.asyncio
    async def test_status_row_refresh_email_polling(self, mock_watcher):
        """Test StatusRow refresh sets Email to live when polling."""
        from textual.app import App

        mock_watcher.email_monitor_status = "Polling"
        mock_watcher._email_monitor = MagicMock()

        class TestApp(App):
            def compose(self):
                yield StatusRow(watcher=mock_watcher)

        app = TestApp()
        async with app.run_test() as pilot:
            status_row = app.query_one(StatusRow)
            status_row.refresh_status()
            await pilot.pause(0.1)
            email_indicator = app.query_one("#ind-email", StatusIndicator)
            assert email_indicator.current_state == "live"


class TestActivityPreview:
    """Tests for ActivityPreview widget."""

    @pytest.mark.asyncio
    async def test_activity_preview_add_line(self):
        """Test ActivityPreview can add colored log lines."""
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield ActivityPreview()

        app = TestApp()
        async with app.run_test() as pilot:
            preview = app.query_one(ActivityPreview)
            preview.add_line("Test message", level="info")
            await pilot.pause(0.1)
            # Message should be added to log

    @pytest.mark.asyncio
    async def test_activity_preview_colorization(self):
        """Test ActivityPreview colorizes different message types."""
        from textual.app import App
        from rich.text import Text

        class TestApp(App):
            def compose(self):
                yield ActivityPreview()

        app = TestApp()
        async with app.run_test() as pilot:
            preview = app.query_one(ActivityPreview)

            # Test colorization of different message types
            colored = preview._colorize_message("Job #12345 found $25.50", "job")
            assert isinstance(colored, Text)

            colored = preview._colorize_message("Error: Failed to connect", "error")
            assert isinstance(colored, Text)

            colored = preview._colorize_message("Success: Job accepted", "success")
            assert isinstance(colored, Text)


class TestJobsPreview:
    """Tests for JobsPreview widget."""

    @pytest.mark.asyncio
    async def test_jobs_preview_refresh(self, mock_state):
        """Test JobsPreview refresh updates job table."""
        mock_state.get_recent_jobs.return_value = [
            {"id": "123", "lang_pair": "JA→EN", "word_count": 100, "reward": 10.0},
            {"id": "456", "lang_pair": "EN→JA", "words": 200, "reward": 20.0},
        ]

        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield JobsPreview(state=mock_state)

        app = TestApp()
        async with app.run_test() as pilot:
            preview = app.query_one(JobsPreview)
            preview.refresh_jobs()
            await pilot.pause(0.1)
            # Jobs should be displayed in table


class TestHourlyActivity:
    """Tests for HourlyActivity widget."""

    @pytest.mark.asyncio
    async def test_hourly_activity_renders(self, mock_stats):
        """Test HourlyActivity renders hourly data."""
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield HourlyActivity(stats=mock_stats)

        app = TestApp()
        async with app.run_test() as pilot:
            chart = app.query_one(HourlyActivity)
            chart.refresh_hourly()
            await pilot.pause(0.1)
            # Chart should be rendered

    @pytest.mark.asyncio
    async def test_hourly_activity_with_no_data(self):
        """Test HourlyActivity handles empty stats."""
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield HourlyActivity(stats=None)

        app = TestApp()
        async with app.run_test() as pilot:
            chart = app.query_one(HourlyActivity)
            chart.refresh_hourly()
            await pilot.pause(0.1)
            # Should handle None stats gracefully


class TestConfigPreview:
    """Tests for ConfigPreview widget."""

    @pytest.mark.asyncio
    async def test_config_preview_displays_config(self, mock_config):
        """Test ConfigPreview displays configuration."""
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield ConfigPreview(config=mock_config)

        app = TestApp()
        async with app.run_test() as pilot:
            preview = app.query_one(ConfigPreview)
            preview.refresh_config()
            await pilot.pause(0.1)
            # Config should be displayed

    def test_config_preview_masks_sensitive_data(self, mock_config):
        """Test masking behaviour for sensitive values."""
        preview = ConfigPreview(config=mock_config)
        masked = preview._mask_value("supersecrettoken123")
        assert "su" in masked
        assert "23" in masked
        assert len(masked) < len("supersecrettoken123")

    def test_config_preview_format_values(self, mock_config):
        """Test ConfigPreview formats different value types correctly."""
        preview = ConfigPreview(config=mock_config)

        assert preview._format_value("test", True) == "✓"
        assert preview._format_value("test", False) == "✗"
        assert preview._format_value("test", [1, 2, 3]) == "1, 2, 3"
        assert preview._format_value("test", 3.14) == "3.14"
        assert preview._format_value("test", 5) == "5"


class TestSessionStats:
    """Tests for SessionStats widget."""

    @pytest.mark.asyncio
    async def test_session_stats_refresh(self, mock_watcher, mock_state):
        """Test SessionStats refresh updates statistics."""
        mock_state.get_recent_jobs.return_value = [
            {"reward": 10.0, "accepted": True},
            {"reward": 15.0, "accepted": False},
        ]

        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield SessionStats(watcher=mock_watcher, state=mock_state)

        app = TestApp()
        async with app.run_test() as pilot:
            stats = app.query_one(SessionStats)
            stats.refresh_stats()
            await pilot.pause(0.1)
            # Stats should be updated


class TestStatsPanel:
    """Tests for StatsPanel widget."""

    @pytest.mark.asyncio
    async def test_stats_panel_refresh(self, mock_stats):
        """Test StatsPanel refresh updates display."""
        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield StatsPanel(stats=mock_stats)

        app = TestApp()
        async with app.run_test() as pilot:
            panel = app.query_one(StatsPanel)
            panel.refresh_stats()
            await pilot.pause(0.1)
            # Stats should be refreshed


class TestTextualLogHandler:
    """Tests for TextualLogHandler."""

    def test_log_handler_colorization(self):
        """Test TextualLogHandler colorizes messages correctly."""
        app = MagicMock()
        handler = TextualLogHandler(app)

        # Test different log levels
        colored = handler._colorize_message("Test message", level=20)  # INFO
        assert colored is not None

        colored = handler._colorize_message("Error message", level=40)  # ERROR
        assert colored is not None

    def test_log_handler_pattern_matching(self):
        """Test TextualLogHandler pattern matching."""
        app = MagicMock()
        handler = TextualLogHandler(app)

        # Test with job ID pattern
        colored = handler._colorize_message("Job #12345 found", level=20)
        text_str = str(colored)
        assert "12345" in text_str

        # Test with money pattern
        colored = handler._colorize_message("Reward: $25.50", level=20)
        text_str = str(colored)
        assert "25.50" in text_str


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_metric_card_with_empty_value(self):
        """Test MetricCard handles empty/zero values."""
        card = MetricCard("Test", "★", value="")
        assert card.value == ""

    def test_activity_preview_with_special_characters(self):
        """Test ActivityPreview handles special characters."""
        from textual.app import App

        preview = ActivityPreview()
        colored = preview._colorize_message("Test 日本語 UTF-8 ♠♥♦♣", "info")
        assert colored is not None

    @pytest.mark.asyncio
    async def test_status_row_with_missing_monitors(self):
        """Test StatusRow handles missing monitor attributes."""
        from textual.app import App

        watcher = MagicMock()
        watcher.websocket_status = ""
        watcher.email_monitor_status = ""
        watcher._email_monitor = None
        watcher._website_monitor = None

        class TestApp(App):
            def compose(self):
                yield StatusRow(watcher=watcher)

        app = TestApp()
        async with app.run_test() as pilot:
            status_row = app.query_one(StatusRow)
            status_row.refresh_status()  # Should not crash
            await pilot.pause(0.1)

    def test_config_preview_with_empty_config(self):
        """Test ConfigPreview handles empty configuration."""
        mock_config = MagicMock()
        mock_config.list_all.return_value = {}

        preview = ConfigPreview(config=mock_config)
        rendered = preview._render_config()
        assert rendered is not None

    @pytest.mark.asyncio
    async def test_jobs_preview_with_malformed_data(self, mock_state):
        """Test JobsPreview handles malformed job data."""
        mock_state.get_recent_jobs.return_value = [
            {},  # Empty dict
            {"id": "123"},  # Missing fields
            {"id": None, "lang_pair": None},  # None values
        ]

        from textual.app import App

        class TestApp(App):
            def compose(self):
                yield JobsPreview(state=mock_state)

        app = TestApp()
        async with app.run_test() as pilot:
            preview = app.query_one(JobsPreview)
            preview.refresh_jobs()  # Should not crash
            await pilot.pause(0.1)
