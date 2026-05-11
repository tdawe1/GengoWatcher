from __future__ import annotations

import concurrent.futures
import queue
import threading
from typing import Callable

TRANSLATION_APP_SUBMISSION_MAX_WORKERS = 1
TRANSLATION_APP_SUBMISSION_MAX_PENDING = 16
_translation_app_executor = None
_translation_app_executor_lock = threading.Lock()
_translation_app_submission_slots = threading.BoundedSemaphore(
    TRANSLATION_APP_SUBMISSION_MAX_WORKERS + TRANSLATION_APP_SUBMISSION_MAX_PENDING
)


def get_translation_app_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _translation_app_executor
    with _translation_app_executor_lock:
        if _translation_app_executor is None:
            _translation_app_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=TRANSLATION_APP_SUBMISSION_MAX_WORKERS,
                thread_name_prefix="TranslationAppSubmit",
            )
        return _translation_app_executor


def submit_translation_app_task(
    task: Callable[[], None],
) -> concurrent.futures.Future:
    if not _translation_app_submission_slots.acquire(blocking=False):
        raise queue.Full("translation-app submission queue is full")

    try:
        future = get_translation_app_executor().submit(task)
    except Exception:
        _translation_app_submission_slots.release()
        raise

    future.add_done_callback(
        lambda _future: _translation_app_submission_slots.release()
    )
    return future
