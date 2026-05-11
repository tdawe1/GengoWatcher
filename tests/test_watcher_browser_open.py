from unittest.mock import MagicMock, patch

from gengowatcher.watcher import GengoWatcher


def test_open_in_browser_uses_managed_firefox_for_gengo_url(
    mock_config,
    mock_state,
    mock_logger,
    monkeypatch,
):
    """Gengo links should stay inside the managed Firefox debug profile."""
    config_values = {
        ("WebSocket", "browser_debug_url"): "ws://127.0.0.1:9222",
        ("WebSocket", "browser_debug_auto_launch"): True,
        ("WebSocket", "browser_debug_profile_path"): "profiles/firefox-debug",
        ("WebSocket", "browser_debug_seed_profile_path"): "",
        (
            "WebSocket",
            "browser_debug_start_url",
        ): "https://gengo.com/t/jobs/status/available/realtime",
        ("Paths", "browser_debug_browser_path"): "firefox",
        ("Paths", "browser_path"): "/usr/bin/firefox",
        ("Paths", "browser_args"): "--new-window {url}",
    }
    mock_config.get.side_effect = (
        lambda section, key, fallback=None, **kwargs: config_values.get(
            (section, key), fallback
        )
    )
    mock_config.getboolean.side_effect = (
        lambda section, key, fallback=None, **kwargs: bool(
            config_values.get((section, key), fallback)
        )
    )

    watcher = GengoWatcher(config=mock_config, state=mock_state, logger=mock_logger)
    mock_webbrowser_open = MagicMock()
    monkeypatch.setattr("gengowatcher.watcher.webbrowser.open", mock_webbrowser_open)

    with patch(
        "gengowatcher.watcher.open_url_in_browser_debug_sync",
        return_value="https://gengo.com/t/jobs/details/123",
    ) as mock_debug_open:
        watcher.open_in_browser("https://gengo.com/t/jobs/details/123")

    mock_debug_open.assert_called_once_with(
        "ws://127.0.0.1:9222",
        "https://gengo.com/t/jobs/details/123",
    )
    mock_webbrowser_open.assert_not_called()
