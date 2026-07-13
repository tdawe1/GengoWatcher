"""New-job processing pipeline extracted from GengoWatcher.

Owns the full new-job funnel: min_reward gating, dedup, state
storage, notification, cancellation/auto-accept routing, and
translation-app submission. The watcher keeps a thin delegator
method on the class so existing call sites and tests continue to
work unchanged.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time

from ..translation_app_queue import (
    submit_translation_app_task as _submit_translation_app_task,
)
from .watcher_config_values import PLACEHOLDER_CONFIG_VALUES
from .watcher_job_metadata import (
    derive_lang_pair,
    derive_word_count,
)

try:
    from ..translation_app_client import TranslationAppClient
except ImportError:  # pragma: no cover - translation-app optional
    TranslationAppClient = None

def process_new_job(watcher, job_id, title, reward, url, source, source_meta=None):
    """Process a newly discovered job from RSS or WebSocket sources.

    Handles job filtering, notification, storage, and auto-acceptance logic.
    Updates session statistics and ensures thread-safe access to shared state.

    Args:
        job_id: Unique identifier for the job.
        title: Job title/description.
        reward: Job reward amount in USD.
        url: URL to access the job.
        source: Source of the job discovery ("RSS" or "WebSocket").
        source_meta: Optional metadata from the source (entry dict, websocket payload, etc.).
    """
    watcher.logger.debug(
        f"Processing new job: {job_id}, {title}, {reward}, {url}, {source}"
    )
    with watcher._seen_jobs_lock:
        if job_id in watcher._seen_jobs_session:
            return
        min_reward = watcher.config.get("Watcher", "min_reward")
        if min_reward is not None and min_reward > 0.0 and reward < min_reward:
            watcher.logger.warning(
                f"Job '{title}' (US$ {reward:.2f}) ignored due to [yellow]min_reward filter[/]."
            )
            return

        lang_pair = derive_lang_pair(title, source_meta)
        word_count = derive_word_count(title, source_meta, reward=reward)

        # Prepare job data for storage, callbacks, and acceptance checks
        job_data = {
            "id": str(job_id),
            "title": title,
            "reward": float(reward),
            "currency": "USD",
            "url": url,
            "timestamp": time.time(),
            "source": source,
            "lang_pair": lang_pair,
            "word_count": word_count,
            "source_meta": watcher._json_safe(source_meta or {}),
            "lifecycle_state": "detected",
            "acceptance_state": "not_requested",
            "workflow_state": "new",
        }

        try:
            inserted = watcher.state.add_job(job_data)
            if inserted is False:
                # Job is a duplicate, bail out immediately
                return

            # Job was successfully inserted, proceed with all side effects
            watcher.logger.info(
                f"[success]New job via {source}: {title.split('|')[0].strip()} (US$ {reward:.2f})[/success]"
            )
            watcher.show_notification(
                message=title,
                title="New Gengo Job Available!",
                play_sound=True,
                open_link=True,
                url=url,
            )

            # Update bookkeeping after successful add_job
            watcher._seen_jobs_session.add(job_id)
            watcher.state.seen_job_ids.append(job_id)
            watcher.state.total_new_entries_found += 1
            watcher.session_new_entries += 1
            watcher.session_total_value += reward
        except Exception as e:
            watcher.logger.warning(f"Failed to store job in state: {e}")
            return

    eligible_for_auto_accept = watcher.job_acceptance_engine.is_job_eligible(job_data)
    allow_http_fallback = watcher.config.getboolean(
        "AutoAccept", "allow_http_fallback", fallback=False
    )
    watcher._emit_webhook_event("job.discovered", job_data)
    watcher._emit_api_event("job.discovered", job_data)
    watcher._emit_api_event("job.details", job_data)

    if watcher.browser_worker_enabled and eligible_for_auto_accept:
        watcher.logger.info(
            "Routing job %s to browser worker via local client", job_id
        )
        if not watcher.browser_worker_client:
            if allow_http_fallback:
                watcher.logger.error(
                    "Browser worker is enabled for job %s but the local client is unavailable;"
                    " falling back to standard acceptance path",
                    job_id,
                )
            else:
                watcher.logger.error(
                    "Browser worker is enabled for job %s but the local client is unavailable;"
                    " HTTP fallback is disabled",
                    job_id,
                )
        else:
            try:
                watcher.browser_worker_client.submit_job(
                    url,
                    source,
                    metadata=job_data,
                )
                accept_requested_payload = {
                    **job_data,
                    "accept_path": "browser_worker",
                    "acceptance_state": "requested",
                    "lifecycle_state": "accept_requested",
                }
                watcher._emit_webhook_event(
                    "job.accept_requested",
                    accept_requested_payload,
                )
                watcher.state.update_job(
                    str(job_id),
                    {
                        "acceptance_state": "requested",
                        "lifecycle_state": "accept_requested",
                        "accept_path": "browser_worker",
                    },
                )
                watcher._emit_api_event(
                    "job.accept_requested",
                    accept_requested_payload,
                )
                watcher.state.save_state()
                if watcher.on_job_added_callback:
                    try:
                        watcher.on_job_added_callback(job_data)
                    except Exception as e:
                        watcher.logger.debug(f"Error in job added callback: {e}")
                return
            except Exception as e:
                if allow_http_fallback:
                    watcher.logger.error(
                        "Failed to submit job %s to browser worker: %s; falling back to"
                        " standard acceptance path",
                        job_id,
                        e,
                    )
                else:
                    watcher.logger.error(
                        "Failed to submit job %s to browser worker: %s; HTTP fallback is disabled",
                        job_id,
                        e,
                    )

    # Consider cancelling a current job if this one is better
    try:
        if (
            watcher.cancellation_manager.cancellation_enabled
            and watcher.cancellation_manager.should_cancel_for_job(
                float(job_data.get("reward", 0.0)), str(job_data.get("id"))
            )
        ):
            watcher.logger.info(
                "Better opportunity detected - scheduling cancellation of current job before accepting new job"
            )
            threading.Thread(
                target=watcher._async_cancel_current_job_wrapper,
                args=(job_data,),
                daemon=True,
            ).start()
    except Exception as e:
        watcher.logger.error(f"Error while evaluating job cancellation: {e}")

    # Check if job should be auto-accepted
    if eligible_for_auto_accept:
        if not allow_http_fallback:
            watcher.logger.info(
                "Job %s meets auto-accept criteria, but standard HTTP acceptance is disabled",
                job_id,
            )
            failed_payload = {
                **job_data,
                "acceptance_state": "failed",
                "lifecycle_state": "accept_failed",
                "accept_path": "native_browser",
                "reason": "http fallback disabled",
            }
            watcher.state.update_job(
                str(job_id),
                {
                    "acceptance_state": "failed",
                    "lifecycle_state": "accept_failed",
                    "accept_path": "native_browser",
                    "accept_failure_reason": "http fallback disabled",
                },
            )
            watcher.state.save_state()
            watcher._emit_webhook_event("job.accept_failed", failed_payload)
            watcher._emit_api_event("job.accept_failed", failed_payload)
            watcher._submit_job_to_translation_app_async(job_data)
            return

        watcher.logger.info(
            f"Job {job_id} meets auto-accept criteria, queuing for acceptance"
        )
        accept_requested_payload = {
            **job_data,
            "accept_path": "standard",
            "acceptance_state": "requested",
            "lifecycle_state": "accept_requested",
        }
        watcher._emit_webhook_event(
            "job.accept_requested",
            accept_requested_payload,
        )
        watcher.state.update_job(
            str(job_id),
            {
                "acceptance_state": "requested",
                "lifecycle_state": "accept_requested",
                "accept_path": "standard",
            },
        )
        watcher._emit_api_event("job.accept_requested", accept_requested_payload)
        threading.Thread(
            target=watcher._async_job_acceptance_wrapper, args=(job_data,), daemon=True
        ).start()
    else:
        watcher.logger.debug(f"Job {job_id} does not meet auto-accept criteria")

    watcher._submit_job_to_translation_app_async(job_data)
    watcher.state.save_state()

    if watcher.on_job_added_callback:
        try:
            watcher.on_job_added_callback(job_data)
        except Exception as e:
            watcher.logger.debug(f"Error in job added callback: {e}")
def async_job_acceptance_wrapper(watcher, job_data: dict):
    """
    Wrapper to run async job acceptance in a separate thread.

    Args:
        job_data: Dictionary containing job information
    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(
            watcher.job_acceptance_engine.accept_job(job_data)
        )
        if success:
            watcher._on_job_accepted(job_data)
        else:
            watcher.state.update_job(
                str(job_data.get("id")),
                {
                    "acceptance_state": "failed",
                    "lifecycle_state": "accept_failed",
                    "accept_failure_reason": "accept_job returned false",
                },
            )
            watcher.state.save_state()
            failed_payload = {
                **job_data,
                "acceptance_state": "failed",
                "lifecycle_state": "accept_failed",
                "reason": "accept_job returned false",
            }
            watcher._emit_webhook_event(
                "job.accept_failed",
                failed_payload,
            )
            watcher._emit_api_event("job.accept_failed", failed_payload)
    except Exception as e:
        watcher.logger.error(
            f"Error in job acceptance wrapper for job {job_data.get('id')}: {e}"
        )
        watcher.state.update_job(
            str(job_data.get("id")),
            {
                "acceptance_state": "failed",
                "lifecycle_state": "accept_failed",
                "accept_failure_reason": str(e),
            },
        )
        watcher.state.save_state()
        failed_payload = {
            **job_data,
            "acceptance_state": "failed",
            "lifecycle_state": "accept_failed",
            "reason": str(e),
        }
        watcher._emit_webhook_event(
            "job.accept_failed",
            failed_payload,
        )
        watcher._emit_api_event("job.accept_failed", failed_payload)
    finally:
        loop.close()

