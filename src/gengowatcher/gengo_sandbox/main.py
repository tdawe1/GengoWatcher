from __future__ import annotations

import argparse
import ipaddress

import uvicorn


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().rstrip(".")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local Gengo webapp sandbox")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument(
        "--unsafe-expose",
        action="store_true",
        help="Allow binding the unauthenticated sandbox to a non-loopback host",
    )
    args = parser.parse_args(argv)
    if not args.unsafe_expose and not _is_loopback_host(args.host):
        parser.error(
            "refusing to expose the unauthenticated sandbox on a non-loopback "
            "host; pass --unsafe-expose to acknowledge the risk"
        )
    uvicorn.run(
        "gengowatcher.gengo_sandbox.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
