# Code Organization

## Module Layout
- Prefer small helper functions for parsing, coercion, and lifecycle boundaries.
- CLI lives in cli.py; startup/runtime orchestration in runtime.py and main.py; web layer in web.py, web_models.py, webhooks.py, web_file_storage.py.
- Shared mutable state is typically protected with threading.Lock or threading.RLock.
- Async workflows bridge blocking code with asyncio.to_thread().
- State and config persistence prefer atomic writes over in-place file mutation.

## Error Handling
- Catch specific exceptions where the failure mode is known.
- Broad except Exception belongs at app boundaries, startup paths, UI loops, and optional integrations; log with context or convert to a clear user-facing fallback.
- Use logger.exception(...) to preserve traceback; logger.warning(...)/logger.error(...) for recoverable issues.
- Avoid silent exception swallowing unless degradation is intentional.

## Logging Conventions
- Modules receive or create a logging.Logger via logging_setup.py.
- Prefer concise, actionable messages with enough context to debug failures.
- CLI/runtime paths may also use rich.console.Console.
- Avoid noisy logs in hot paths unless they are gated by an existing debug category.

## Config and State Conventions
- config.toml is canonical; config.ini is legacy and migrated by AppConfig.
- Placeholder secrets (REPLACE_WITH_YOUR_*) are tracked explicitly; never treat them as real values.
- Use pathlib.Path for filesystem paths.
- Preserve atomic-write semantics when touching config or state persistence code.
