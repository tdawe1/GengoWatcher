from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .._async_utils import run_coroutine_sync
from .protocol import (
    build_job_url_command,
    decode_message,
    encode_message,
    normalize_sandbox_origin,
)


class BrowserWorkerClient:
    def __init__(
        self,
        socket_path: str | Path,
        *,
        logger: logging.Logger | None = None,
        response_timeout: float = 5.0,
        auth_token: str = "",
        sandbox_origin: str = "",
    ):
        self.socket_path = Path(socket_path)
        self.logger = logger or logging.getLogger(__name__)
        self.response_timeout = response_timeout
        self.auth_token = str(auth_token or "")
        self.sandbox_origin = normalize_sandbox_origin(sandbox_origin)

    def build_job_url_command(
        self,
        url: str,
        source: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return build_job_url_command(
            url,
            source,
            metadata=metadata,
            auth_token=self.auth_token,
            allowed_origins=(self.sandbox_origin,) if self.sandbox_origin else (),
        )

    async def send_command(
        self,
        payload: dict[str, Any],
        *,
        response_timeout: float | None = None,
    ) -> dict[str, Any]:
        reader, writer = await asyncio.open_unix_connection(str(self.socket_path))
        try:
            writer.write(encode_message(payload))
            await writer.drain()
            effective_timeout = (
                float(response_timeout)
                if response_timeout is not None
                else self.response_timeout
            )
            try:
                response = await asyncio.wait_for(
                    reader.readline(),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError as exc:
                raise RuntimeError(
                    f"browser worker timed out after {effective_timeout:.1f}s"
                ) from exc
        finally:
            writer.close()
            await writer.wait_closed()

        if not response:
            raise RuntimeError("browser worker closed connection without a response")

        return decode_message(response)

    def _prepare_acceptance_payload(
        self,
        payload: dict[str, Any],
        *,
        track_acceptance: bool,
        acceptance_timeout_sec: float,
    ) -> float | None:
        """Set acceptance tracking fields and return adjusted timeout."""
        if track_acceptance and acceptance_timeout_sec > 0:
            payload["track_acceptance"] = True
            payload["acceptance_timeout_ms"] = int(acceptance_timeout_sec * 1000)
            return max(self.response_timeout, acceptance_timeout_sec + 5.0)
        return None

    async def submit_job_async(
        self,
        url: str,
        source: str,
        *,
        metadata: dict[str, Any] | None = None,
        track_acceptance: bool = False,
        acceptance_timeout_sec: float = 0.0,
    ) -> dict[str, Any]:
        payload = self.build_job_url_command(url, source, metadata=metadata)
        response_timeout = self._prepare_acceptance_payload(
            payload,
            track_acceptance=track_acceptance,
            acceptance_timeout_sec=acceptance_timeout_sec,
        )
        if response_timeout is None:
            return await self.send_command(payload)
        return await self.send_command(payload, response_timeout=response_timeout)

    def submit_job(
        self,
        url: str,
        source: str,
        *,
        metadata: dict[str, Any] | None = None,
        track_acceptance: bool = False,
        acceptance_timeout_sec: float = 0.0,
    ) -> dict[str, Any]:
        payload = self.build_job_url_command(url, source, metadata=metadata)
        response_timeout = self._prepare_acceptance_payload(
            payload,
            track_acceptance=track_acceptance,
            acceptance_timeout_sec=acceptance_timeout_sec,
        )
        if response_timeout is None:
            return run_coroutine_sync(self.send_command, payload)
        return run_coroutine_sync(
            self.send_command,
            payload,
            response_timeout=response_timeout,
            _result_timeout_sec=response_timeout + 1.0,
        )
