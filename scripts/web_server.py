#!/usr/bin/env python3
"""
Standalone web server for GengoWatcher web UI.
Run this to start only the web interface without the TUI.
"""

import sys
import os
from pathlib import Path

# Add src to path so we can import gengowatcher
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gengowatcher.web import run_web_server

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="GengoWatcher Web Server")
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port to bind to (default: 8000)"
    )

    args = parser.parse_args()

    print(f"Starting GengoWatcher Web Server on http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop")

    try:
        run_web_server(host=args.host, port=args.port)
    except KeyboardInterrupt:
        print("\nWeb server stopped")
    except Exception as e:
        print(f"Error starting web server: {e}")
        sys.exit(1)
