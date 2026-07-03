from __future__ import annotations

import datetime
import re
from typing import Any

from textual.color import Color
from textual.theme import BUILTIN_THEMES, Theme

from .watcher_job_metadata import TIER_UNIT_RATES


class Icons:
    FOUND = ""
    ACCEPTED = ""
    VALUE = ""
    RATE = ""
    TODAY = ""
    MIN_WORDS = "≥"

    WEBSOCKET = ""
    EMAIL = ""
    WEB = ""
    RSS = ""
    CAPTCHA = ""
    WORKFLOW = ""
    AUTO = ""
    API = ""
    WEBHOOK = ""

    PANEL_ACTIVITY = ""
    PANEL_JOBS = ""
    PANEL_CHART = ""
    PANEL_CONFIG = ""
    PANEL_SESSION = ""
    PANEL_TELEMETRY = ""
    IDLE = "○"
    LIVE = "∿∿∿"
    POLLING = "↻"


SOURCE_BUCKET_CONFIG = {
    "websocket": {"label": "WebSocket", "color": "secondary"},
    "email": {"label": "Email", "color": "accent"},
    "website": {"label": "Website", "color": "primary"},
    "rss": {"label": "RSS", "color": "success"},
    "unknown": {"label": "Unknown", "color": "text-muted"},
}

ACTIVITY_PREVIEW_MAX_LINES = 250
ACTIVITY_LOG_MAX_LINES = 1000
OUTPUT_LOG_MAX_LINES = 500
TELEMETRY_SECTION_ORDER = (
    "websocket",
    "rss",
    "session",
    "workflow",
    "email",
    "browser",
    "api_events",
)
TELEMETRY_LABELS = {
    "websocket": ("WS", "WEBSOCKET"),
    "rss": ("RSS", "RSS"),
    "session": ("Session", "SESSION"),
    "workflow": ("Workflow", "WORKFLOW"),
    "email": ("Email", "EMAIL"),
    "browser": ("Browser", "BROWSER"),
    "api_events": ("API", "API"),
}

_TIMESTAMP_PREFIX_PATTERN = re.compile(
    r"^\s*(?:"
    r"\[\d{2}:\d{2}:\d{2}\]"
    r"|\d{2}:\d{2}:\d{2}\b"
    r"|\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\]?"
    r")"
)


def format_timestamp(timestamp: Any) -> str:
    """Normalize a timestamp value to HH:MM:SS for display."""
    if timestamp is None:
        return ""

    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        try:
            dt = datetime.datetime.fromtimestamp(timestamp)
        except (OSError, OverflowError, ValueError):
            return ""
        return dt.strftime("%H:%M:%S")

    if isinstance(timestamp, str):
        cleaned = timestamp.strip()
        if not cleaned:
            return ""

        iso_candidate = cleaned
        if iso_candidate.endswith("Z"):
            iso_candidate = iso_candidate[:-1] + "+00:00"
        try:
            dt = datetime.datetime.fromisoformat(iso_candidate)
            return dt.strftime("%H:%M:%S")
        except ValueError:
            pass

        for sep in ("T", " "):
            if sep in cleaned:
                _, _, tail = cleaned.partition(sep)
                match = re.match(r"(\d{2}:\d{2}:\d{2})", tail)
                if match:
                    return match.group(1)

        match = re.match(r"(\d{2}:\d{2}:\d{2})", cleaned)
        if match:
            return match.group(1)
        return ""

    return ""


def with_timestamp_prefix(
    message: str,
    now: datetime.datetime | None = None,
) -> str:
    """Prefix a message with [HH:MM:SS] if it has no leading timestamp."""
    text = "" if message is None else str(message)
    if _TIMESTAMP_PREFIX_PATTERN.match(text):
        return text

    current_time = now or datetime.datetime.now()
    return f"[{current_time.strftime('%H:%M:%S')}] {text}".rstrip()


def get_active_theme(owner: Any) -> Theme:
    """Get the current Textual theme for an app/widget/handler owner."""
    app = None
    try:
        app = owner.app
    except Exception:
        app = getattr(owner, "__dict__", {}).get("app")
    if app is not None:
        theme = getattr(app, "current_theme", None)
        if isinstance(theme, Theme):
            return theme
    return BUILTIN_THEMES["textual-dark"]


def to_rich_color(color_value: str) -> str:
    """Normalize a Textual color value to a Rich-compatible color string."""
    try:
        return Color.parse(color_value).hex6
    except Exception:
        return color_value


def build_semantic_color_palette(theme: Theme) -> dict[str, str]:
    """Build semantic Rich color roles from a Textual theme."""
    generated = theme.to_color_system().generate()

    def rich_color(name: str) -> str:
        return to_rich_color(generated[name])

    return {
        "timestamp": rich_color("foreground-muted"),
        "job_id": rich_color("primary"),
        "money": rich_color("warning"),
        "lang_pair": rich_color("secondary"),
        "number": rich_color("accent"),
        "success": rich_color("success"),
        "error_word": rich_color("error"),
        "warning_word": rich_color("warning"),
        "source_ws": rich_color("secondary"),
        "source_email": rich_color("accent"),
        "source_rss": rich_color("success"),
        "source_web": rich_color("primary"),
        "url": rich_color("accent"),
        "default": rich_color("foreground"),
        "level_debug": rich_color("foreground-muted"),
        "level_info": rich_color("foreground"),
        "level_warning": rich_color("warning"),
        "level_error": rich_color("error"),
        "level_success": rich_color("success"),
        "level_job": rich_color("primary"),
        "level_critical": to_rich_color(
            generated.get("error-lighten-1", generated["error"])
        ),
        "bracket": rich_color("foreground-muted"),
        "punctuation": rich_color("foreground-muted"),
    }


