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
        seed_profile_path=Path(args.seed_profile_path)
        if args.seed_profile_path
        else None,
        socket_path=Path(args.socket_path),
    )


async def run_worker(config: BrowserRuntimeConfig) -> BrowserRuntime:
    telemetry = BrowserWorkerTelemetry(config.artifacts_dir / "worker.jsonl")
    runtime = BrowserRuntime(config=config, telemetry=telemetry)
    await runtime.start()
    return runtime


<<<<<<< HEAD
async def _run_forever(args: argparse.Namespace) -> None:
    runtime = await run_worker(build_runtime_config(args))
    logging.getLogger(__name__).info(
        "browser worker started with %s", runtime.config.profile_path
    )
    try:
        await runtime.serve_forever()
    finally:
        await runtime.stop()


=======
>>>>>>> da0e254 (feat: add browser worker handoff flow)
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GengoWatcher browser worker")
    parser.add_argument("--profile-path", required=True)
    parser.add_argument("--seed-profile-path")
    parser.add_argument("--socket-path", default="")
    parser.add_argument("--headless", action="store_true", default=False)
    args = parser.parse_args(argv)

    if not args.socket_path:
        args.socket_path = str(BrowserRuntimeConfig(profile_path=Path(args.profile_path)).socket_path)

    logging.basicConfig(level=logging.INFO)
<<<<<<< HEAD
    try:
        asyncio.run(_run_forever(args))
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("browser worker stopped")
=======
    runtime = asyncio.run(run_worker(build_runtime_config(args)))
    logging.getLogger(__name__).info(
        "browser worker started with %s", runtime.config.profile_path
    )
>>>>>>> da0e254 (feat: add browser worker handoff flow)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
