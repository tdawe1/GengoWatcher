from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

_T = TypeVar("_T")
_EVENT_LOOP_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="gengowatcher-sync-async",
)


def shutdown_event_loop_executor() -> None:
    """Stop the shared sync-to-async executor without blocking shutdown."""
    _EVENT_LOOP_EXECUTOR.shutdown(wait=False, cancel_futures=True)


atexit.register(shutdown_event_loop_executor)


def run_coroutine_sync(
    coro_func: Callable[..., Awaitable[_T]],
    *args: Any,
    _result_timeout_sec: float | None = 30.0,
    **kwargs: Any,
) -> _T:
    async def run_with_timeout() -> _T:
        coroutine = coro_func(*args, **kwargs)
        if _result_timeout_sec is None:
            return await coroutine
        return await asyncio.wait_for(coroutine, timeout=_result_timeout_sec)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_with_timeout())

    future = _EVENT_LOOP_EXECUTOR.submit(lambda: asyncio.run(run_with_timeout()))
    outer_timeout = None if _result_timeout_sec is None else _result_timeout_sec + 1.0
    return future.result(timeout=outer_timeout)
