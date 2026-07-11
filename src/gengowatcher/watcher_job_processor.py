"""New-job processing pipeline extracted from GengoWatcher.

Owns the full new-job funnel: min_reward gating, dedup, state
storage, notification, cancellation/auto-accept routing, and
translation-app submission. The watcher keeps a thin delegator
method on the class so existing call sites and tests continue to
work unchanged.
"""

from __future__ import annotations

import threading
import time

from .watcher_job_metadata import (
    derive_lang_pair,
    derive_word_count,
)

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
        if min_reward > 0.0 and reward < min_reward:
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

__all__ = ["process_new_job"]
