from __future__ import annotations

import re
from typing import Any

LANG_PAIR_REGEX = re.compile(
    r"\b([A-Z]{2})\s*(?:→|->|(?<=\s)-(?=\s)|>)\s*([A-Z]{2})\b",
    re.IGNORECASE,
)
LANG_PAIR_SPLIT_REGEX = re.compile(r"\s*(?:→|->|(?<=\s)-(?=\s)|>|↔|/)\s*")
WORD_COUNT_REGEX = re.compile(r"\b(\d{1,6})\s*words?\b", re.IGNORECASE)
UNIT_COUNT_REGEX = re.compile(
    r"\b(\d{1,6})\s*(?:words?|chars?|units?)\b", re.IGNORECASE
)
TITLE_TIER_REGEX = re.compile(r"\(([^)]+)\)")
TIER_UNIT_RATES = {
    "standard": 0.02,
    "pro": 0.05,
    "edit": 0.01,
}


def normalize_meta(meta: Any) -> dict:
    if meta is None or not hasattr(meta, "get"):
        return {}
    return meta


def pick_meta_value(meta: dict, keys: list[str]):
    for key in keys:
        value = meta.get(key)
        if value:
            return value
    return None


def format_lang_token(token: str) -> str:
    if not token:
        return ""
    cleaned = "".join(ch for ch in str(token) if ch.isalpha())
    if not cleaned:
        return ""
    if len(cleaned) == 2:
        return cleaned.upper()
    return cleaned[:2].upper()


def normalize_lang_pair_string(value: Any) -> str:
    if not value:
        return ""
    candidate = str(value)
    parts = LANG_PAIR_SPLIT_REGEX.split(candidate)
    if len(parts) < 2:
        return ""
    left = format_lang_token(parts[0])
    right = format_lang_token(parts[1])
    if left and right:
        return f"{left}→{right}"
    return ""


def parse_lang_pair_from_title(title: Any) -> str:
    if not title:
        return ""
    text = str(title)
    primary = text.split("|")[0]
    match = LANG_PAIR_REGEX.search(primary)
    if match:
        return f"{match.group(1).upper()}→{match.group(2).upper()}"
    return normalize_lang_pair_string(primary)


def derive_lang_pair(title: Any, source_meta: Any) -> str:
    meta = normalize_meta(source_meta)
    for key in ("lang_pair", "language_pair"):
        normalized = normalize_lang_pair_string(meta.get(key))
        if normalized:
            return normalized

    src = pick_meta_value(meta, ["lc_src", "source_lang", "source_language", "source"])
    tgt = pick_meta_value(meta, ["lc_tgt", "target_lang", "target_language", "target"])
    if src and tgt:
        left = format_lang_token(src)
        right = format_lang_token(tgt)
        if left and right:
            return f"{left}→{right}"

    fallback = parse_lang_pair_from_title(title)
    return fallback or "??→??"


def coerce_positive_int(value: Any) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        if isinstance(value, str):
            match = re.search(r"(\d+)", value)
            if not match:
                return 0
            try:
                parsed = int(match.group(1))
            except ValueError:
                return 0
        else:
            return 0
    return parsed if parsed > 0 else 0


def coerce_positive_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed > 0 else 0.0


def resolve_tier_rate(tier_value: Any) -> float:
    if not tier_value:
        return 0.0
    normalized = str(tier_value).strip().lower().replace("-", "").replace("_", "")
    if normalized in ("standard", "std", "basic"):
        return TIER_UNIT_RATES["standard"]
    if normalized in ("pro", "professional"):
        return TIER_UNIT_RATES["pro"]
    if normalized in ("edit", "proofread", "proofreading"):
        return TIER_UNIT_RATES["edit"]
    return 0.0


def estimate_word_count_from_reward(reward: Any, title: Any, source_meta: Any) -> int:
    meta = normalize_meta(source_meta)
    reward_value = coerce_positive_float(reward)
    if reward_value <= 0:
        reward_value = coerce_positive_float(
            pick_meta_value(meta, ["rewards", "reward"])
        )
    if reward_value <= 0:
        return 0

    for key in (
        "reward_per_unit",
        "unit_reward",
        "unit_price",
        "price_per_unit",
        "rate_per_unit",
    ):
        rate = coerce_positive_float(meta.get(key))
        if rate > 0:
            return max(1, int(round(reward_value / rate)))

    tier = pick_meta_value(meta, ["tier", "job_tier", "service_level"])
    if not tier and title:
        match = TITLE_TIER_REGEX.search(str(title))
        if match:
            tier = match.group(1)

    rate = resolve_tier_rate(tier)
    if rate > 0:
        return max(1, int(round(reward_value / rate)))
    return 0


def derive_word_count(title: Any, source_meta: Any, reward: Any = 0.0) -> int:
    meta = normalize_meta(source_meta)
    for key in (
        "word_count",
        "words",
        "unit",
        "units",
        "unit_count",
        "wordCount",
        "unitCount",
    ):
        count = coerce_positive_int(meta.get(key))
        if count > 0:
            return count

    text = str(title) if title else ""
    match = WORD_COUNT_REGEX.search(text) or UNIT_COUNT_REGEX.search(text)
    if match:
        count = coerce_positive_int(match.group(1))
        if count > 0:
            return count

    return estimate_word_count_from_reward(reward, title, source_meta)
