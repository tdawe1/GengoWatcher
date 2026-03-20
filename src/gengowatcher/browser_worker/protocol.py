from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit


JOB_DETAILS_RE = re.compile(r"/t/jobs/details/(?P<job_id>\d+)")


def canonicalize_job_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def extract_job_id(url: str) -> str:
    match = JOB_DETAILS_RE.search(urlsplit(url).path)
    if not match:
        raise ValueError(f"unable to extract job id from url: {url}")
    return match.group("job_id")


def build_job_url_command(
    url: str,
    source: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "job_url",
        "url": canonicalize_job_url(url),
        "source": source,
        "metadata": metadata or {},
    }


def encode_message(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")


def decode_message(payload: bytes) -> dict[str, Any]:
    text = payload.decode("utf-8").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        snippet = text[:120]
        raise ValueError(
            f"invalid browser worker message payload: {snippet!r}"
        ) from exc
