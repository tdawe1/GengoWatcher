from argparse import Namespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gengowatcher.browser_worker.main import _run_forever, main


@pytest.mark.asyncio
async def test_run_forever_serves_until_stopped():
    runtime = MagicMock()
    runtime.config.profile_path = "profiles/browser-worker"
    runtime.serve_forever = AsyncMock()
    runtime.stop = AsyncMock()
    args = Namespace(
        profile_path="profiles/browser-worker",
        seed_profile_path="",
        socket_path="/tmp/gengowatcher.sock",
        headless=False,
    )

    with patch(
        "gengowatcher.browser_worker.main.run_worker",
        AsyncMock(return_value=runtime),
    ):
        await _run_forever(args)

    runtime.serve_forever.assert_awaited_once()
    runtime.stop.assert_awaited_once()


def test_main_handles_keyboard_interrupt():
    with patch(
        "gengowatcher.browser_worker.main.asyncio.run",
        side_effect=KeyboardInterrupt,
    ):
        assert (
            main(
                [
                    "--profile-path",
                    "profiles/browser-worker",
                    "--socket-path",
                    "/tmp/gengowatcher.sock",
                ]
            )
            == 0
        )
