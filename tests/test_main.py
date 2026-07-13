from pathlib import Path
from unittest.mock import MagicMock, patch

from gengowatcher.main import PROJECT_ROOT, _start_metrics_server_if_enabled


def test_project_root_contains_pyproject():
    assert PROJECT_ROOT == Path(__file__).resolve().parents[1]
    assert (PROJECT_ROOT / "pyproject.toml").is_file()


def test_metrics_server_stays_disabled_by_default():
    config = MagicMock()
    config.getboolean.return_value = False

    assert _start_metrics_server_if_enabled(config, MagicMock(), MagicMock()) is None


def test_metrics_server_uses_configured_address():
    config = MagicMock()
    config.getboolean.return_value = True
    config.get.side_effect = lambda section, key, fallback=None: {
        ("Metrics", "host"): "0.0.0.0",
    }.get((section, key), fallback)
    config.getint.return_value = 9191
    watcher = MagicMock()
    logger = MagicMock()

    with patch(
        "gengowatcher.main.start_watcher_metrics_server", return_value="server"
    ) as start:
        result = _start_metrics_server_if_enabled(config, watcher, logger)

    assert result == "server"
    start.assert_called_once_with(
        host="0.0.0.0",
        port=9191,
        watcher=watcher,
        logger=logger,
    )
