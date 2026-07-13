"""Browser-worker telemetry listener + job-accepted callback
extracted from GengoWatcher.

* run_browser_worker_event_listener(watcher) -- Tails the
  browser-worker JSONL telemetry file at
  watcher._browser_worker_telemetry_path(), reads new lines as
  they're appended, watches for truncation / file rotation via
  st_size/st_ino/st_dev, and forwards each line to
  watcher._handle_browser_worker_telemetry_line. Idles on
  watcher.shutdown_event at 0.5s granularity when there is no
  new data or the file doesn't yet exist.

* on_job_accepted(watcher, job_data) -- Records that a job has
  been accepted: persists accepted_workbench + workbench_url via
  watcher.state.mark_job_accepted / save_state, sets
  watcher.cancellation_manager.set_current_job(job_id, reward),
  then emits 'job.accepted' through both the alerting webhook
  and API event channels. Tolerates missing legacy state by
  building the accepted-job dict inline so the event payloads
  remain useful.

The watcher keeps thin delegator methods on the class so the
existing ``threading.Thread(target=self._run_*, daemon=True)``
call sites in watcher.run() and watcher_job_processor.py:284 keep
resolving them through the instance.
"""

from __future__ import annotations

import os


def run_browser_worker_event_listener(watcher) -> None:
    telemetry_path = watcher._browser_worker_telemetry_path()
    watcher.logger.info("Browser worker event listener watching %s", telemetry_path)
    initialized = False
    skip_existing_on_open = True
    while not watcher.shutdown_event.is_set():
        if not telemetry_path.exists():
            watcher.shutdown_event.wait(1.0)
            continue

        try:
            with telemetry_path.open("r", encoding="utf-8") as handle:
                opened_stat = os.fstat(handle.fileno())
                if not initialized:
                    if skip_existing_on_open:
                        handle.seek(0, os.SEEK_END)
                    initialized = True
                    skip_existing_on_open = False
                    ready_event = getattr(
                        watcher, "_browser_worker_listener_ready_event", None
                    )
                    if ready_event is not None:
                        ready_event.set()
                while not watcher.shutdown_event.is_set():
                    line = handle.readline()
                    if not line:
                        try:
                            current_stat = telemetry_path.stat()
                            if (
                                current_stat.st_size < handle.tell()
                                or current_stat.st_ino != opened_stat.st_ino
                                or current_stat.st_dev != opened_stat.st_dev
                            ):
                                initialized = False
                                skip_existing_on_open = False
                                break
                        except OSError:
                            initialized = False
                            break
                        watcher.shutdown_event.wait(0.5)
                        continue
                    watcher._handle_browser_worker_telemetry_line(line)
        except OSError as exc:
            watcher.logger.debug(
                "Browser worker telemetry listener could not read %s: %s",
                telemetry_path,
                exc,
            )
            watcher.shutdown_event.wait(1.0)
        except Exception:
            watcher.logger.exception("Browser worker telemetry listener failed")
            watcher.shutdown_event.wait(1.0)
    watcher.logger.info("Browser worker event listener stopped.")


def on_job_accepted(watcher, job_data: dict):
    """Record that a job has been accepted for future cancellation decisions."""
    try:
        job_id = str(job_data.get("id"))
        reward = float(job_data.get("reward", 0.0))
        try:
            watcher.state.mark_job_accepted(
                job_id,
                accepted_workbench=job_data.get("accepted_workbench"),
                workbench_url=job_data.get("workbench_url"),
            )
            watcher.state.save_state()
        except Exception:
            watcher.logger.exception(
                "Failed to persist accepted job metadata for job %s",
                job_id,
            )
        watcher.cancellation_manager.set_current_job(job_id, reward)
        watcher.logger.debug(
            f"Tracking job {job_id} (${reward:.2f}) as current engagement"
        )
        current_job = watcher.state.get_job(job_id)
        accepted_job = {
            **job_data,
            **(current_job if isinstance(current_job, dict) else {}),
            "accepted": True,
            "acceptance_state": "accepted",
            "lifecycle_state": "accepted",
        }
        watcher._emit_webhook_event("job.accepted", accepted_job)
        watcher._emit_api_event("job.accepted", accepted_job)
    except Exception as e:
        watcher.logger.exception(
            f"Failed to record accepted job for cancellation tracking: {e}"
        )


__all__ = ["run_browser_worker_event_listener", "on_job_accepted"]
