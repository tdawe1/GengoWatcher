from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

from .protocol import build_job_url_command, decode_message, encode_message


class BrowserWorkerClient:
    def __init__(
        self,
        socket_path: str | Path,
        *,
        logger: logging.Logger | None = None,
        response_timeout: float = 5.0,
    ):
        self.socket_path = Path(socket_path)
        self.logger = logger or logging.getLogger(__name__)
        self.response_timeout = response_timeout

    def build_job_url_command(
        self,
        url: str,
        source: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return build_job_url_command(url, source, metadata=metadata)

    async def send_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        reader, writer = await asyncio.open_unix_connection(str(self.socket_path))
        try:
            writer.write(encode_message(payload))
            await writer.drain()
            response = await reader.readline()
        finally:
            writer.close()
            await writer.wait_closed()

        if not response:
            raise RuntimeError("browser worker closed connection without a response")

        return decode_message(response)

    async def submit_job_async(
        self,
        url: str,
        source: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self.build_job_url_command(url, source, metadata=metadata)
        return await self.send_command(payload)

    def submit_job(
        self,
        url: str,
        source: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self.build_job_url_command(url, source, metadata=metadata)
        return asyncio.run(self.send_command(payload))