def build_config_style_palette(theme: Theme) -> dict[str, str]:
    """Build semantic styles for ConfigPreview from a Textual theme."""
    generated = theme.to_color_system().generate()
    return {
        "section_header": f"bold {to_rich_color(generated['primary'])}",
        "section_rule": to_rich_color(generated["foreground-muted"]),
        "key": to_rich_color(generated["foreground-muted"]),
        "bool_true": to_rich_color(generated["success"]),
        "bool_false": to_rich_color(generated["error"]),
        "sensitive": to_rich_color(generated["secondary"]),
        "number": to_rich_color(generated["accent"]),
        "value": to_rich_color(generated["foreground"]),
    }


def telemetry_state_style(owner: Any, state: str) -> str:
    colors = build_semantic_color_palette(get_active_theme(owner))
    state_lower = str(state or "").lower()
    if state_lower == "healthy":
        return colors["success"]
    if state_lower in {"working", "stale"}:
        return colors["warning_word"]
    if state_lower in {"error", "disabled"}:
        return colors["error_word" if state_lower == "error" else "timestamp"]
    return colors["default"]


def format_telemetry_metric(name: str, value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if name.endswith("_sec"):
            return f"{int(round(value))}s"
        if name.endswith("_ms"):
            return f"{int(round(value))}ms"
        if float(value).is_integer():
            return str(int(value))
        return f"{value:.2f}"
    return str(value)


def iter_telemetry_entries(
    snapshot: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    ordered: list[tuple[str, dict[str, Any]]] = []
    for key in TELEMETRY_SECTION_ORDER:
        value = snapshot.get(key)
        if isinstance(value, dict):
            ordered.append((key, value))
    for key, value in snapshot.items():
        if key in TELEMETRY_SECTION_ORDER or not isinstance(value, dict):
            continue
        ordered.append((str(key), value))
    return ordered


def normalize_source(source: Any) -> str:
    """Map incoming source strings into the normalized buckets."""
    if source is None:
        return "unknown"

    normalized = str(source).strip().lower()
    if not normalized:
        return "unknown"

    if "websocket" in normalized or normalized in ("ws", "socket"):
        return "websocket"
    if any(token in normalized for token in ("email", "imap", "mail")):
        return "email"
    if any(token in normalized for token in ("rss", "feed")):
        return "rss"
    if any(
        token in normalized for token in ("web", "http", "browser", "scrape", "website")
    ):
        return "website"
    return "unknown"


def coerce_positive_int(value: Any) -> int:
    """Best-effort conversion to positive int from numeric/text values."""
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        if not isinstance(value, str):
            return 0
        match = re.search(r"(\d+)", value)
        if not match:
            return 0
        try:
            parsed = int(match.group(1))
        except ValueError:
            return 0
    return parsed if parsed > 0 else 0


def coerce_positive_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed > 0 else 0.0


def derive_display_word_count(job: dict[str, Any]) -> int:
    """Derive a display word/unit count for tables."""
    for key in (
        "word_count",
        "words",
        "accepted_unit_count",
        "accepted_word_count",
        "unit_count",
        "unit",
        "units",
        "wordCount",
        "unitCount",
    ):
        count = coerce_positive_int(job.get(key))
        if count > 0:
            return count

    reward = coerce_positive_float(job.get("reward"))
    if reward <= 0:
        return 0

    tier_text = str(
        job.get("tier") or job.get("job_tier") or job.get("service_level") or ""
    ).lower()
    if not tier_text:
        title = str(job.get("title") or "")
        match = re.search(r"\(([^)]+)\)", title)
        if match:
            tier_text = match.group(1).strip().lower()

    normalized = tier_text.replace("-", "").replace("_", "").strip()
    if any(token in normalized for token in ("pro", "professional")):
        rate = TIER_UNIT_RATES["pro"]
    elif any(token in normalized for token in ("edit", "proofread", "proofreading")):
        rate = TIER_UNIT_RATES["edit"]
    else:
        rate = TIER_UNIT_RATES["standard"]

    return max(1, int(round(reward / rate)))


def parse_job_title_fallback(title: Any) -> tuple[str, str]:
    """Fallback parser for language pair and word count from job title."""
    default_pair = "??→??"
    default_words = "0"
    if not title:
        return default_pair, default_words

    text = str(title)
    pair_match = re.search(
        r"\b([A-Z]{2})\s*(?:→|->|-|>)\s*([A-Z]{2})\b", text, re.IGNORECASE
    )
    if pair_match:
        pair = f"{pair_match.group(1).upper()}→{pair_match.group(2).upper()}"
    else:
        pair = default_pair

    words_match = re.search(r"\b(\d{1,6})\s*words?\b", text, re.IGNORECASE)
    words = words_match.group(1) if words_match else default_words
    return pair, words
