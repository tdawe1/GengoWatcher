from __future__ import annotations

import asyncio
import base64
import binascii
import copy
import html
import ipaddress
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from .persistence import (
    SandboxDocumentError,
    sanitize_file_filename,
    validate_collection,
)

from fastapi import (
    Body,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

CAPTURED_COLLECTIONS: tuple[dict[str, Any], ...] = (
    {
        "collection_id": 34176023,
        "job_id": 98937760,
        "order_id": 8012223,
        "customer_id": 336569,
        "source": "現代ロシアにおけるドモヴォイの語りと表象",
        "purpose": "History / Regional",
        "reward": 0.96,
        "unit_count": 20,
    },
    {
        "collection_id": 34176080,
        "job_id": 98938270,
        "order_id": 8012277,
        "customer_id": 1119138,
        "source": "1.つけると良いこと起きるかも\n2.厄除けと幸運のために",
        "purpose": "Generic Content",
        "reward": 1.20,
        "unit_count": 25,
        "comment": (
            "2つの文章ともに商品の什器デザインに使うキャッチコピーです。"
            "１の「つけると〜」というのは「その商品を身につけると」"
            "というニュアンスです。"
        ),
        "comment_id": 70615746,
        "comment_time": "2026-06-30T02:00:05.313235Z",
    },
)

MAX_WEBSOCKET_CLIENTS = 32
WEBSOCKET_QUEUE_SIZE = 64
MAX_SANDBOX_FILE_BYTES = 2 * 1024 * 1024
MAX_SANDBOX_FILENAME_BYTES = 255


_sanitize_download_filename = sanitize_file_filename


@dataclass(frozen=True)
class SandboxFile:
    filename: str
    content_type: str
    content: bytes = field(repr=False)

    @classmethod
    def from_dict(cls, value: Any) -> SandboxFile:
        if not isinstance(value, dict):
            raise ValueError("file fixture must be an object")
        filename = _sanitize_download_filename(value.get("filename"))
        content_type = str(
            value.get("content_type") or "application/octet-stream"
        ).strip()
        if (
            not content_type
            or len(content_type) > 127
            or re.search(r"[\x00-\x1f\x7f]", content_type)
        ):
            raise ValueError("file content_type is invalid")

        has_base64 = "content_base64" in value
        has_text = "content_text" in value
        if has_base64 == has_text:
            raise ValueError(
                "file fixture requires exactly one of content_base64 or content_text"
            )
        if has_text:
            text = value.get("content_text")
            if not isinstance(text, str):
                raise ValueError("file content_text must be a string")
            content = text.encode("utf-8")
        else:
            encoded = value.get("content_base64")
            if not isinstance(encoded, str):
                raise ValueError("file content_base64 must be a string")
            max_encoded_size = 4 * ((MAX_SANDBOX_FILE_BYTES + 2) // 3)
            if len(encoded) > max_encoded_size:
                raise ValueError("file fixture exceeds sandbox size limit")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("file content_base64 is invalid") from exc
        if len(content) > MAX_SANDBOX_FILE_BYTES:
            raise ValueError("file fixture exceeds sandbox size limit")
        return cls(filename=filename, content_type=content_type, content=content)

    def metadata(self, download_url: str) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "content_type": self.content_type,
            "size_bytes": len(self.content),
            "download_url": download_url,
        }


def _file_list_from_seed(value: Any, *, field_name: str) -> list[SandboxFile]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    if len(value) > 1:
        raise ValueError(f"{field_name} supports at most one file")
    return [SandboxFile.from_dict(item) for item in value]


def _job_counts(status: str, target_content: str) -> dict[str, int]:
    in_progress = status == "incomplete"
    submitted = status in {"reviewable", "complete"}
    has_translation = int(bool(target_content))
    return {
        "approved": 0,
        "archived": 0,
        "auto_approve_jobs": 0,
        "confirmed": 0,
        "editable": int(in_progress),
        "has_errors": 0,
        "has_errors_and_warnings": 0,
        "has_translation": has_translation,
        "has_warnings": 0,
        "no_translation": int(not target_content and in_progress),
        "not_submitted": int(in_progress),
        "pemt": 0,
        "pemt_submittable": 0,
        "rejected": 0,
        "returned": 0,
        "submittable": int(in_progress and bool(target_content)),
        "submitted": int(submitted),
        "total": 1,
        "translatable": int(status in {"available", "incomplete"}),
        "unconfirmed": 0,
    }


@dataclass
class SandboxCollection:
    collection_id: int
    job_id: int
    order_id: int
    customer_id: int
    source: str
    purpose: str
    reward: float
    unit_count: int
    comment: str = ""
    comment_id: int = 0
    comment_time: str = ""
    status: str = "available"
    target_content: str = ""
    started_at: float | None = None
    allotted_seconds: int = 3600
    translator_id: int = 789487
    flag_id: int = 0
    has_flag: bool = False
    segment_states: list[dict[str, Any]] = field(default_factory=list)
    job_activities: list[dict[str, Any]] = field(default_factory=list)
    glossary_entries: list[dict[str, Any]] = field(default_factory=list)
    tm_matches: list[dict[str, Any]] = field(default_factory=list)
    mt_translation: str = ""
    source_files: list[SandboxFile] = field(default_factory=list)
    target_files: list[SandboxFile] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SandboxCollection:
        try:
            value = validate_collection(value)
        except SandboxDocumentError as exc:
            raise ValueError(str(exc)) from exc
        allotted_seconds = max(1, int(value.get("allotted_seconds", 3600)))
        started_at = (
            float(value["started_at"]) if value.get("started_at") is not None else None
        )
        if (
            started_at is None
            and str(value.get("status", "available")) == "incomplete"
            and value.get("countdown_seconds_left") is not None
        ):
            seconds_left = max(0, int(value["countdown_seconds_left"]))
            started_at = time.time() - max(0, allotted_seconds - seconds_left)
        return cls(
            collection_id=int(value["collection_id"]),
            job_id=int(value.get("job_id", value["collection_id"])),
            order_id=int(value.get("order_id", value["collection_id"])),
            customer_id=int(value.get("customer_id", 1)),
            source=str(value.get("source", "Test source text")),
            purpose=str(value.get("purpose", "Generic Content")),
            reward=float(value.get("reward", 0)),
            unit_count=int(value.get("unit_count", 1)),
            comment=str(value.get("comment", "")),
            comment_id=int(value.get("comment_id", 0)),
            comment_time=str(value.get("comment_time", "")),
            status=str(value.get("status", "available")),
            target_content=str(value.get("target_content", "")),
            started_at=started_at,
            allotted_seconds=allotted_seconds,
            translator_id=int(value.get("translator_id", 789487)),
            flag_id=int(value.get("flag_id", 0)),
            has_flag=bool(value.get("has_flag", False)),
            segment_states=copy.deepcopy(value.get("segment_states") or []),
            job_activities=copy.deepcopy(value.get("job_activities") or []),
            glossary_entries=copy.deepcopy(value.get("glossary_entries") or []),
            tm_matches=copy.deepcopy(value.get("tm_matches") or []),
            mt_translation=str(value.get("mt_translation", "")),
            source_files=_file_list_from_seed(
                value.get("source_files"), field_name="source_files"
            ),
            target_files=_file_list_from_seed(
                value.get("target_files"), field_name="target_files"
            ),
        )

    def seconds_left(self) -> int:
        if self.status != "incomplete" or self.started_at is None:
            return 0
        return max(0, self.allotted_seconds - int(time.time() - self.started_at))

    def is_expired(self) -> bool:
        return (
            self.status == "incomplete"
            and self.started_at is not None
            and self.seconds_left() <= 0
        )

    @staticmethod
    def expiry_response() -> dict[str, Any]:
        return {
            "code": 3302,
            "description": (
                "Sorry, you have run out of time to complete this collection."
            ),
            "opstat": "critical",
            "title": "Collection expired",
        }

    def summary(self) -> dict[str, Any]:
        status_name = {
            "available": "Available",
            "incomplete": "In Progress",
            "reviewable": "Reviewable",
            "complete": "Complete",
            "declined": "Declined",
        }.get(self.status, self.status.title())
        summary: dict[str, Any] = {
            "allotted_seconds": self.allotted_seconds,
            "auto_approve_time": 120,
            "base_unit_reward": 0.048,
            "bonus_rate": 0,
            "customer_id": self.customer_id,
            "customer_lc": "ja",
            "customer_lc_name": "Japanese",
            "has_tm": bool(self.tm_matches),
            "is_ezra": False,
            "is_src_rtl": False,
            "is_src_word_based": False,
            "is_tgt_rtl": False,
            "is_tgt_word_based": True,
            "job_counts": _job_counts(self.status, self.target_content),
            "lc_src": "ja",
            "lc_src_name": "Japanese",
            "lc_tgt": "en",
            "mtime": int(time.time() * 1000),
            "order_id": self.order_id,
            "purpose": self.purpose,
            "rewards_total": self.reward,
            "seconds_left": self.seconds_left(),
            "segment_match_changed": False,
            "service": "translation",
            "status": self.status,
            "status_name": status_name,
            "tier": "pro",
            "tier_string": "Pro",
            "unit_count": self.unit_count,
        }
        if self.started_at is not None:
            summary["expire_time"] = int(
                (self.started_at + self.allotted_seconds) * 1000
            )
        return summary

    def payload(
        self,
        *,
        source_download_url: str = "",
        target_download_url: str = "",
    ) -> dict[str, Any]:
        editable = self.status == "incomplete"
        summary = self.summary()
        job_status = (
            "submitted" if self.status in {"reviewable", "complete"} else self.status
        )
        job_status_name = (
            "Submitted"
            if job_status == "submitted"
            else "Not Submitted" if editable else summary["status_name"]
        )
        segment = {
            "flag_id": self.flag_id,
            "glossary": [],
            "hasErrors": False,
            "hasWarnings": self.collection_id == 34176080,
            "last_author": "",
            "segment_id": str(self.job_id),
            "source_content": self.source,
            "target_content": self.target_content,
            "tokenized_source": [
                {"content": self.source, "type": "text", "level": "ok"}
            ],
            "tokenized_target": (
                [
                    {
                        "content": self.target_content,
                        "type": "text",
                        "level": "ok",
                    }
                ]
                if self.target_content
                else None
            ),
        }
        job = {
            "Error": "",
            "Position": 1,
            "errors": 0,
            "flag_id": self.flag_id,
            "has_flag": self.has_flag,
            "has_new_comments": False,
            "id": self.job_id,
            "is_editable": editable,
            "max_chars": 0,
            "prefill": "",
            "reward": self.reward,
            "segments": [segment],
            "status": job_status,
            "status_name": job_status_name,
            "unit_count": self.unit_count,
            "warnings": 2 if editable and segment["hasWarnings"] else 0,
        }
        if self.tm_matches or self.glossary_entries:
            job["tm_id"] = 1
        if self.started_at is not None:
            job["translator"] = self.translator_id
        if (
            self.source_files
            and self.status in {"available", "incomplete"}
            and source_download_url
        ):
            job["source_files"] = [self.source_files[0].metadata(source_download_url)]
        if (
            self.target_files
            and self.status in {"reviewable", "complete"}
            and target_download_url
        ):
            job["target_files"] = [self.target_files[0].metadata(target_download_url)]
        return {
            "jobs": [job],
            "pagination": {"last": "1"},
            "position_map": {str(self.job_id): 0},
            "summary": summary,
        }

    def event(self) -> dict[str, Any]:
        return {
            "type": "available_collection",
            "collection": {
                "id": self.collection_id,
                "lc_src": "Japanese",
                "lc_tgt": "English",
                "rewards": f"{self.reward:.2f}",
                "tier": "pro",
                "unit_count": self.unit_count,
            },
        }


@dataclass
class SandboxState:
    collections: dict[int, SandboxCollection] = field(default_factory=dict)
    suggestion_flags: dict[int, dict[str, Any]] = field(default_factory=dict)
    next_suggestion_flag_id: int = 1
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(
        default_factory=set, repr=False
    )
    _lock: RLock = field(default_factory=RLock, repr=False)

    def reset(self) -> None:
        with self._lock:
            self.collections = {
                item.collection_id: item
                for item in (
                    SandboxCollection.from_dict(copy.deepcopy(value))
                    for value in CAPTURED_COLLECTIONS
                )
            }
            self.suggestion_flags = {}
            self.next_suggestion_flag_id = 1

    def add(self, value: dict[str, Any]) -> SandboxCollection:
        item = SandboxCollection.from_dict(value)
        with self._lock:
            self.collections[item.collection_id] = item
        return item

    def get(self, collection_id: int) -> SandboxCollection:
        with self._lock:
            item = self.collections.get(collection_id)
        if item is None:
            raise HTTPException(status_code=404, detail="collection not found")
        return item

    def get_by_job(self, job_id: int) -> SandboxCollection:
        with self._lock:
            item = next(
                (
                    value
                    for value in self.collections.values()
                    if value.job_id == job_id
                ),
                None,
            )
        if item is None:
            raise HTTPException(status_code=404, detail="job not found")
        return item

    def get_by_order(self, order_id: int) -> SandboxCollection:
        with self._lock:
            item = next(
                (
                    value
                    for value in self.collections.values()
                    if value.order_id == order_id
                ),
                None,
            )
        if item is None:
            raise HTTPException(status_code=404, detail="order not found")
        return item

    def available(self) -> list[SandboxCollection]:
        with self._lock:
            return [
                item for item in self.collections.values() if item.status == "available"
            ]

    def add_suggestion_flag(self, payload: dict[str, Any]) -> int:
        with self._lock:
            flag_id = self.next_suggestion_flag_id
            self.next_suggestion_flag_id += 1
            self.suggestion_flags[flag_id] = copy.deepcopy(payload)
        return flag_id

    def delete_suggestion_flag(self, flag_id: int) -> bool:
        with self._lock:
            return self.suggestion_flags.pop(flag_id, None) is not None

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=WEBSOCKET_QUEUE_SIZE
        )
        with self._lock:
            if len(self.subscribers) >= MAX_WEBSOCKET_CLIENTS:
                raise RuntimeError("too many live-dashboard clients")
            self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self.subscribers.discard(queue)

    async def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = tuple(self.subscribers)
        for queue in subscribers:
            value = copy.deepcopy(event)
            try:
                queue.put_nowait(value)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                queue.put_nowait(value)


