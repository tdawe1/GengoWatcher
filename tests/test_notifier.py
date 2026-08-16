from unittest.mock import patch

import subprocess

from gengowatcher.notifier import send_notification


def test_send_notification_includes_stderr_on_failure(caplog):
    error = subprocess.CalledProcessError(
        1, ["notify-send"], stderr="backend unavailable"
    )
    with patch("gengowatcher.notifier.subprocess.run", side_effect=error):
        send_notification("Title", "Body")
    assert "backend unavailable" in caplog.text


def test_send_notification_reports_oserror_separately_from_missing_binary(caplog):
    with patch(
        "gengowatcher.notifier.subprocess.run",
        side_effect=OSError("permission denied"),
    ):
        send_notification("Title", "Body")
    assert "operating system error" in caplog.text
    assert "command not found" not in caplog.text