def async_cancel_current_job_wrapper(watcher, upcoming_job: dict):
    """Wrapper to cancel the current job without blocking the main thread."""
    previous_job_id = watcher.cancellation_manager.current_job_id
    try:
        success = watcher.cancel_current_job_sync()
        if success:
            watcher.logger.info(
                f"Current job {previous_job_id} cancelled. Preparing to accept {upcoming_job.get('id')}"
            )
        else:
            watcher.logger.warning(
                "Failed to cancel current job before processing new opportunity"
            )
    except Exception as e:
        watcher.logger.error(f"Error during automatic job cancellation: {e}")

def submit_job_to_translation_app_async(watcher, job_data: dict) -> None:
    """Submit a discovered job to translation-app without blocking monitors."""
    if TranslationAppClient is None:
        watcher.logger.debug("translation-app client is unavailable")
        return
    if not watcher.config.getboolean("TranslationApp", "enabled", fallback=False):
        return

    base_url = str(
        watcher.config.get("TranslationApp", "base_url", fallback="") or ""
    ).strip()
    auth_token = str(
        watcher.config.get("TranslationApp", "auth_token", fallback="") or ""
    ).strip()
    if not base_url or auth_token in PLACEHOLDER_CONFIG_VALUES:
        watcher.logger.warning(
            "TranslationApp is enabled but base_url or auth_token is not configured"
        )
        return

    timeout_sec = float(
        watcher.config.getfloat("TranslationApp", "timeout_sec", fallback=5.0) or 5.0
    )
    verify_tls = watcher.config.getboolean(
        "TranslationApp", "verify_tls", fallback=True
    )

    def submit() -> None:
        try:
            client = TranslationAppClient(
                base_url=base_url,
                auth_token=auth_token,
                timeout_sec=timeout_sec,
                verify_tls=verify_tls,
                logger=watcher.logger,
            )
            client.submit_job(dict(job_data))
        except Exception:
            watcher.logger.exception(
                "Failed to submit job %s to translation-app",
                job_data.get("id", "unknown"),
            )

    try:
        _submit_translation_app_task(submit)
    except queue.Full:
        watcher.logger.warning(
            "Translation-app submission queue is full; dropping job %s",
            job_data.get("id", "unknown"),
        )
    except Exception:
        watcher.logger.exception(
            "Failed to queue job %s for translation-app submission",
            job_data.get("id", "unknown"),
        )


__all__ = [
    "process_new_job",
    "async_job_acceptance_wrapper",
    "async_cancel_current_job_wrapper",
    "submit_job_to_translation_app_async",
]
