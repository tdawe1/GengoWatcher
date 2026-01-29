"""Tests for Dashboard Quadrant widgets."""

import pytest
from unittest.mock import MagicMock
from textual.app import App, ComposeResult

from gengowatcher.ui_textual import ActivityPreview, JobsPreview, ConfigPreview


class ActivityPreviewTestApp(App):
    def compose(self) -> ComposeResult:
        yield ActivityPreview()


class JobsPreviewTestApp(App):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        yield JobsPreview(self._state)


class ConfigPreviewTestApp(App):
    def __init__(self, config):
        super().__init__()
        self._config = config

    def compose(self) -> ComposeResult:
        yield ConfigPreview(self._config)


@pytest.mark.asyncio
async def test_activity_preview_has_log():
    """ActivityPreview should have a RichLog widget."""
    app = ActivityPreviewTestApp()
    async with app.run_test() as pilot:
        preview = app.query_one(ActivityPreview)
        # Updated: ActivityPreview uses RichLog with id="activity-log"
        log_widget = preview.query_one("#activity-log")
        assert log_widget is not None


@pytest.mark.asyncio
async def test_jobs_preview_displays_jobs():
    """JobsPreview should display recent jobs via refresh_jobs()."""
    state = MagicMock()
    state.get_recent_jobs.return_value = [
        {"id": "123456", "lang_pair": "JA→EN", "reward": 12.50, "word_count": 500},
        {"id": "123457", "lang_pair": "EN→JA", "reward": 8.00, "word_count": 300},
    ]

    app = JobsPreviewTestApp(state)
    async with app.run_test() as pilot:
        preview = app.query_one(JobsPreview)
        preview.refresh_jobs()
        await pilot.pause()
        # Updated: JobsPreview uses DataTable with id="jobs-table"
        table = preview.query_one("#jobs-table")
        assert table is not None
        # Check that the table has rows
        assert table.row_count == 2


def test_config_preview_constants():
    """ConfigPreview should have all required class constants defined."""
    # Test that constants exist
    assert hasattr(ConfigPreview, "SECTION_ORDER")
    assert hasattr(ConfigPreview, "SECTION_HEADER_WIDTH")
    assert hasattr(ConfigPreview, "MAX_VALUE_LENGTH")
    assert hasattr(ConfigPreview, "MAX_VALUE_LENGTH_SHORT")

    # Test constant types
    assert isinstance(ConfigPreview.SECTION_ORDER, list)
    assert isinstance(ConfigPreview.SECTION_HEADER_WIDTH, int)
    assert isinstance(ConfigPreview.MAX_VALUE_LENGTH, int)
    assert isinstance(ConfigPreview.MAX_VALUE_LENGTH_SHORT, int)

    # Test constant values
    assert ConfigPreview.SECTION_HEADER_WIDTH == 18
    assert ConfigPreview.MAX_VALUE_LENGTH == 20
    assert ConfigPreview.MAX_VALUE_LENGTH_SHORT == 17

    # Test SECTION_ORDER contains expected sections
    assert "Watcher" in ConfigPreview.SECTION_ORDER
    assert "WebSocket" in ConfigPreview.SECTION_ORDER
    assert "AutoAccept" in ConfigPreview.SECTION_ORDER
    assert len(ConfigPreview.SECTION_ORDER) == 13


@pytest.mark.asyncio
async def test_config_preview_render_uses_constants():
    """ConfigPreview._render_config should use class constants properly."""
    # Create a mock config
    config = MagicMock()
    config.list_all.return_value = {
        "Watcher": {
            "check_interval": 30,
            "enabled": True,
            "very_long_value_that_should_be_truncated": "x" * 30,
        },
        "WebSocket": {
            "enabled": False,
        },
    }

    app = ConfigPreviewTestApp(config)
    async with app.run_test():
        preview = app.query_one(ConfigPreview)
        result = preview._render_config()

        # Check that the result is a Text object
        assert result is not None
        result_str = result.plain

        # Check that sections appear in the order defined by SECTION_ORDER
        # Watcher should appear before WebSocket
        watcher_pos = result_str.find("Watcher")
        websocket_pos = result_str.find("WebSocket")
        assert watcher_pos >= 0
        assert websocket_pos >= 0
        assert watcher_pos < websocket_pos

        # Check that long values are truncated to MAX_VALUE_LENGTH_SHORT + "..."
        # The 30-character value should be truncated
        assert "..." in result_str
        # Verify the full 30-character value is not present
        assert "x" * 30 not in result_str
# =============================================================================
# ConfigPreview Tests
# =============================================================================


def create_mock_config(config_dict):
    """Create a mock AppConfig with the given config dictionary."""
    mock = MagicMock()
    mock.list_all.return_value = config_dict
    return mock


@pytest.mark.asyncio
async def test_config_preview_renders_sections():
    """ConfigPreview should render config sections."""
    config = create_mock_config(
        {
            "Watcher": {"check_interval": 30, "min_reward": 0.0},
            "WebSocket": {"enable_websocket": True},
        }
    )

    app = ConfigPreviewTestApp(config)
    async with app.run_test() as pilot:
        preview = app.query_one(ConfigPreview)
        content = preview.query_one("#config-content")
        assert content is not None


