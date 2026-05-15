from __future__ import annotations

import re
from typing import Any

RAW_WS_REDACTED = "[REDACTED]"
RAW_WS_SENSITIVE_KEYWORDS = (
    "authorization",
    "cookie",
    "session",
    "token",
    "secret",
    "key",
)
RAW_WS_SENSITIVE_PATTERNS = (
    (
        re.compile(r"(my_gengo_session=)[^;\s\"']+", re.IGNORECASE),
        rf"\1{RAW_WS_REDACTED}",
    ),
    (
        re.compile(r"(authorization\s*:\s*bearer\s+)[^\s,;}}]+", re.IGNORECASE),
        rf"\1{RAW_WS_REDACTED}",
    ),
    (
        re.compile(
            r"((?:token|api_key|secret|access_token|refresh_token|auth_token|"
            r"secret_key|session_key|client_secret)\s*=\s*['\"]?)[^'\";,\s}]+",
            re.IGNORECASE,
        ),
        rf"\1{RAW_WS_REDACTED}",
    ),
    (
        re.compile(
            r"((?:\"|')?(?:token|api_key|secret|access_token|refresh_token|"
            r"auth_token|secret_key|session_key|client_secret)(?:\"|')?\s*:\s*"
            r"['\"]?)[^'\",;\s}]+",
            re.IGNORECASE,
        ),
        rf"\1{RAW_WS_REDACTED}",
    ),
)


def raw_ws_key_is_sensitive(key: object) -> bool:
    normalized = str(key).lower()
    return any(keyword in normalized for keyword in RAW_WS_SENSITIVE_KEYWORDS)


def redact_raw_ws_value(value: Any):
    if isinstance(value, dict):
        return {
            key: (
                RAW_WS_REDACTED
                if raw_ws_key_is_sensitive(key)
                else redact_raw_ws_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_raw_ws_value(item) for item in value]
    return value


def redact_raw_ws_text(message: str) -> str:
    redacted = message
    for pattern, replacement in RAW_WS_SENSITIVE_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
