"""Synchronous client for the Gengo translator Workbench HTTP API.

See ``docs/agents/gengo-workbench-api.md`` for the reconstructed contract. The
client authenticates with the ``myG_myGSession_`` cookie only; it never sends CSRF
headers or ``X-Requested-With``. Business errors arrive as HTTP 200 bodies, so every
response body is inspected before it is returned.

``submit_collection`` is irreversible on production Gengo: callers must have explicit
user approval (or the configured deadline auto-submit policy) before invoking it.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import requests

__all__ = [
    "CustomerComment",
    "GengoWorkbenchClient",
    "IncompleteCollection",
    "JobDetails",
    "UploadTarget",
    "WorkbenchUploadError",
    "WorkbenchCollection",
    "WorkbenchError",
    "WorkbenchExpiredError",
    "WorkbenchFileCollectionError",
    "WorkbenchJob",
    "WorkbenchSegment",
    "WorkbenchSessionDeadError",
    "WorkbenchValidationError",
    "extract_gengo_tags",
    "extract_triple_brackets",
    "parse_incomplete_collections",
    "parse_job_details",
    "validate_segment_preservation",
]

DEFAULT_BASE_URL = "https://gengo.com"
DEFAULT_TIMEOUT_SEC = 30.0
SESSION_COOKIE_NAME = "myG_myGSession_"
EXPIRED_ERROR_CODE = 3302
FILE_COLLECTION_ERROR_CODE = 3009
_MILLISECOND_EPOCH_THRESHOLD = 10_000_000_000
_ERROR_OPSTATS = frozenset({"error", "critical"})
_BODY_EXCERPT_CHARS = 200

_GENGO_TAG_RE = re.compile(r"\{/?\d+\}")
_TRIPLE_BRACKET_RE = re.compile(r"\[\[\[.*?\]\]\]", re.DOTALL)
_WS_RE = re.compile(r"\s+")
_DETAILS_PATH_RE = re.compile(r"/t/jobs/details/([A-Za-z0-9_-]{1,64})/?$")
_CID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_UNITS_RE = re.compile(
    r"(\d[\d,]*)\s*(?:chars?|characters?|words?|units?)\b", re.IGNORECASE
)
_HEADING_RE = re.compile(r"Collection\s*#\s*([A-Za-z0-9_-]+)\s*(?:-\s*(.*))?$")
_POSTED_RE = re.compile(r"^on\s+(.*?)\s+by\b", re.IGNORECASE)
_COMMENT_CLASSES = frozenset({"comment_continer", "comment_container"})
_TIER_ALIASES = {"standard": "std", "professional": "pro"}


class WorkbenchError(RuntimeError):
    """Base error for Workbench API failures, including HTTP-200 business errors."""

    def __init__(
        self,
        message: str = "",
        *,
        code: int | None = None,
        opstat: str | None = None,
        title: str = "",
        description: str = "",
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.opstat = opstat
        self.title = title
        self.description = description
        self.status_code = status_code
        super().__init__(message or self._default_message())

    def _default_message(self) -> str:
        parts = [part for part in (self.title, self.description) if part]
        text = ": ".join(parts) or "Gengo Workbench request failed"
        details = []
        if self.code is not None:
            details.append(f"code={self.code}")
        if self.opstat:
            details.append(f"opstat={self.opstat}")
        if self.status_code is not None:
            details.append(f"http={self.status_code}")
        return f"{text} ({', '.join(details)})" if details else text


class WorkbenchSessionDeadError(WorkbenchError):
    """The ``myG_myGSession_`` cookie is missing, expired, or rejected."""


class WorkbenchExpiredError(WorkbenchError):
    """The collection deadline has passed (Gengo code 3302)."""


class WorkbenchFileCollectionError(WorkbenchError):
    """The collection is file-based and has no workbench segments (code 3009)."""


class WorkbenchValidationError(WorkbenchError):
    """Local validation failed (tag/bracket parity, blank targets, QA errors)."""


class WorkbenchUploadError(WorkbenchError):
    """File upload failed on Gengo (status, error message, or non-JSON response)."""


@dataclass(frozen=True)
class WorkbenchSegment:
    segment_id: str
    job_id: str
    source_content: str
    target_content: str = ""
    last_author: str = ""
    has_errors: bool = False
    has_warnings: bool = False
    glossary: list[dict[str, Any]] = field(default_factory=list)
    matches: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkbenchJob:
    job_id: str
    unit_count: int
    reward: float
    status: str
    comment: str
    segments: list[WorkbenchSegment]
    source_files: list[dict[str, Any]] = field(default_factory=list)
    target_files: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkbenchCollection:
    collection_id: str
    order_id: str
    customer_id: str
    status: str
    lc_src: str
    lc_tgt: str
    tier: str
    purpose: str
    unit_count: int
    reward: float
    allotted_seconds: int
    seconds_left: int
    expire_time_epoch: float | None
    fetched_at: float
    last_page: int
    job_counts: dict[str, int]
    jobs: list[WorkbenchJob]
    summary: dict[str, Any]
    raw_pages: list[dict[str, Any]]

    @property
    def deadline_epoch(self) -> float | None:
        """Absolute deadline in epoch seconds, if Gengo reported one."""
        if self.expire_time_epoch is not None and self.expire_time_epoch > 0:
            return self.expire_time_epoch
        if self.seconds_left > 0:
            return self.fetched_at + self.seconds_left
        return None

    @property
    def all_segments(self) -> list[WorkbenchSegment]:
        return [segment for job in self.jobs for segment in job.segments]


@dataclass(frozen=True)
class IncompleteCollection:
    """One row of the translator dashboard's "Incomplete jobs" section."""

    collection_id: str
    title: str
    lang_pair: str
    tier: str
    unit_count: int
    reward: float
    url: str


