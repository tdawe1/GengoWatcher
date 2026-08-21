from __future__ import annotations

import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

JOB_DETAILS_RE = re.compile(r"^/t/jobs/details/(?P<job_id>\d+)/?$")
ALLOWED_GENGO_HOST_SUFFIX = ".gengo.com"
ALLOWED_GENGO_HOST = "gengo.com"


def _is_allowed_gengo_hostname(hostname: str) -> bool:
    normalized = hostname.lower().rstrip(".")
    return normalized == ALLOWED_GENGO_HOST or normalized.endswith(
        ALLOWED_GENGO_HOST_SUFFIX
    )


def _origin_tuple(value: str) -> tuple[str, str, int | None]:
    parts = urlsplit(str(value or "").strip())
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
    ):
        raise ValueError(f"invalid browser worker sandbox origin: {value}")
    hostname = parts.hostname.lower().rstrip(".")
    if hostname != "localhost":
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError as exc:
            raise ValueError(
                f"browser worker sandbox origin must use a loopback host: {value}"
            ) from exc
        if not address.is_loopback:
            raise ValueError(
                f"browser worker sandbox origin must use a loopback host: {value}"
            )
    return parts.scheme, hostname, parts.port


def normalize_sandbox_origin(value: str) -> str:
    """Canonicalize an optional HTTP(S) loopback origin.

    Non-empty values must have no credentials, path, query, or fragment.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    scheme, hostname, port = _origin_tuple(text)
    if ":" in hostname:
        netloc = f"[{hostname}]"
    else:
        netloc = hostname
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, "", "", ""))


def url_origin(value: str) -> tuple[str, str, int | None]:
    parts = urlsplit(str(value or "").strip())
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise ValueError(f"invalid browser URL origin: {value}")
    return parts.scheme, parts.hostname.lower().rstrip("."), parts.port


def is_allowed_browser_origin(
    url: str, *, allowed_origins: tuple[str, ...] = ()
) -> bool:
    try:
        candidate_origin = url_origin(url)
    except ValueError:
        return False
    scheme, hostname, port = candidate_origin
    is_production = (
        scheme == "https"
        and _is_allowed_gengo_hostname(hostname)
        and port in (None, 443)
    )
    if is_production:
        return True
    return candidate_origin in {
        _origin_tuple(origin) for origin in allowed_origins if str(origin).strip()
    }


def has_same_origin(url: str, expected_url: str) -> bool:
    try:
        return url_origin(url) == url_origin(expected_url)
    except ValueError:
        return False


def canonicalize_job_url(url: str, *, allowed_origins: tuple[str, ...] = ()) -> str:
    parts = urlsplit(url)
    hostname = (parts.hostname or "").lower().rstrip(".")
    if parts.username or parts.password:
        raise ValueError("Gengo job URL must not include credentials")

    is_production = (
        parts.scheme == "https"
        and _is_allowed_gengo_hostname(hostname)
        and parts.port in (None, 443)
    )
    candidate_origin = (parts.scheme, hostname, parts.port)
    is_explicitly_allowed = candidate_origin in {
        _origin_tuple(origin) for origin in allowed_origins if str(origin).strip()
    }
    if not is_production and not is_explicitly_allowed:
        raise ValueError(f"unsupported Gengo job URL host: {url}")
    match = JOB_DETAILS_RE.fullmatch(parts.path)
    if match is None:
        raise ValueError(f"unable to extract job id from url: {url}")
    path = parts.path.rstrip("/")
    netloc = hostname if is_production else parts.netloc.lower()
    return urlunsplit((parts.scheme, netloc, path, "", ""))


def extract_job_id(url: str) -> str:
    match = JOB_DETAILS_RE.fullmatch(urlsplit(url).path)
    if not match:
        raise ValueError(f"unable to extract job id from url: {url}")
    return match.group("job_id")


def build_job_url_command(
    url: str,
    source: str,
    *,
    metadata: dict[str, Any] | None = None,
    auth_token: str = "",
    allowed_origins: tuple[str, ...] = (),
) -> dict[str, Any]:
    command = {
        "type": "job_url",
        "url": canonicalize_job_url(url, allowed_origins=allowed_origins),
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