@pytest.mark.asyncio
async def test_config_preview_masks_sensitive_keys():
    """ConfigPreview should mask sensitive values like tokens and secrets."""
    config = create_mock_config(
        {
            "WebSocket": {
                "user_session": "abc123xyz789secret",
                "user_key": "my_secret_key_12345",
            },
        }
    )

    app = ConfigPreviewTestApp(config)
    async with app.run_test() as pilot:
        preview = app.query_one(ConfigPreview)

        # Test the masking function directly
        assert preview._is_sensitive("user_session") is True
        assert preview._is_sensitive("user_key") is True
        assert preview._is_sensitive("access_token") is True
        assert preview._is_sensitive("client_secret") is True
        assert preview._is_sensitive("check_interval") is False

        # Test mask output
        masked = preview._mask_value("abc123xyz789secret")
        assert masked == "ab...et"
        assert "abc123xyz789secret" not in masked


@pytest.mark.asyncio
async def test_config_preview_formats_booleans():
    """ConfigPreview should format booleans as ✓ or ✗."""
    config = create_mock_config(
        {
            "Watcher": {"enable_notifications": True, "use_custom_user_agent": False},
        }
    )

    app = ConfigPreviewTestApp(config)
    async with app.run_test() as pilot:
        preview = app.query_one(ConfigPreview)

        assert preview._format_value("enable_notifications", True) == "✓"
        assert preview._format_value("use_custom_user_agent", False) == "✗"


@pytest.mark.asyncio
async def test_config_preview_formats_numbers():
    """ConfigPreview should format numbers appropriately."""
    config = create_mock_config(
        {
            "Watcher": {"check_interval": 30, "min_reward": 5.50},
        }
    )

    app = ConfigPreviewTestApp(config)
    async with app.run_test() as pilot:
        preview = app.query_one(ConfigPreview)

        # Integer-like floats should display as integers
        assert preview._format_value("check_interval", 30.0) == "30"
        # Floats with decimals should show 2 decimal places
        assert preview._format_value("min_reward", 5.50) == "5.50"


@pytest.mark.asyncio
async def test_config_preview_formats_lists():
    """ConfigPreview should format lists as comma-separated values."""
    config = create_mock_config(
        {
            "WebServer": {
                "cors_origins": ["http://localhost:5173", "http://127.0.0.1:5173"]
            },
        }
    )

    app = ConfigPreviewTestApp(config)
    async with app.run_test() as pilot:
        preview = app.query_one(ConfigPreview)

        formatted = preview._format_value("cors_origins", ["a", "b", "c"])
        assert formatted == "a, b, c"


@pytest.mark.asyncio
async def test_config_preview_truncates_long_values():
    """ConfigPreview should truncate values longer than 20 characters."""
    config = create_mock_config(
        {
            "Paths": {"feed_url": "https://example.com/very/long/path/to/resource"},
        }
    )

    app = ConfigPreviewTestApp(config)
    async with app.run_test() as pilot:
        preview = app.query_one(ConfigPreview)
        text = preview._render_config()
        plain_text = text.plain

        # The full URL should not appear (it's > 20 chars)
        assert "https://example.com/very/long/path/to/resource" not in plain_text
        # But truncated version with ... should appear
        assert "..." in plain_text


@pytest.mark.asyncio
async def test_config_preview_handles_empty_values():
    """ConfigPreview should handle empty/None values gracefully."""
    config = create_mock_config(
        {
            "Paths": {"browser_path": "", "notification_icon_path": None},
        }
    )

    app = ConfigPreviewTestApp(config)
    async with app.run_test() as pilot:
        preview = app.query_one(ConfigPreview)

        assert preview._format_value("browser_path", "") == "—"
        assert preview._format_value("notification_icon_path", None) == "—"


@pytest.mark.asyncio
async def test_config_preview_refresh_updates_content():
    """ConfigPreview.refresh_config should update the Static widget content."""
    config = create_mock_config(
        {
            "Watcher": {"check_interval": 30},
        }
    )

    app = ConfigPreviewTestApp(config)
    async with app.run_test() as pilot:
        preview = app.query_one(ConfigPreview)

        # Update config mock
        config.list_all.return_value = {
            "Watcher": {"check_interval": 60},
        }

        preview.refresh_config()
        await pilot.pause()

        # Query the Static widget to verify it was actually updated
        content = preview.query_one("#config-content")
        assert "60" in content.content.plain


@pytest.mark.asyncio
async def test_config_preview_section_ordering():
    """ConfigPreview should display sections in the defined order."""
    config = create_mock_config(
        {
            "Logging": {"log_main_enabled": True},
            "Watcher": {"check_interval": 30},
            "WebSocket": {"enable_websocket": True},
        }
    )

    app = ConfigPreviewTestApp(config)
    async with app.run_test() as pilot:
        preview = app.query_one(ConfigPreview)
        text = preview._render_config()
        plain_text = text.plain

        # Watcher should appear before WebSocket, which should appear before Logging
        watcher_pos = plain_text.find("Watcher")
        websocket_pos = plain_text.find("WebSocket")
        logging_pos = plain_text.find("Logging")

        assert watcher_pos < websocket_pos < logging_pos