@dataclass(frozen=True)
class CustomerComment:
    """A real comment on a job details page (activity lines excluded)."""

    comment_id: str
    author: str
    posted_at: str
    text: str
    links: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class UploadTarget:
    """Target upload configuration parsed from a details page."""

    job_id: str
    allowed_extensions: tuple[str, ...]
    action_url: str


@dataclass(frozen=True)
class JobDetails:
    """Parsed ``/t/jobs/details/{cid}`` page of an accepted collection."""

    collection_id: str
    title: str
    status: str
    unit_count: int
    reward: float
    source_download_urls: list[str]
    comments: list[CustomerComment]
    is_file_job: bool
    upload_targets: list[UploadTarget] = field(default_factory=list)


def extract_gengo_tags(text: str) -> Counter[str]:
    """Return the multiset of Gengo ``{n}`` / ``{/n}`` placeholder tags."""
    return Counter(_GENGO_TAG_RE.findall(text or ""))


def extract_triple_brackets(text: str) -> Counter[str]:
    """Return the multiset of ``[[[...]]]`` do-not-translate spans."""
    return Counter(_TRIPLE_BRACKET_RE.findall(text or ""))


def _format_counter(values: Counter[str]) -> str:
    return ", ".join(
        item if count == 1 else f"{item} x{count}"
        for item, count in sorted(values.items())
    )


def validate_segment_preservation(source: str, target: str) -> list[str]:
    """Return human-readable preservation errors; an empty list means valid."""
    source = source or ""
    target = target or ""
    errors: list[str] = []

    source_tags = extract_gengo_tags(source)
    target_tags = extract_gengo_tags(target)
    if source_tags != target_tags:
        missing = source_tags - target_tags
        extra = target_tags - source_tags
        if missing:
            errors.append(f"missing tags: {_format_counter(missing)}")
        if extra:
            errors.append(f"unexpected tags: {_format_counter(extra)}")

    source_spans = extract_triple_brackets(source)
    target_spans = extract_triple_brackets(target)
    if source_spans != target_spans:
        missing = source_spans - target_spans
        extra = target_spans - source_spans
        if missing:
            errors.append(
                f"missing or altered [[[...]]] spans: {_format_counter(missing)}"
            )
        if extra:
            errors.append(f"unexpected [[[...]]] spans: {_format_counter(extra)}")

    if source.strip() and not target.strip():
        errors.append("target is blank but source is not")
    return errors


def _coerce_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_epoch(value: Any) -> float | None:
    """Normalize a Gengo timestamp (seconds or milliseconds) to epoch seconds."""
    epoch = _coerce_float(value, 0.0)
    if epoch <= 0:
        return None
    if epoch > _MILLISECOND_EPOCH_THRESHOLD:
        epoch /= 1000.0
    return epoch


def _str_field(value: Any) -> str:
    return "" if value is None else str(value)


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _looks_like_login_page(text: str) -> bool:
    lowered = text.lower()
    return "/auth/" in lowered or "login" in lowered or "sign in" in lowered


def _parse_segment(raw: Mapping[str, Any], job_id: str) -> WorkbenchSegment:
    return WorkbenchSegment(
        segment_id=_str_field(raw.get("segment_id")),
        job_id=job_id,
        source_content=_str_field(raw.get("source_content")),
        target_content=_str_field(raw.get("target_content")),
        last_author=_str_field(raw.get("last_author")),
        has_errors=bool(raw.get("hasErrors", raw.get("has_errors", False))),
        has_warnings=bool(raw.get("hasWarnings", raw.get("has_warnings", False))),
        glossary=_dict_list(raw.get("glossary")),
        matches=_dict_list(raw.get("matches")),
        raw=dict(raw),
    )


def _parse_job(
    raw: Mapping[str, Any], segments: list[WorkbenchSegment]
) -> WorkbenchJob:
    return WorkbenchJob(
        job_id=_str_field(raw.get("id")),
        unit_count=_coerce_int(raw.get("unit_count")),
        reward=_coerce_float(raw.get("reward")),
        status=_str_field(raw.get("status")),
        comment=_str_field(raw.get("comment")),
        segments=segments,
        source_files=_dict_list(raw.get("source_files")),
        target_files=_dict_list(raw.get("target_files")),
        raw=dict(raw),
    )


def _config_value(config: Any, section: str, key: str, fallback: Any) -> Any:
    """Read ``[section] key`` from an AppConfig-like object or nested mapping."""
    if config is None:
        return fallback
    if isinstance(config, Mapping):
        values = config.get(section)
        if not isinstance(values, Mapping):
            return fallback
        value = values.get(key, fallback)
    else:
        getter = getattr(config, "get", None)
        if getter is None:
            return fallback
        try:
            value = getter(section, key, fallback=fallback)
        except (KeyError, TypeError, ValueError):
            return fallback
    if value is None or (isinstance(value, str) and not value.strip()):
        return fallback
    return value


# ------------------------------------------------------------- HTML pages