def _safe_inline_json(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _loopback_hostname(value: str) -> str | None:
    hostname = value.lower().rstrip(".")
    if hostname == "localhost":
        return hostname
    try:
        return hostname if ipaddress.ip_address(hostname).is_loopback else None
    except ValueError:
        return None


def _websocket_origin_is_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    try:
        parts = urlsplit(origin)
        host_parts = urlsplit(f"//{websocket.headers.get('host', '')}")
    except ValueError:
        return False
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return False

    if not host_parts.hostname:
        return False
    try:
        origin_port = parts.port or (443 if parts.scheme == "https" else 80)
        request_port = host_parts.port or (443 if websocket.url.scheme == "wss" else 80)
    except ValueError:
        return False
    origin_host = _loopback_hostname(parts.hostname)
    request_host = _loopback_hostname(host_parts.hostname)
    request_scheme = "https" if websocket.url.scheme == "wss" else "http"
    return (
        origin_host is not None
        and origin_host == request_host
        and parts.scheme == request_scheme
        and origin_port == request_port
    )


def _require_incomplete(item: SandboxCollection, action: str) -> None:
    if item.status != "incomplete":
        raise HTTPException(
            status_code=409,
            detail=f"cannot {action} collection in {item.status} state",
        )


def _layout(title: str, body: str, *, script: str = "") -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{html.escape(title, quote=True)}</title><style>
body{{font:16px system-ui,sans-serif;margin:0;background:#f5f6f7;color:#20252a}}
header{{background:#253746;color:white;padding:1rem 2rem}}main{{max-width:920px;margin:2rem auto;padding:0 1rem}}
.job,.panel{{background:white;border:1px solid #d8dde2;border-radius:7px;padding:1rem;margin:1rem 0}}
.meta{{color:#66717b}}a{{color:#0877b9}}button{{background:#ef6c35;color:white;border:0;border-radius:4px;padding:.7rem 1.2rem;font-weight:700;cursor:pointer}}
textarea{{width:100%;min-height:8rem;box-sizing:border-box;padding:.7rem}}.actions{{display:flex;gap:.7rem;margin-top:1rem}}
</style></head><body><header><strong>Gengo translator sandbox</strong></header><main>{body}</main>{script}</body></html>"""


def _collection_list(state: SandboxState) -> str:
    jobs = "".join(
        f"""<article class="job" data-job-id="{item.collection_id}">
<a href="/t/jobs/details/{item.collection_id}" title="Japanese to English — {html.escape(item.purpose, quote=True)}">
Japanese → English — {html.escape(item.purpose, quote=True)}</a>
<p class="meta">Pro · {item.unit_count} units · US${item.reward:.2f}</p></article>"""
        for item in state.available()
    )
    if not jobs:
        jobs = '<p id="no-jobs">No jobs are currently available.</p>'
    return jobs


def _activity(
    item: SandboxCollection,
    *,
    activity_id: int,
    body: str,
    object_id: int,
    object_type: str,
    activity_type: str = "comment",
    created_at: str = "",
    user: str = "Translator #789487",
    user_id: int = 789487,
    user_type: str = "translator",
    **extra: Any,
) -> dict[str, Any]:
    del item
    timestamp = created_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    return {
        "activity_type": activity_type,
        "attachments": None,
        "body": body,
        "ctime": timestamp,
        "has_style_guide_info": False,
        "id": activity_id,
        "mtime": timestamp,
        "object_id": object_id,
        "object_type": object_type,
        "user": user,
        "user_id": user_id,
        "user_type": user_type,
        **extra,
    }


def _tokenize_text(
    text: str, glossary: list[dict[str, Any]], *, target: bool = False
) -> list[dict[str, str]]:
    if not text:
        return []
    terms: list[str] = []
    for entry in glossary:
        if not isinstance(entry, dict):
            continue
        if target:
            translations = entry.get("translations") or []
            terms.extend(
                str(translation.get("text") or "")
                for translation in translations
                if isinstance(translation, dict)
            )
        else:
            terms.append(str(entry.get("term") or ""))
    matches = [term for term in terms if term and term.casefold() in text.casefold()]
    if not matches:
        return [{"content": text, "type": "text", "level": "ok"}]

    term = max(matches, key=len)
    start = text.casefold().find(term.casefold())
    end = start + len(term)
    tokens: list[dict[str, str]] = []
    if start:
        tokens.append({"content": text[:start], "type": "text", "level": "ok"})
    tokens.append({"content": text[start:end], "type": "glossary", "level": "ok"})
    if end < len(text):
        tokens.append({"content": text[end:], "type": "text", "level": "ok"})
    return tokens


def _download_links(item: SandboxCollection) -> str:
    links: list[str] = []
    if item.source_files and item.status in {"available", "incomplete"}:
        filename = html.escape(item.source_files[0].filename, quote=True)
        links.append(
            f'<a id="source-download" href="/download/source/{item.job_id}/">'
            f"Download source file ({filename})</a>"
        )
    if item.target_files and item.status in {"reviewable", "complete"}:
        filename = html.escape(item.target_files[0].filename, quote=True)
        links.append(
            f'<a id="target-download" href="/download/target/{item.job_id}/">'
            f"Download target file ({filename})</a>"
        )
    if not links:
        return ""
    return '<p class="downloads">' + " · ".join(links) + "</p>"


def _payload_for_request(item: SandboxCollection, request: Request) -> dict[str, Any]:
    source_url = str(request.url_for("download_source_file", job_id=item.job_id))
    target_url = str(request.url_for("download_target_file", job_id=item.job_id))
    return item.payload(
        source_download_url=source_url,
        target_download_url=target_url,
    )


def _file_download_response(item: SandboxCollection, file: SandboxFile) -> Response:
    headers = {
        "Content-Disposition": (
            f'attachment; filename="o{item.order_id}/{file.filename}"'
        ),
        "Content-Transfer-Encoding": "binary",
        "Cache-Control": "private, no-transform, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return Response(
        content=file.content,
        media_type="application/octet-stream",
        headers=headers,
    )


def create_app(state: SandboxState | None = None) -> FastAPI:
    sandbox = state or SandboxState()
    if not sandbox.collections:
        sandbox.reset()
    app = FastAPI(title="Gengo local sandbox", version="0.1")
    app.state.sandbox = sandbox

    @app.get("/", response_class=HTMLResponse)
    @app.get("/t/jobs/", response_class=HTMLResponse)
    @app.get("/t/jobs/status/available", response_class=HTMLResponse)
    @app.get("/t/jobs/status/available/realtime", response_class=HTMLResponse)
    async def available_jobs() -> str:
        return _layout(
            "Available jobs", f"<h1>Available jobs</h1>{_collection_list(sandbox)}"
        )

    @app.get("/t/dashboard", response_class=HTMLResponse)
    async def dashboard() -> str:
        return _layout(
            "Dashboard",
            '<h1>Translator dashboard</h1><p><a href="/t/jobs/status/available">Available jobs</a></p>',
        )

    @app.get("/t/jobs/details/{collection_id}", response_class=HTMLResponse)
    async def job_details(collection_id: int) -> str:
        item = sandbox.get(collection_id)
        if item.status == "available":
            body = f"""<h1>Japanese → English</h1><section class="panel"><p>{html.escape(item.source, quote=True)}</p>
<p class="meta">{html.escape(item.purpose, quote=True)} · Pro · US${item.reward:.2f}</p>
{_download_links(item)}
<form method="post" action="/t/jobs/details/{collection_id}/accept"><button id="accept" type="submit">Accept</button></form></section>"""
            return _layout(f"Job {collection_id}", body)
        if item.status in {"reviewable", "complete"}:
            body = (
                '<h1>Japanese → English</h1><section class="panel">'
                f"{_download_links(item)}</section>"
            )
            return _layout(f"Job {collection_id}", body)
        else:
            return _layout(
                "Job unavailable", "<h1>This job is no longer available.</h1>"
            )

    @app.post("/t/jobs/details/{collection_id}/accept")
    async def accept_from_details(collection_id: int) -> RedirectResponse:
        with sandbox._lock:
            item = sandbox.get(collection_id)
            if item.status == "available":
                item.status = "incomplete"
                item.started_at = time.time()
            elif item.status != "incomplete":
                raise HTTPException(
                    status_code=409,
                    detail=f"cannot accept collection in {item.status} state",
                )
        return RedirectResponse(f"/t/workbench/{collection_id}#!/", status_code=303)

    @app.get("/t/workbench/{collection_id:int}", response_class=HTMLResponse)
    async def workbench(collection_id: int, request: Request) -> str:
        item = sandbox.get(collection_id)
        payload = _safe_inline_json(_payload_for_request(item, request))
        body = f"""<h1>Workbench</h1><section class="panel"><p id="source">{html.escape(item.source, quote=True)}</p>
<label for="target">English translation</label><textarea id="target">{html.escape(item.target_content, quote=True)}</textarea>
{_download_links(item)}
<div class="actions"><button id="start">Start</button><button id="save">Save</button><button id="submit">Submit</button><button id="decline">Decline</button></div>
<p id="status" class="meta">{html.escape(item.status, quote=True)}</p></section>"""
        script = f"""<script>window.__GENGO_WORKBENCH_DATA__={payload};
const cid={collection_id}; const status=document.querySelector('#status');
async function action(name, body={{}}){{const r=await fetch(`/t/workbench/collection/${{cid}}/${{name}}`,{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify(body)}});window.__GENGO_WORKBENCH_DATA__=await r.json();status.textContent=window.__GENGO_WORKBENCH_DATA__.summary?.status||name;return window.__GENGO_WORKBENCH_DATA__;}}
document.querySelector('#start').onclick=()=>action('start');
document.querySelector('#save').onclick=()=>action('save',{{jobs:[{{id:{item.job_id},segments:[{{segment_id:'{item.job_id}',target_content:document.querySelector('#target').value}}]}}]}});
document.querySelector('#submit').onclick=()=>action('submit');
document.querySelector('#decline').onclick=async()=>{{await action('decline');location.href='/t/jobs/status/available';}};</script>"""
        return _layout(f"Workbench {collection_id}", body, script=script)

    @app.get("/t/workbench/collection/{collection_id}")
    async def get_collection(
        collection_id: int, request: Request, page: int = 1
    ) -> dict[str, Any]:
        del page
        return _payload_for_request(sandbox.get(collection_id), request)

    @app.get("/download/source/{job_id}/")
    async def download_source_file(job_id: int) -> Response:
        """Serve an inferred source-file route for deterministic local tests."""
        item = sandbox.get_by_job(job_id)
        if item.status not in {"available", "incomplete"} or not item.source_files:
            raise HTTPException(status_code=404, detail="source file not found")
        return _file_download_response(item, item.source_files[0])

    @app.get("/download/target/{job_id}/")
    async def download_target_file(job_id: int) -> Response:
        item = sandbox.get_by_job(job_id)
        if item.status not in {"reviewable", "complete"} or not item.target_files:
            raise HTTPException(status_code=404, detail="target file not found")
        return _file_download_response(item, item.target_files[0])

    @app.post("/t/workbench/collection/{collection_id}/start")
    async def start_collection(
        collection_id: int, payload: dict[str, Any] = Body(default_factory=dict)
    ) -> dict[str, Any]:
        del payload
        with sandbox._lock:
            item = sandbox.get(collection_id)
            if item.is_expired():
                return item.expiry_response()
            if item.status == "available":
                item.status = "incomplete"
                item.started_at = time.time()
            elif item.status != "incomplete":
                raise HTTPException(
                    status_code=409,
                    detail=f"cannot start collection in {item.status} state",
                )
            return item.payload()

    @app.get("/t/workbench/collection/{collection_id}/status")
    @app.post("/t/workbench/collection/{collection_id}/status")
    async def collection_status(collection_id: int) -> dict[str, Any]:
        item = sandbox.get(collection_id)
        if item.is_expired():
            return item.expiry_response()
        return item.summary()

    @app.post("/t/workbench/collection/{collection_id}/save")
    async def save_collection(
        collection_id: int, payload: dict[str, Any] = Body(default_factory=dict)
    ) -> dict[str, Any]:
        segments = payload.get("segments") or []
        jobs = payload.get("jobs") or []
        if jobs and isinstance(jobs[0], dict):
            segments = jobs[0].get("segments") or segments
        with sandbox._lock:
            item = sandbox.get(collection_id)
            if item.is_expired():
                return item.expiry_response()
            _require_incomplete(item, "save")
            if segments and isinstance(segments[0], dict):
                item.target_content = str(segments[0].get("target_content") or "")
            response = item.payload()
            return {"summary": response["summary"], "jobs": response["jobs"]}

    @app.post("/t/workbench/collection/{collection_id}/decline")
    async def decline_collection(collection_id: int) -> dict[str, Any]:
        with sandbox._lock:
            item = sandbox.get(collection_id)
            if item.is_expired():
                return item.expiry_response()
            _require_incomplete(item, "decline")
            item.status = "declined"
            return {}

    @app.post("/t/workbench/collection/{collection_id}/submit")
    async def submit_collection(collection_id: int) -> dict[str, Any]:
        with sandbox._lock:
            item = sandbox.get(collection_id)
            if item.is_expired():
                return item.expiry_response()
            _require_incomplete(item, "submit")
            if not item.target_content.strip():
                raise HTTPException(
                    status_code=409,
                    detail="cannot submit collection without a translation",
                )
            item.status = "reviewable"
            response = item.payload()
            return {"summary": response["summary"], "jobs": response["jobs"]}

    @app.get("/t/workbench/activity/collection/{collection_id}")
    async def collection_activity(
        collection_id: int, order_id: int | None = None
    ) -> list[dict[str, Any]]:
        item = sandbox.get(collection_id)
        del order_id
        if not item.comment:
            return []
        return [
            _activity(
                item,
                activity_id=item.comment_id or 1,
                body=item.comment,
                object_id=item.order_id,
                object_type="order",
                created_at=item.comment_time,
                user=f"Customer #{item.customer_id}",
                user_id=item.customer_id,
                user_type="customer",
            )
        ]

    @app.get("/t/workbench/activity/job/{job_id}")
    async def job_activity(job_id: int, tier: str = "") -> list[dict[str, Any]]:
        item = sandbox.get_by_job(job_id)
        del tier
        return list(item.job_activities)

    @app.post("/t/workbench/comment/{object_type}/{object_id}")
    async def save_comment(
        object_type: str,
        object_id: int,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        if object_type == "job":
            item = sandbox.get_by_job(object_id)
        elif object_type == "collection":
            item = sandbox.get(object_id)
        elif object_type == "order":
            item = sandbox.get_by_order(object_id)
        else:
            raise HTTPException(status_code=400, detail="unsupported comment type")
        activity = _activity(
            item,
            activity_id=1_000_000 + len(item.job_activities),
            body=str(payload.get("comment") or ""),
            object_id=object_id,
            object_type=object_type,
        )
        item.job_activities.append(activity)
        return {"opstat": "ok"}

    @app.post("/t/workbench/collection/{collection_id}/job/{job_id}/flag")
    async def flag_job(
        collection_id: int,
        job_id: int,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        item = sandbox.get(collection_id)
        if item.job_id != job_id:
            raise HTTPException(status_code=404, detail="job not found in collection")
        item.flag_id = max(1, item.flag_id + 1)
        item.has_flag = True
        reason = int(payload.get("flag") or 0)
        item.job_activities.append(
            _activity(
                item,
                activity_id=item.flag_id,
                body=str(payload.get("comment") or "Flagged by translator"),
                object_id=job_id,
                object_type="job",
                activity_type="flag",
                flag_type=reason,
            )
        )
        return {"id": item.flag_id}

    @app.post("/t/workbench/collection/{collection_id}/job/{job_id}/flag/resolve")
    async def resolve_job_flag(
        collection_id: int,
        job_id: int,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        item = sandbox.get(collection_id)
        del payload
        if item.job_id != job_id:
            raise HTTPException(status_code=404, detail="job not found in collection")
        item.has_flag = False
        return {"id": item.flag_id, "has_flag": False}

    @app.get("/t/workbench/job/segments/get_state")
    async def get_segments_state(
        job_id: int, is_edit_service: bool = False
    ) -> dict[str, Any]:
        item = sandbox.get_by_job(job_id)
        del is_edit_service
        return {"segments": copy.deepcopy(item.segment_states)}

    @app.post("/t/workbench/job/segments/set_state")
    async def set_segments_state(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        item = sandbox.get_by_job(int(payload.get("job_id") or 0))
        states = payload.get("states") or []
        item.segment_states = [
            {
                "segment_id": str(state.get("segment_id") or ""),
                "is_edited": bool(state.get("is_edited")),
            }
            for state in states
            if isinstance(state, dict)
        ]
        return {"segments": copy.deepcopy(item.segment_states)}

    @app.post("/t/workbench/logger")
    async def workbench_logger(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        del payload
        return {"opstat": "ok"}

    @app.post("/t/workbench/segment/tokenize")
    async def tokenize_segment(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        glossary = payload.get("glossary") or []
        if not isinstance(glossary, list):
            glossary = []
        return {
            "tokenized_source": _tokenize_text(
                str(payload.get("source") or ""), glossary
            ),
            "tokenized_target": _tokenize_text(
                str(payload.get("target") or ""), glossary, target=True
            ),
        }

    @app.post("/t/workbench/segment/translate")
    async def translate_segment(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        with sandbox._lock:
            item = sandbox.get(int(payload.get("collection_id") or 0))
            if item.is_expired():
                return item.expiry_response()
            _require_incomplete(item, "translate")
            if str(payload.get("segment_id") or "") != str(item.job_id):
                raise HTTPException(status_code=404, detail="segment not found")
            item.target_content = str(payload.get("target_content") or "")
            return {"summary": item.summary()}

    @app.get("/t/workbench/segment/is_edited")
    async def is_segment_edited(job_id: int, segment_id: str) -> dict[str, Any]:
        item = sandbox.get_by_job(job_id)
        edited = next(
            (
                bool(state.get("is_edited"))
                for state in item.segment_states
                if str(state.get("segment_id")) == segment_id
            ),
            False,
        )
        return {"segment_id": segment_id, "is_edited": edited}

    @app.put("/t/workbench/segment/is_edited")
    async def mark_segment_edited(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        item = sandbox.get_by_job(int(payload.get("job_id") or 0))
        segment_id = str(payload.get("segment_id") or item.job_id)
        state = {
            "segment_id": segment_id,
            "is_edited": bool(payload.get("is_edited", True)),
        }
        item.segment_states = [
            existing
            for existing in item.segment_states
            if str(existing.get("segment_id")) != segment_id
        ]
        item.segment_states.append(state)
        return state

    @app.get("/t/workbench/glossary")
    async def glossary(tm_id: int, segment_id: str) -> list[dict[str, Any]]:
        del tm_id
        item = sandbox.get_by_job(int(segment_id))
        return copy.deepcopy(item.glossary_entries)

    @app.post("/t/workbench/tm/matches/{tm_id}")
    async def translation_memory_matches(
        tm_id: int, payload: dict[str, Any] = Body(default_factory=dict)
    ) -> dict[str, Any]:
        del tm_id
        item = sandbox.get_by_job(int(payload.get("job_id") or 0))
        return {"matches": copy.deepcopy(item.tm_matches)}

    @app.post("/t/workbench/mt/translate")
    async def machine_translate(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        item = sandbox.get_by_job(int(payload.get("job_id") or 0))
        source = str(payload.get("text") or "")
        translated = item.mt_translation or f"[sandbox MT] {source}"
        return {
            "translated_text": translated,
            "provider": "sandbox",
            "flag_id": None,
        }

    @app.post("/t/workbench/flappy")
    async def flag_suggestion(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        sandbox.get_by_job(int(payload.get("job_id") or 0))
        return {"id": sandbox.add_suggestion_flag(payload)}

    @app.delete("/t/workbench/flappy/delete")
    async def unflag_suggestion(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        flag_id = int(payload.get("flag_id") or 0)
        return {"deleted": sandbox.delete_suggestion_flag(flag_id)}

    @app.get("/rss/available_jobs/{feed_token}")
    async def rss_feed(request: Request, feed_token: str) -> Response:
        del feed_token
        items = "".join(
            f"<item><title>Japanese to English | Pro | US${item.reward:.2f}</title>"
            f"<link>{escape(str(request.base_url).rstrip('/'))}/t/jobs/details/{item.collection_id}</link>"
            f"<guid>{item.collection_id}</guid><description>{escape(item.purpose)}</description></item>"
            for item in sandbox.available()
        )
        xml = f'<?xml version="1.0"?><rss version="2.0"><channel><title>Gengo available jobs</title>{items}</channel></rss>'
        return Response(xml, media_type="application/rss+xml")

    @app.websocket("/live-dashboard")
    async def live_dashboard(websocket: WebSocket) -> None:
        if not _websocket_origin_is_allowed(websocket):
            await websocket.close(code=1008, reason="untrusted Origin")
            return
        try:
            queue = sandbox.subscribe()
        except RuntimeError:
            await websocket.close(code=1013, reason="too many clients")
            return
        await websocket.accept()
        sender: asyncio.Task[None] | None = None
        try:
            auth = await websocket.receive_json()
            await websocket.send_json(
                {"type": "welcome", "user_id": auth.get("user_id")}
            )
            for item in sandbox.available():
                await websocket.send_json(item.event())

            async def send_events() -> None:
                while True:
                    await websocket.send_json(await queue.get())

            sender = asyncio.create_task(send_events())
            while True:
                message = await websocket.receive_json()
                if message.get("type") == "list_available":
                    for item in sandbox.available():
                        await websocket.send_json(item.event())
        except WebSocketDisconnect:
            return
        finally:
            sandbox.unsubscribe(queue)
            if sender is not None:
                sender.cancel()
                try:
                    await sender
                except asyncio.CancelledError:
                    pass

    @app.get("/__sandbox__/state")
    async def sandbox_state() -> dict[str, Any]:
        return {str(key): value.payload() for key, value in sandbox.collections.items()}

    @app.post("/__sandbox__/reset")
    async def reset_sandbox() -> JSONResponse:
        sandbox.reset()
        return JSONResponse({"ok": True, "collections": len(sandbox.collections)})

    @app.post("/__sandbox__/jobs", status_code=201)
    async def add_sandbox_job(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            item = sandbox.add(payload)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await sandbox.publish(item.event())
        return item.payload()

    @app.post("/__sandbox__/events/available/{collection_id}")
    async def publish_available_collection(collection_id: int) -> dict[str, Any]:
        event = sandbox.get(collection_id).event()
        await sandbox.publish(event)
        return event

    @app.post("/__sandbox__/collections/{collection_id}/expire")
    async def expire_sandbox_collection(collection_id: int) -> dict[str, Any]:
        item = sandbox.get(collection_id)
        item.status = "incomplete"
        item.started_at = time.time() - item.allotted_seconds - 1
        return item.expiry_response()

    return app


app = create_app()
