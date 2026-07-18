# GengoWatcher Ratatui TUI

This is the native terminal client for GengoWatcher. It deliberately keeps
watcher, browser, and persistence logic in Python and consumes the authenticated
local FastAPI boundary.

The normal entrypoint starts the API and client together:

```bash
PYTHONPATH=src python3 -m gengowatcher.main
```

For direct development, start GengoWatcher in web-only mode and export the token
from `[WebServer].auth_token`:

```bash
PYTHONPATH=src python3 -m gengowatcher.main --web-only
GENGOWATCHER_API_TOKEN=... cargo run --manifest-path \
  prototypes/garden-ratatui/Cargo.toml
```

Useful development commands:

```bash
cargo run --manifest-path prototypes/garden-ratatui/Cargo.toml -- --demo
cargo test --manifest-path prototypes/garden-ratatui/Cargo.toml
cargo clippy --manifest-path prototypes/garden-ratatui/Cargo.toml \
  --all-targets -- -D warnings
cargo run --manifest-path prototypes/garden-ratatui/Cargo.toml -- \
  --render prototypes/garden-ratatui-previews
```

Security properties:

- the bearer token is read from `GENGOWATCHER_API_TOKEN`, never a CLI flag;
- API connections are restricted to the local loopback HTTP service;
- job IDs are validated before being placed into request paths;
- accept and cancel operations require an explicit confirmation;
- API failures preserve the last valid snapshot and reconnect with bounded
  exponential backoff.
