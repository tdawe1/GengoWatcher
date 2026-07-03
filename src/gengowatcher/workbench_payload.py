"""Normalize workbench payloads from browser observation.

Extracts clean structure from raw workbench JSON:
- collection_id, order_id, customer_id
- job_ids, lc_src, lc_tgt
- tier, purpose, reward
- unit_count, expire_time, seconds_left
- allotted_seconds, segments, source_text
"""

from __future__ import annotations

import re
from typing import Any


def _first_present(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if value is not None and value != "":
            return value
    return None


def _epoch_seconds(value: Any) -> int | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return int(numeric / 1000) if numeric > 10_000_000_000 else int(numeric)


def _segment_source_text(segment: dict[str, Any]) -> str:
    value = _first_present(segment, "source_content", "text", "source_text", "source")
    return str(value or "")


def normalize_workbench_payload(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize raw workbench payload to standard format."""
    if not isinstance(raw, dict):
        return {}

    payload: dict[str, Any] = {}

    # URL extraction
    url = raw.get("url") or raw.get("workbench_url") or ""
    match = re.search(r"/workbench/([^/?]+)", url) if url else None
    if match:
        payload["collection_id"] = match.group(1)

    # Order ID
    raw_summary = raw.get("summary")
    raw_order = raw.get("order")
    if isinstance(raw_summary, dict):
        summary = raw_summary
    elif isinstance(raw_order, dict):
        summary = raw_order
    else:
        summary = raw

    payload["order_id"] = _first_present(summary, "order_id", "id", "order")
    payload["customer_id"] = _first_present(summary, "customer_id", "customer")

    # Language pair
    payload["lc_src"] = _first_present(summary, "lc_src", "source_language")
    payload["lc_tgt"] = _first_present(summary, "lc_tgt", "target_language")

    # Job IDs
    jobs = raw.get("jobs") or raw.get("job_list") or []
    if isinstance(jobs, list):
        payload["job_ids"] = [
            job_id
            for job in jobs
            if isinstance(job, dict)
            for job_id in [_first_present(job, "id", "job_id")]
            if job_id
        ]

    # Reward and units
    payload["reward"] = _first_present(summary, "reward", "rewards_total") or 0
    payload["unit_count"] = _first_present(summary, "unit_count", "units") or len(
        payload.get("job_ids", [])
    )

    # Timing
    expire_time = _first_present(summary, "expire_time", "deadline")
    if expire_time:
        epoch_seconds = _epoch_seconds(expire_time)
        if epoch_seconds is not None:
            payload["expire_time"] = epoch_seconds

    payload["allotted_seconds"] = _first_present(summary, "allotted_seconds")
    payload["seconds_left"] = _first_present(summary, "seconds_left", "left")

    # Tier and purpose
    payload["tier"] = _first_present(summary, "tier", "quality_tier")
    payload["purpose"] = summary.get("purpose")

    # Segments and source text - check both top-level and jobs[].segments
    segments = raw.get("segments") or []
    if not segments and isinstance(jobs, list) and len(jobs) > 0:
        # Extract all segments from all jobs
        all_segments = []
        for job in jobs:
            if isinstance(job, dict):
                job_segments = job.get("segments") or []
                if isinstance(job_segments, list):
                    all_segments.extend(job_segments)
        segments = all_segments

    if isinstance(segments, list):
        payload["segments"] = segments
        source_parts = [
            _segment_source_text(segment)
            for segment in segments
            if isinstance(segment, dict)
        ]
        payload["source_text"] = "\n\n".join(part for part in source_parts if part)

    # Preserve raw for audit
    payload["_raw"] = raw

    return payload
