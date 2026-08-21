from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .runtime import BrowserRuntime, BrowserRuntimeConfig
from .telemetry import BrowserWorkerTelemetry


def build_runtime_config(args: argparse.Namespace) -> BrowserRuntimeConfig:
    return BrowserRuntimeConfig(
        profile_path=Path(args.profile_path),
        headless=args.headless,
        browser_executable_path=(
            Path(args.browser_executable_path)
            if getattr(args, "browser_executable_path", "")
            else None
        ),
        seed_profile_path=(
            Path(args.seed_profile_path) if args.seed_profile_path else None
        ),
        socket_path=Path(args.socket_path),
        auth_token=str(getattr(args, "auth_token", "") or ""),
        sandbox_origin=str(getattr(args, "sandbox_origin", "") or ""),
    )


async def run_worker(config: BrowserRuntimeConfig) -> BrowserRuntime:
    telemetry = BrowserWorkerTelemetry(config.artifacts_dir / "worker.jsonl")
    runtime = BrowserRuntime(config=config, telemetry=telemetry)
    await runtime.start()
    return runtime


async def _run_forever(args: argparse.Namespace) -> None:
    runtime = await run_worker(build_runtime_config(args))
    logging.getLogger(__name__).info(
        "browser worker started with %s", runtime.config.profile_path
    )
    try:
        await runtime.serve_forever()
    finally:
        await runtime.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GengoWatcher browser worker")
    parser.add_argument("--profile-path", required=True)
    parser.add_argument(
        "--browser-executable-path",
        default="",
        help="Optional Chromium executable; useful for a system browser in tests",
    )
    parser.add_argument("--seed-profile-path")
    parser.add_argument("--socket-path", default="")
    parser.add_argument("--auth-token", default="")
    parser.add_argument(
        "--sandbox-origin",
        default="",
        help="Explicit local test origin, for example http://127.0.0.1:8765",
    )
    parser.add_argument("--headless", action="store_true", default=False)
    args = parser.parse_args(argv)

    if not args.socket_path:
        args.socket_path = str(
            BrowserRuntimeConfig(profile_path=Path(args.profile_path)).socket_path
        )

    logging.basicConfig(level=logging.INFO)
    worker_coro = _run_forever(args)
    try:
        asyncio.run(worker_coro)
    except KeyboardInterrupt:
        worker_coro.close()
        logging.getLogger(__name__).info("browser worker stopped")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