def _collapse(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def _classes(attrs: Sequence[tuple[str, str | None]]) -> set[str]:
    for key, value in attrs:
        if key == "class" and value:
            return set(value.split())
    return set()


def _attr(attrs: Sequence[tuple[str, str | None]], name: str) -> str:
    for key, value in attrs:
        if key == name and value is not None:
            return value.strip()
    return ""


def _first_number(text: str) -> str:
    match = _NUMBER_RE.search(text or "")
    return match.group(0).replace(",", "") if match else ""


def _same_origin(url: str, base_url: str) -> bool:
    parts, base = urlsplit(url), urlsplit(base_url)
    return (
        parts.scheme in {"http", "https"}
        and parts.scheme == base.scheme
        and parts.netloc.lower() == base.netloc.lower()
    )


class _DashboardParser(HTMLParser):
    """Collect ``tr.td-list-row`` rows under the "Incomplete jobs" heading."""

    _COLUMNS = {
        "td-list-column-tier": "tier",
        "td-list-column-langs": "langs",
        "td-list-column-content": "content",
        "td-list-column-unitcount": "units",
        "td-list-column-reward": "reward",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.section = ""
        self.rows: list[dict[str, Any]] = []
        self._heading: list[str] | None = None
        self._row: dict[str, Any] | None = None
        self._column: str | None = None

    def _in_incomplete(self) -> bool:
        return self.section.startswith("incomplete jobs")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = _classes(attrs)
        if tag == "h2" and "td-list-head-label" in classes:
            self._heading = []
            return
        if not self._in_incomplete():
            return
        if tag == "tr" and "td-list-row" in classes:
            self._row = {
                "id": _attr(attrs, "data-id"),
                "url": _attr(attrs, "data-detail-url"),
                "hrefs": [],
                **{name: [] for name in self._COLUMNS.values()},
            }
            self._column = None
        elif self._row is not None:
            if tag == "td":
                self._column = next(
                    (name for cls, name in self._COLUMNS.items() if cls in classes),
                    None,
                )
            elif tag == "a" and _attr(attrs, "href"):
                self._row["hrefs"].append(_attr(attrs, "href"))

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self._heading is not None:
            self.section = _collapse("".join(self._heading)).lower()
            self._heading = None
            self._row = None
        elif tag == "td":
            self._column = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._column = None

    def handle_data(self, data: str) -> None:
        if self._heading is not None:
            self._heading.append(data)
        elif self._row is not None and self._column is not None:
            self._row[self._column].append(data)


def _row_collection_id(row: Mapping[str, Any]) -> str:
    candidates = [str(row.get("id") or "")]
    for href in [row.get("url") or "", *row.get("hrefs", [])]:
        match = _DETAILS_PATH_RE.search(urlsplit(str(href)).path)
        if match:
            candidates.append(match.group(1))
    return next((cid for cid in candidates if _CID_RE.match(cid)), "")


def parse_incomplete_collections(
    html_text: str, base_url: str = DEFAULT_BASE_URL
) -> list[IncompleteCollection]:
    """Parse the dashboard's "Incomplete jobs" table (missing section -> [])."""
    parser = _DashboardParser()
    parser.feed(html_text or "")
    parser.close()
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    result: list[IncompleteCollection] = []
    seen: set[str] = set()
    for row in parser.rows:
        cid = _row_collection_id(row)
        if not cid or cid in seen:
            continue
        seen.add(cid)
        tier = _collapse("".join(row["tier"])).lower()
        result.append(
            IncompleteCollection(
                collection_id=cid,
                title=_collapse("".join(row["content"])),
                lang_pair=_collapse("".join(row["langs"])),
                tier=_TIER_ALIASES.get(tier, tier),
                unit_count=_coerce_int(_first_number("".join(row["units"]))),
                reward=_coerce_float(_first_number("".join(row["reward"]))),
                url=f"{base}/t/jobs/details/{cid}",
            )
        )
    return result


class _DetailsParser(HTMLParser):
    """Extract heading, order summary, links and comments from a details page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.heading: str | None = None
        self.title: str | None = None
        self.units_text: str | None = None
        self.price_text: str | None = None
        self.hrefs: list[str] = []
        self.comments: list[dict[str, Any]] = []
        self._capture: str | None = None
        self._capture_tag = ""
        self._buffer: list[str] = []
        self._div_depth = 0
        self._basic_info_depth = 0
        self._ol_depth = 0
        self._comments_ol_depth = 0
        self._li_depth = 0
        self._comment: dict[str, Any] | None = None
        self._in_meta = False
        self._in_author = False

    # Single-field captures (h1, title h3, units line, price) -------------

    def _start_capture(self, name: str, tag: str) -> None:
        self._capture, self._capture_tag, self._buffer = name, tag, []

    def _finish_capture(self) -> None:
        value = _collapse("".join(self._buffer))
        setattr(self, self._capture or "", value)
        self._capture = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = _classes(attrs)
        if tag == "div":
            self._div_depth += 1
            if "basic-info" in classes and self.title is None:
                self._basic_info_depth = self._div_depth
        elif tag == "ol":
            self._ol_depth += 1
            if "comments-list" in classes and not self._comments_ol_depth:
                self._comments_ol_depth = self._ol_depth
        elif tag == "li" and self._comments_ol_depth:
            self._li_depth += 1
            if self._li_depth == 1 and classes & _COMMENT_CLASSES:
                comment_id = _attr(attrs, "id").removeprefix("comment-")
                self._comment = {
                    "id": comment_id,
                    "meta": [],
                    "author": [],
                    "body": [],
                    "links": [],
                }
        if self._comment is not None:
            self._comment_start(tag, attrs, classes)
            return
        if self._capture is not None:
            return
        if tag == "h1" and self.heading is None:
            self._start_capture("heading", tag)
        elif self._basic_info_depth:
            if tag == "h3" and self.title is None:
                self._start_capture("title", tag)
            elif tag == "p" and "line2" in classes and self.units_text is None:
                self._start_capture("units_text", tag)
        if tag == "span" and "price" in classes and self.price_text is None:
            self._start_capture("price_text", tag)
        if tag == "a" and not self._comments_ol_depth and _attr(attrs, "href"):
            self.hrefs.append(_attr(attrs, "href"))

    def _comment_start(
        self, tag: str, attrs: list[tuple[str, str | None]], classes: set[str]
    ) -> None:
        comment = self._comment
        assert comment is not None
        if tag == "p" and "comment_meta" in classes:
            self._in_meta = True
        elif tag == "span" and "comment-name" in classes:
            self._in_author = True
        elif tag == "br" and not self._in_meta:
            comment["body"].append("\n")
        elif tag == "a":
            href = _attr(attrs, "href")
            if href and not href.startswith(("#", "javascript:")):
                comment["links"].append(href)

    def handle_endtag(self, tag: str) -> None:
        if self._capture is not None and tag == self._capture_tag:
            self._finish_capture()
        if tag == "div":
            if self._div_depth == self._basic_info_depth:
                self._basic_info_depth = 0
            self._div_depth = max(0, self._div_depth - 1)
        elif tag == "ol":
            if self._ol_depth == self._comments_ol_depth:
                self._comments_ol_depth = 0
                self._li_depth = 0
                self._finish_comment()
            self._ol_depth = max(0, self._ol_depth - 1)
        elif tag == "li" and self._comments_ol_depth:
            if self._li_depth == 1:
                self._finish_comment()
            self._li_depth = max(0, self._li_depth - 1)
        elif self._comment is not None:
            if tag == "p":
                if self._in_meta:
                    self._in_meta = False
                else:
                    self._comment["body"].append("\n")
            elif tag == "span":
                self._in_author = False

    def handle_data(self, data: str) -> None:
        if self._comment is not None:
            if self._in_author:
                self._comment["author"].append(data)
            if self._in_meta:
                self._comment["meta"].append(data)
            else:
                self._comment["body"].append(_WS_RE.sub(" ", data))
        elif self._capture is not None:
            self._buffer.append(data)

    def _finish_comment(self) -> None:
        if self._comment is not None:
            self.comments.append(self._comment)
        self._comment = None
        self._in_meta = self._in_author = False


def _comment_text(parts: Sequence[str]) -> str:
    lines = [line.strip() for line in "".join(parts).split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _parse_upload_targets(
    html_text: str, base_url: str = DEFAULT_BASE_URL
) -> list[UploadTarget]:
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    targets: list[UploadTarget] = []
    pattern = re.compile(r"new\s+qq\.FileUploader\s*\(\s*\{")
    for m in pattern.finditer(html_text or ""):
        start = m.end() - 1
        depth = 0
        in_string: str | None = None
        escape = False
        end = -1
        for i in range(start, len(html_text)):
            c = html_text[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if in_string:
                if c == in_string:
                    in_string = None
                continue
            if c in ('"', "'"):
                in_string = c
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end == -1:
            continue
        body = html_text[start:end]
        job_m = re.search(r'["\']job_id["\']\s*:\s*["\']([^"\']+)["\']', body)
        action_m = re.search(r'action\s*:\s*["\']([^"\']+)["\']', body)
        if not (job_m and action_m):
            continue
        job_id = job_m.group(1).strip()
        action_raw = action_m.group(1).strip()
        action_abs = urljoin(base + "/", action_raw)
        parts = urlsplit(action_abs)

        valid_origin = _same_origin(action_abs, base) or _same_origin(
            action_raw, DEFAULT_BASE_URL
        )
        if not (valid_origin and parts.path.rstrip("/") == "/t/ajax/upload_file"):
            continue

        normalized_action = (
            action_abs
            if _same_origin(action_abs, base)
            else urljoin(base + "/", parts.path)
        )
        exts_m = re.search(r"allowedExtensions\s*:\s*\[([^\]]*)\]", body)
        exts: list[str] = []
        if exts_m:
            for item in exts_m.group(1).split(","):
                cleaned = item.strip().strip("'\"").lstrip(".")
                if cleaned:
                    exts.append(cleaned.lower())

        targets.append(
            UploadTarget(
                job_id=job_id,
                allowed_extensions=tuple(exts),
                action_url=normalized_action,
            )
        )
    return targets


def parse_job_details(
    html_text: str, collection_id: str | int, base_url: str = DEFAULT_BASE_URL
) -> JobDetails:
    """Parse a job details page; missing pieces become empty/zero values."""
    parser = _DetailsParser()
    parser.feed(html_text or "")
    parser.close()
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    status = ""
    match = _HEADING_RE.search(parser.heading or "")
    if match:
        status = (match.group(2) or "").strip()

    downloads: list[str] = []
    for href in parser.hrefs:
        absolute = urljoin(base + "/", href)
        if _same_origin(absolute, base) and urlsplit(absolute).path.startswith(
            "/download/source/"
        ):
            downloads.append(absolute)
    downloads = list(dict.fromkeys(downloads))

    comments: list[CustomerComment] = []
    for raw in parser.comments:
        author = _collapse("".join(raw["author"]))
        meta = _collapse("".join(raw["meta"]))
        posted = _POSTED_RE.search(meta)
        links = [urljoin(base + "/", href) for href in raw["links"]]
        comments.append(
            CustomerComment(
                comment_id=str(raw["id"]),
                author=author,
                posted_at=posted.group(1).strip() if posted else "",
                text=_comment_text(raw["body"]),
                links=list(dict.fromkeys(links)),
            )
        )

    units_match = _UNITS_RE.search(parser.units_text or "")
    units = (
        units_match.group(1).replace(",", "")
        if units_match
        else _first_number(parser.units_text or "")
    )
    upload_targets = _parse_upload_targets(html_text or "", base)
    return JobDetails(
        collection_id=str(collection_id),
        title=(parser.title or "").strip(),
        status=status,
        unit_count=_coerce_int(units),
        reward=_coerce_float(_first_number(parser.price_text or "")),
        source_download_urls=downloads,
        comments=comments,
        is_file_job=bool(downloads or upload_targets),
        upload_targets=upload_targets,
    )


class GengoWorkbenchClient:
    """Cookie-authenticated client for ``/t/workbench/collection/*`` endpoints."""

    def __init__(
        self,
        *,
        user_session: str,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str = "",
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        session: requests.Session | None = None,
    ) -> None:
        self._user_session = (user_session or "").strip()
        self.base_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        self.user_agent = (user_agent or "").strip()
        self.timeout_sec = timeout_sec if timeout_sec > 0 else DEFAULT_TIMEOUT_SEC
        self._owns_session = session is None
        self._session = session if session is not None else requests.Session()
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(base_url={self.base_url!r}, "
            f"has_session={bool(self._user_session)})"
        )

    @classmethod
    def from_config(
        cls, config: Any, *, session: requests.Session | None = None
    ) -> GengoWorkbenchClient:
        user_session = str(_config_value(config, "WebSocket", "user_session", ""))
        if not user_session.strip():
            user_session = os.environ.get("GENGO_USER_SESSION", "")
        user_agent = str(
            _config_value(config, "Network", "browser_user_agent", "") or ""
        )
        base_url = str(
            _config_value(config, "JobPipeline", "workbench_base_url", "")
            or _config_value(config, "BrowserWorker", "sandbox_origin", "")
            or DEFAULT_BASE_URL
        )
        timeout_sec = _coerce_float(
            _config_value(
                config, "JobPipeline", "workbench_timeout_sec", DEFAULT_TIMEOUT_SEC
            ),
            DEFAULT_TIMEOUT_SEC,
        )
        return cls(
            user_session=user_session,
            base_url=base_url,
            user_agent=user_agent,
            timeout_sec=timeout_sec,
            session=session,
        )

    @property
    def has_session(self) -> bool:
        return bool(self._user_session)

    def close(self) -> None:
        """Close the underlying HTTP session if this client created it."""
        if self._owns_session:
            with self._lock:
                self._session.close()

    def __enter__(self) -> GengoWorkbenchClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------ HTTP

    def _headers(self, collection_id: str, *, post: bool) -> dict[str, str]:
        headers = {
            "Cookie": f"{SESSION_COOKIE_NAME}={self._user_session}",
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{self.base_url}/t/workbench/{collection_id}",
        }
        if post:
            headers["Origin"] = self.base_url
            headers["Content-Type"] = "application/json;charset=utf-8"
        if self.user_agent:
            headers["User-Agent"] = self.user_agent
        return headers

    def _request(
        self,
        method: str,
        path: str,
        collection_id: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
    ) -> dict[str, Any]:
        if not self._user_session:
            raise WorkbenchSessionDeadError(
                "No Gengo user_session configured ([WebSocket] user_session)",
                title="Missing session",
            )
        post = method.upper() == "POST"
        try:
            with self._lock:
                response = self._session.request(
                    method.upper(),
                    f"{self.base_url}{path}",
                    params=dict(params) if params else None,
                    json=json_body if post else None,
                    headers=self._headers(collection_id, post=post),
                    timeout=self.timeout_sec,
                    allow_redirects=False,
                )
        except requests.RequestException as exc:
            raise WorkbenchError(
                f"Gengo Workbench request failed: {type(exc).__name__}: {exc}",
                title="Request failed",
                description=str(exc),
            ) from exc
        return self._unwrap_json(response, collection_id)

    def _unwrap_json(
        self, response: requests.Response, collection_id: str | int
    ) -> dict[str, Any]:
        status = response.status_code
        if 300 <= status < 400:
            location = response.headers.get("Location", "")
            if "/auth/" in location or "/login" in location:
                raise WorkbenchSessionDeadError(
                    f"Gengo session rejected for collection {collection_id}: "
                    f"redirected to {location}",
                    title="Session expired",
                    status_code=status,
                )
            raise WorkbenchError(
                f"Unexpected redirect for collection {collection_id} to "
                f"{location or '<no location>'}",
                title="Unexpected redirect",
                status_code=status,
            )
        if status in {401, 403}:
            raise WorkbenchSessionDeadError(
                f"Gengo session rejected for collection {collection_id} "
                f"(HTTP {status})",
                title="Session rejected",
                status_code=status,
            )
        if status >= 400:
            description = response.text[:_BODY_EXCERPT_CHARS]
            try:
                body = response.json()
            except ValueError:
                body = None
            if isinstance(body, Mapping) and body.get("detail"):
                description = str(body["detail"])
            raise WorkbenchError(
                title=f"HTTP {status}",
                description=description,
                status_code=status,
            )
        try:
            body = response.json()
        except ValueError as exc:
            text = response.text or ""
            if _looks_like_login_page(text):
                raise WorkbenchSessionDeadError(
                    f"Gengo returned a login page for collection {collection_id}",
                    title="Session expired",
                    status_code=status,
                ) from exc
            raise WorkbenchError(
                title="Invalid JSON response",
                description=text[:_BODY_EXCERPT_CHARS],
                status_code=status,
            ) from exc
        if not isinstance(body, dict):
            raise WorkbenchError(
                title="Unexpected response payload",
                description=f"expected JSON object, got {type(body).__name__}",
                status_code=status,
            )

        opstat = body.get("opstat")
        opstat = str(opstat).lower() if opstat is not None else None
        raw_code = body.get("code")
        code = _coerce_int(raw_code, 0) if raw_code is not None else None
        title = _str_field(body.get("title"))
        error_kwargs: dict[str, Any] = {
            "code": code,
            "opstat": opstat,
            "title": title,
            "description": _str_field(body.get("description")),
            "status_code": status,
        }
        if code == EXPIRED_ERROR_CODE or (
            opstat == "critical" and "expired" in title.lower()
        ):
            raise WorkbenchExpiredError(**error_kwargs)
        if code == FILE_COLLECTION_ERROR_CODE:
            raise WorkbenchFileCollectionError(**error_kwargs)
        if opstat in _ERROR_OPSTATS:
            raise WorkbenchError(**error_kwargs)
        return body

    # --------------------------------------------------------------- Methods

    def fetch_collection(
        self, collection_id: str | int, *, max_pages: int = 20
    ) -> WorkbenchCollection:
        """Fetch every batch of a collection and merge jobs/segments in order."""
        cid = str(collection_id)
        path = f"/t/workbench/collection/{cid}"
        fetched_at = time.time()
        first = self._request("GET", path, cid, params={"page": 1})
        pagination = first.get("pagination")
        last = _coerce_int(
            pagination.get("last") if isinstance(pagination, Mapping) else None, 1
        )
        last = max(1, min(last, max(1, int(max_pages))))

        pages = [first]
        for page in range(2, last + 1):
            pages.append(self._request("GET", path, cid, params={"page": page}))

        job_raws: dict[str, Mapping[str, Any]] = {}
        job_segments: dict[str, list[WorkbenchSegment]] = {}
        seen_segments: dict[str, set[str]] = {}
        for payload in pages:
            jobs = payload.get("jobs")
            if not isinstance(jobs, list):
                continue
            for raw_job in jobs:
                if not isinstance(raw_job, Mapping):
                    continue
                job_id = _str_field(raw_job.get("id"))
                job_raws.setdefault(job_id, raw_job)
                segments = job_segments.setdefault(job_id, [])
                seen = seen_segments.setdefault(job_id, set())
                raw_segments = raw_job.get("segments")
                if not isinstance(raw_segments, list):
                    continue
                for raw_segment in raw_segments:
                    if not isinstance(raw_segment, Mapping):
                        continue
                    segment = _parse_segment(raw_segment, job_id)
                    if segment.segment_id in seen:
                        continue
                    seen.add(segment.segment_id)
                    segments.append(segment)

        jobs_list = [
            _parse_job(raw_job, job_segments[job_id])
            for job_id, raw_job in job_raws.items()
        ]
        summary_raw = first.get("summary")
        summary = dict(summary_raw) if isinstance(summary_raw, Mapping) else {}
        job_counts_raw = summary.get("job_counts")
        job_counts = (
            {str(key): _coerce_int(value) for key, value in job_counts_raw.items()}
            if isinstance(job_counts_raw, Mapping)
            else {}
        )
        reward = (
            _coerce_float(summary["rewards_total"])
            if "rewards_total" in summary
            else sum(job.reward for job in jobs_list)
        )
        return WorkbenchCollection(
            collection_id=cid,
            order_id=_str_field(summary.get("order_id")),
            customer_id=_str_field(summary.get("customer_id")),
            status=_str_field(summary.get("status")),
            lc_src=_str_field(summary.get("lc_src")),
            lc_tgt=_str_field(summary.get("lc_tgt")),
            tier=_str_field(summary.get("tier")),
            purpose=_str_field(summary.get("purpose")),
            unit_count=_coerce_int(summary.get("unit_count")),
            reward=reward,
            allotted_seconds=_coerce_int(summary.get("allotted_seconds")),
            seconds_left=_coerce_int(summary.get("seconds_left")),
            expire_time_epoch=_normalize_epoch(summary.get("expire_time")),
            fetched_at=fetched_at,
            last_page=last,
            job_counts=job_counts,
            jobs=jobs_list,
            summary=summary,
            raw_pages=pages,
        )

    def get_status(self, collection_id: str | int) -> dict[str, Any]:
        """Return the live collection summary with normalized deadline fields."""
        cid = str(collection_id)
        body = self._request("GET", f"/t/workbench/collection/{cid}/status", cid)
        wrapped = body.get("summary")
        summary = dict(wrapped) if isinstance(wrapped, Mapping) else dict(body)
        summary["expire_time_epoch"] = _normalize_epoch(
            summary.get("expire_time", summary.get("expire_time_epoch"))
        )
        summary["seconds_left"] = _coerce_int(summary.get("seconds_left"))
        return summary

    def save_segments(
        self,
        collection_id: str | int,
        jobs_segments: Mapping[str | int, Sequence[Mapping[str, Any]]],
        *,
        validate_against: WorkbenchCollection | None = None,
    ) -> dict[str, Any]:
        """Stage translations via ``/save`` (reversible; does not submit)."""
        cid = str(collection_id)
        if validate_against is not None:
            sources = {
                (segment.job_id, segment.segment_id): segment.source_content
                for segment in validate_against.all_segments
            }
            errors: list[str] = []
            for job_id, segments in jobs_segments.items():
                for item in segments:
                    segment_id = str(item["segment_id"])
                    label = f"job {job_id} segment {segment_id}"
                    source = sources.get((str(job_id), segment_id))
                    if source is None:
                        errors.append(f"{label}: not found in collection {cid}")
                        continue
                    errors.extend(
                        f"{label}: {error}"
                        for error in validate_segment_preservation(
                            source, str(item["target_content"])
                        )
                    )
            if errors:
                raise WorkbenchValidationError(
                    f"Segment validation failed for collection {cid}: "
                    + "; ".join(errors),
                    title="Segment validation failed",
                    description="\n".join(errors),
                )

        payload = {
            "jobs": [
                {
                    "id": int(job_id) if str(job_id).isdigit() else str(job_id),
                    "segments": [
                        {
                            "segment_id": str(item["segment_id"]),
                            "target_content": str(item["target_content"]),
                        }
                        for item in segments
                    ],
                }
                for job_id, segments in jobs_segments.items()
            ]
        }
        return self._request(
            "POST", f"/t/workbench/collection/{cid}/save", cid, json_body=payload
        )

    def submit_collection(
        self, collection_id: str | int, *, last_page: int = 1
    ) -> dict[str, Any]:
        """Submit the collection. Irreversible on production Gengo."""
        cid = str(collection_id)
        return self._request(
            "POST",
            f"/t/workbench/collection/{cid}/submit",
            cid,
            json_body={"page": int(last_page) + 1},
        )

    def download_file(
        self, collection_id: str | int, url: str, *, max_bytes: int
    ) -> tuple[bytes, str]:
        """Download a collection source file with the session cookie.

        ``url`` must be absolute; the caller is responsible for restricting it to
        trusted Gengo origins. Returns ``(content, content_disposition)``.
        """
        if not self._user_session:
            raise WorkbenchSessionDeadError(
                "No Gengo user_session configured ([WebSocket] user_session)",
                title="Missing session",
            )
        cid = str(collection_id)
        try:
            with self._lock:
                response = self._session.get(
                    url,
                    headers=self._headers(cid, post=False),
                    timeout=self.timeout_sec,
                    allow_redirects=False,
                    stream=True,
                )
                try:
                    status = response.status_code
                    location = response.headers.get("Location", "")
                    if 300 <= status < 400 and (
                        "/auth/" in location or "/login" in location
                    ):
                        raise WorkbenchSessionDeadError(
                            "Gengo session expired (redirected to login)",
                            title="Session dead",
                            status_code=status,
                        )
                    if status in (401, 403):
                        raise WorkbenchSessionDeadError(
                            f"Gengo rejected the session (HTTP {status})",
                            title="Session dead",
                            status_code=status,
                        )
                    if status != 200:
                        raise WorkbenchError(
                            f"Source file download failed (HTTP {status})",
                            title="Download failed",
                            status_code=status,
                        )
                    content = bytearray()
                    for chunk in response.iter_content(64 * 1024):
                        content.extend(chunk)
                        if len(content) > max_bytes:
                            raise WorkbenchError(
                                "Source file exceeds download limit",
                                title="Download too large",
                            )
                    disposition = response.headers.get("Content-Disposition", "")
                finally:
                    response.close()
        except requests.RequestException as exc:
            raise WorkbenchError(
                f"Source file download failed: {type(exc).__name__}: {exc}",
                title="Request failed",
                description=str(exc),
            ) from exc
        return bytes(content), disposition

    # ------------------------------------------------------------ HTML pages

    def _get_html(self, path: str) -> str:
        """GET a translator HTML page without following redirects."""
        if not self._user_session:
            raise WorkbenchSessionDeadError(
                "No Gengo user_session configured ([WebSocket] user_session)",
                title="Missing session",
            )
        headers = {
            "Cookie": f"{SESSION_COOKIE_NAME}={self._user_session}",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Referer": f"{self.base_url}/t/dashboard",
        }
        if self.user_agent:
            headers["User-Agent"] = self.user_agent
        try:
            with self._lock:
                response = self._session.get(
                    f"{self.base_url}{path}",
                    headers=headers,
                    timeout=self.timeout_sec,
                    allow_redirects=False,
                )
        except requests.RequestException as exc:
            raise WorkbenchError(
                f"Gengo page request failed: {type(exc).__name__}: {exc}",
                title="Request failed",
                description=str(exc),
            ) from exc
        status = response.status_code
        if 300 <= status < 400:
            location = response.headers.get("Location", "")
            if "/auth" in location or "/login" in location:
                raise WorkbenchSessionDeadError(
                    f"Gengo session rejected for {path}: redirected to {location}",
                    title="Session expired",
                    status_code=status,
                )
            raise WorkbenchError(
                f"Unexpected redirect for {path} to {location or '<no location>'}",
                title="Unexpected redirect",
                status_code=status,
            )
        if status in {401, 403}:
            raise WorkbenchSessionDeadError(
                f"Gengo session rejected for {path} (HTTP {status})",
                title="Session rejected",
                status_code=status,
            )
        if status != 200:
            raise WorkbenchError(
                f"Gengo page {path} failed (HTTP {status})",
                title=f"HTTP {status}",
                status_code=status,
            )
        content_type = response.headers.get("Content-Type", "").lower()
        if "charset=" in content_type:
            return response.text
        # requests assumes ISO-8859-1 for charset-less text/html; Gengo is UTF-8.
        return response.content.decode("utf-8", errors="replace")

    def list_incomplete_collections(self) -> list[IncompleteCollection]:
        """Return the dashboard's "Incomplete jobs" (accepted, in progress)."""
        return parse_incomplete_collections(
            self._get_html("/t/dashboard"), self.base_url
        )

    def fetch_job_details(self, collection_id: str | int) -> JobDetails:
        """Fetch and parse ``/t/jobs/details/{cid}`` (title, files, comments)."""
        cid = str(collection_id).strip()
        if not _CID_RE.match(cid):
            raise WorkbenchError(f"Invalid collection id: {collection_id!r}")
        return parse_job_details(
            self._get_html(f"/t/jobs/details/{cid}"), cid, self.base_url
        )

    def upload_translated_file(
        self,
        target: UploadTarget,
        path: Path | str,
        *,
        collection_id: str | int = "",
    ) -> dict[str, Any]:
        """Upload a translated file to Gengo, submitting the job directly."""
        if not self._user_session:
            raise WorkbenchSessionDeadError(
                "No Gengo user_session configured ([WebSocket] user_session)",
                title="Missing session",
            )
        file_path = Path(path)
        if not file_path.is_file():
            raise WorkbenchUploadError(
                f"Upload file not found: {file_path}",
                title="File not found",
            )
        ext = file_path.suffix.lstrip(".").lower()
        if target.allowed_extensions and ext not in tuple(
            e.lower() for e in target.allowed_extensions
        ):
            raise WorkbenchUploadError(
                f"File extension .{ext} not in allowed extensions "
                f"{target.allowed_extensions}",
                title="Invalid extension",
            )
        size = file_path.stat().st_size
        max_size = 100 * 1024 * 1024
        if size > max_size:
            raise WorkbenchUploadError(
                f"File {file_path.name} exceeds maximum 100MB ({size} bytes)",
                title="File too large",
            )
        file_bytes = file_path.read_bytes()

        cid_str = str(collection_id).strip()
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-File-Name": quote(file_path.name),
            "Content-Type": "application/octet-stream",
            "Origin": self.base_url,
        }
        if cid_str:
            headers["Referer"] = f"{self.base_url}/t/jobs/details/{cid_str}"
        if self.user_agent:
            headers["User-Agent"] = self.user_agent

        params = {
            "job_id": target.job_id,
            "valums": "true",
            "qqfile": file_path.name,
        }

        try:
            with self._lock:
                response = self._session.request(
                    "POST",
                    target.action_url,
                    params=params,
                    data=file_bytes,
                    headers=headers,
                    timeout=self.timeout_sec,
                    allow_redirects=False,
                )
        except requests.RequestException as exc:
            raise WorkbenchUploadError(
                f"Gengo upload request failed for job {target.job_id}: "
                f"{type(exc).__name__}: {exc}",
                title="Upload request failed",
                description=str(exc),
            ) from exc

        status = response.status_code
        if 300 <= status < 400:
            location = response.headers.get("Location", "")
            if "/auth/" in location or "/login" in location:
                raise WorkbenchSessionDeadError(
                    f"Gengo session rejected during upload: redirected to {location}",
                    title="Session expired",
                    status_code=status,
                )
            raise WorkbenchUploadError(
                f"Unexpected redirect during upload to {location or '<no location>'}",
                title="Unexpected redirect",
                status_code=status,
            )
        if status in {401, 403}:
            raise WorkbenchSessionDeadError(
                f"Gengo session rejected during upload (HTTP {status})",
                title="Session rejected",
                status_code=status,
            )
        if status >= 400:
            raise WorkbenchUploadError(
                f"Upload HTTP {status} error for job {target.job_id}",
                title=f"HTTP {status}",
                description=response.text[:_BODY_EXCERPT_CHARS],
                status_code=status,
            )

        try:
            body = response.json()
        except ValueError as exc:
            text = response.text or ""
            if _looks_like_login_page(text):
                raise WorkbenchSessionDeadError(
                    "Gengo returned a login page during upload for job "
                    f"{target.job_id}",
                    title="Session expired",
                    status_code=status,
                ) from exc
            raise WorkbenchUploadError(
                f"Gengo upload response was not valid JSON for job {target.job_id}",
                title="Invalid JSON response",
                description=text[:_BODY_EXCERPT_CHARS],
                status_code=status,
            ) from exc

        if not isinstance(body, dict):
            raise WorkbenchUploadError(
                f"Gengo upload response was not a JSON object for job {target.job_id}",
                title="Invalid response",
                status_code=status,
            )

        if body.get("opstat") == "ok":
            return body

        msg = str(body.get("msg") or body.get("error") or "Upload failed")
        raise WorkbenchUploadError(
            f"Gengo upload failed for job {target.job_id}: {msg}",
            title="Upload failed",
            description=msg,
            status_code=status,
        )
