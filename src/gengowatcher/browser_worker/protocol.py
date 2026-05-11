from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit


JOB_DETAILS_RE = re.compile(r"/t/jobs/details/(?P<job_id>\d+)")
ALLOWED_GENGO_HOST_SUFFIX = ".gengo.com"
ALLOWED_GENGO_HOST = "gengo.com"


def _is_allowed_gengo_hostname(hostname: str) -> bool:
    normalized = hostname.lower().rstrip(".")
    return normalized == ALLOWED_GENGO_HOST or normalized.endswith(
        ALLOWED_GENGO_HOST_SUFFIX
    )


def canonicalize_job_url(url: str) -> str:
    parts = urlsplit(url)
    hostname = parts.hostname or ""
    if parts.scheme != "https" or not _is_allowed_gengo_hostname(hostname):
        raise ValueError(f"unsupported Gengo job URL host: {url}")
    if parts.username or parts.password:
        raise ValueError("Gengo job URL must not include credentials")
    if parts.port not in (None, 443):
        raise ValueError("Gengo job URL must use the default HTTPS port")
    path = parts.path.rstrip("/")
    if not JOB_DETAILS_RE.search(path):
        raise ValueError(f"unable to extract job id from url: {url}")
    return urlunsplit(("https", hostname.lower(), path, "", ""))


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
    auth_token: str = "",
) -> dict[str, Any]:
    command = {
        "type": "job_url",
        "url": canonicalize_job_url(url),
        "source": source,
        "metadata": metadata or {},
    }
    if auth_token:
        command["auth_token"] = auth_token
    return command


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
