from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

_T = TypeVar("_T")
_EVENT_LOOP_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="gengowatcher-sync-async",
)


def run_coroutine_sync(
    coro_func: Callable[..., Awaitable[_T]],
    *args: Any,
    **kwargs: Any,
) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_func(*args, **kwargs))

    future = _EVENT_LOOP_EXECUTOR.submit(
        lambda: asyncio.run(coro_func(*args, **kwargs))
    )
    return future.result()
