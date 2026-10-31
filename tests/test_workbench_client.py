from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from fastapi.testclient import TestClient
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict

from gengowatcher.gengo_sandbox.app import SandboxState, create_app
from gengowatcher.workbench_client import (
    GengoWorkbenchClient,
    UploadTarget,
    WorkbenchError,
    WorkbenchExpiredError,
    WorkbenchFileCollectionError,
    WorkbenchSessionDeadError,
    WorkbenchUploadError,
    WorkbenchValidationError,
    extract_gengo_tags,
    extract_triple_brackets,
    parse_job_details,
    validate_segment_preservation,
)

BASE_URL = "http://sandbox"
SESSION_VALUE = "test-session-cookie"
CID = 9300
JOB_ID = 99300
SOURCE = "{1}東京駅{/1}から[[[Shinkansen]]]で{2}"


def _to_requests_response(
    request: requests.PreparedRequest,
    status: int,
    headers: dict[str, str],
    content: bytes,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers = CaseInsensitiveDict(headers)
    response._content = content
    response.url = request.url or ""
    response.request = request
    response.encoding = "utf-8"
    return response


class SandboxAdapter(BaseAdapter):
    """Route ``requests`` traffic into an in-process ASGI app without sockets."""

    def __init__(self, app: Any) -> None:
        super().__init__()
        self.client = TestClient(app, follow_redirects=False)
        self.sent: list[requests.PreparedRequest] = []

    def send(
        self, request: requests.PreparedRequest, **kwargs: Any
    ) -> requests.Response:
        self.sent.append(request)
        parts = urlsplit(request.url)
        target = parts.path + (f"?{parts.query}" if parts.query else "")
        body = request.body
        if isinstance(body, str):
            body = body.encode("utf-8")
        result = self.client.request(
            request.method or "GET",
            target,
            headers={
                k: v
                for k, v in request.headers.items()
                if k.lower() != "content-length"
            },
            content=body,
        )
        return _to_requests_response(
            request, result.status_code, dict(result.headers), result.content
        )

    def close(self) -> None:
        self.client.close()


class CannedAdapter(BaseAdapter):
    """Answer each request from a callable returning (status, headers, body)."""

    def __init__(
        self,
        responder: Callable[
            [requests.PreparedRequest], tuple[int, dict[str, str], bytes]
        ],
    ) -> None:
        super().__init__()
        self.responder = responder
        self.sent: list[requests.PreparedRequest] = []

    def send(
        self, request: requests.PreparedRequest, **kwargs: Any
    ) -> requests.Response:
        self.sent.append(request)
        status, headers, content = self.responder(request)
        return _to_requests_response(request, status, headers, content)

    def close(self) -> None:
        pass


def _json_response(payload: Any, status: int = 200):
    return status, {"Content-Type": "application/json"}, json.dumps(payload).encode()


def _client_for(adapter: BaseAdapter) -> GengoWorkbenchClient:
    session = requests.Session()
    session.mount(BASE_URL, adapter)
    return GengoWorkbenchClient(
        user_session=SESSION_VALUE,
        base_url=BASE_URL,
        user_agent="UnitTest/1.0",
        session=session,
    )


@pytest.fixture
def sandbox() -> Iterator[tuple[SandboxState, SandboxAdapter, GengoWorkbenchClient]]:
    state = SandboxState()
    adapter = SandboxAdapter(create_app(state))
    state.add(
        {
            "collection_id": CID,
            "job_id": JOB_ID,
            "order_id": 7300,
            "source": SOURCE,
            "reward": 1.5,
            "unit_count": 12,
            "status": "incomplete",
            "allotted_seconds": 3600,
            "countdown_seconds_left": 1800,
        }
    )
    client = _client_for(adapter)
    yield state, adapter, client
    client.close()
    adapter.close()


# ---------------------------------------------------------------- helpers


def test_extract_helpers_count_tags_and_spans() -> None:
    text = "{1}a{/1} {1}b{/1} {12} [[[keep\nme]]] [[[x]]] {x} [[not]]"
    assert extract_gengo_tags(text) == {"{1}": 2, "{/1}": 2, "{12}": 1}
    assert extract_triple_brackets(text) == {"[[[keep\nme]]]": 1, "[[[x]]]": 1}


@pytest.mark.parametrize(
    ("target", "expected_fragment"),
    [
        ("{1}Tokyo Station{/1} by [[[Shinkansen]]] {2}", None),
        ("Tokyo Station{/1} by [[[Shinkansen]]] {2}", "missing tags: {1}"),
        (
            "{1}Tokyo Station{/1} by [[[Shinkansen]]] {2}{/2}",
            "unexpected tags: {/2}",
        ),
        (
            "{1}Tokyo Station{/1} by [[[bullet train]]] {2}",
            "missing or altered [[[...]]] spans: [[[Shinkansen]]]",
        ),
        ("   ", "target is blank"),
    ],
)
def test_validate_segment_preservation(
    target: str, expected_fragment: str | None
) -> None:
    errors = validate_segment_preservation(SOURCE, target)
    if expected_fragment is None:
        assert errors == []
    else:
        assert any(expected_fragment in error for error in errors), errors


def test_validate_segment_preservation_allows_blank_source() -> None:
    assert validate_segment_preservation("  ", "") == []


# ------------------------------------------------------------- sandbox API


def test_fetch_collection_returns_segments_and_deadline(sandbox) -> None:
    _, adapter, client = sandbox
    before = time.time()

    collection = client.fetch_collection(CID)

    assert collection.collection_id == str(CID)
    assert collection.status == "incomplete"
    assert collection.order_id == "7300"
    assert collection.last_page == 1
    assert 0 < collection.seconds_left <= 1800
    assert collection.deadline_epoch is not None
    assert collection.deadline_epoch == pytest.approx(before + 1800, abs=5)
    assert [job.job_id for job in collection.jobs] == [str(JOB_ID)]
    (segment,) = collection.all_segments
    assert segment.segment_id == str(JOB_ID)
    assert segment.job_id == str(JOB_ID)
    assert segment.source_content == SOURCE
    assert segment.target_content == ""

    (request,) = adapter.sent
    assert parse_qs(urlsplit(request.url).query) == {"page": ["1"]}
    assert request.headers["Cookie"] == f"myG_myGSession_={SESSION_VALUE}"
    assert request.headers["Referer"] == f"{BASE_URL}/t/workbench/{CID}"
    assert request.headers["User-Agent"] == "UnitTest/1.0"
    assert "Origin" not in request.headers
    assert "X-Requested-With" not in request.headers


def test_get_status_then_expired(sandbox) -> None:
    _, adapter, client = sandbox
    before = time.time()

    status = client.get_status(CID)

    assert status["status"] == "incomplete"
    assert 0 < status["seconds_left"] <= 1800
    assert status["expire_time_epoch"] == pytest.approx(before + 1800, abs=5)

    adapter.client.post(f"/__sandbox__/collections/{CID}/expire")
    with pytest.raises(WorkbenchExpiredError) as excinfo:
        client.get_status(CID)
    assert excinfo.value.code == 3302
    assert excinfo.value.opstat == "critical"


def test_save_segments_stages_translation(sandbox) -> None:
    state, adapter, client = sandbox
    collection = client.fetch_collection(CID)
    target = "{1}Tokyo Station{/1} by [[[Shinkansen]]] {2}"

    client.save_segments(
        CID,
        {str(JOB_ID): [{"segment_id": str(JOB_ID), "target_content": target}]},
        validate_against=collection,
    )

    save_request = adapter.sent[-1]
    assert save_request.method == "POST"
    assert save_request.headers["Origin"] == BASE_URL
    assert save_request.headers["Content-Type"] == "application/json;charset=utf-8"
    assert json.loads(save_request.body) == {
        "jobs": [
            {
                "id": JOB_ID,
                "segments": [{"segment_id": str(JOB_ID), "target_content": target}],
            }
        ]
    }
    assert state.collections[CID].target_content == target
    assert client.fetch_collection(CID).all_segments[0].target_content == target


def test_save_segments_rejects_tag_mismatch_without_request(sandbox) -> None:
    state, adapter, client = sandbox
    collection = client.fetch_collection(CID)
    sent_before = len(adapter.sent)

    with pytest.raises(WorkbenchValidationError) as excinfo:
        client.save_segments(
            CID,
            {JOB_ID: [{"segment_id": JOB_ID, "target_content": "Tokyo Station"}]},
            validate_against=collection,
        )

    assert "missing tags" in excinfo.value.description
    assert len(adapter.sent) == sent_before
    assert state.collections[CID].target_content == ""


def test_submit_collection_posts_next_page(sandbox) -> None:
    state, adapter, client = sandbox
    client.save_segments(
        CID,
        {JOB_ID: [{"segment_id": JOB_ID, "target_content": "Done {1}{/1}{2}"}]},
    )

    client.submit_collection(CID, last_page=1)

    submit_request = adapter.sent[-1]
    assert urlsplit(submit_request.url).path == (
        f"/t/workbench/collection/{CID}/submit"
    )
    assert json.loads(submit_request.body) == {"page": 2}
    assert state.collections[CID].status == "reviewable"


# ------------------------------------------------------------ canned errors


def test_fetch_collection_merges_pages_and_dedupes_segments() -> None:
    def segment(sid: str, text: str) -> dict[str, Any]:
        return {"segment_id": sid, "source_content": text, "target_content": None}

    pages = {
        "1": {
            "summary": {"status": "incomplete", "seconds_left": 600},
            "pagination": {"last": "3"},
            "jobs": [{"id": 1, "segments": [segment("a", "A")]}],
        },
        "2": {
            "jobs": [
                {"id": 1, "segments": [segment("a", "A"), segment("b", "B")]},
                {"id": 2, "segments": [segment("c", "C")]},
            ]
        },
    }

    def responder(request: requests.PreparedRequest):
        page = parse_qs(urlsplit(request.url).query)["page"][0]
        return _json_response(pages[page])

    adapter = CannedAdapter(responder)
    collection = _client_for(adapter).fetch_collection(55, max_pages=2)

    assert collection.last_page == 2
    assert len(adapter.sent) == 2
    assert [(s.job_id, s.segment_id) for s in collection.all_segments] == [
        ("1", "a"),
        ("1", "b"),
        ("2", "c"),
    ]
    assert collection.all_segments[0].target_content == ""
    assert collection.expire_time_epoch is None
    assert collection.deadline_epoch == collection.fetched_at + 600


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        (
            (302, {"Location": "https://gengo.com/auth/form/login"}, b""),
            WorkbenchSessionDeadError,
        ),
        ((401, {}, b""), WorkbenchSessionDeadError),
        (
            (200, {"Content-Type": "text/html"}, b"<form action='/auth/form/login'>"),
            WorkbenchSessionDeadError,
        ),
        (
            _json_response(
                {"opstat": "error", "code": 3009, "title": "File collection"}
            ),
            WorkbenchFileCollectionError,
        ),
        (
            _json_response(
                {"opstat": "error", "code": 1, "title": "Sorry, something's gone"}
            ),
            WorkbenchError,
        ),
        (_json_response({"detail": "conflict"}, status=409), WorkbenchError),
    ],
)
def test_error_responses_raise_typed_errors(
    response: tuple[int, dict[str, str], bytes], error_type: type[Exception]
) -> None:
    adapter = CannedAdapter(lambda _request: response)

    with pytest.raises(error_type) as excinfo:
        _client_for(adapter).fetch_collection(1)

    assert type(excinfo.value) is error_type
    assert len(adapter.sent) == 1


def test_missing_session_fails_before_network() -> None:
    adapter = CannedAdapter(lambda _request: _json_response({}))
    session = requests.Session()
    session.mount(BASE_URL, adapter)
    client = GengoWorkbenchClient(user_session="", base_url=BASE_URL, session=session)

    with pytest.raises(WorkbenchSessionDeadError):
        client.get_status(1)
    assert adapter.sent == []


# ------------------------------------------------------------ HTML pages

_DASHBOARD_ROW = """
<tr class="td-list-row" data-id='{cid}' data-detail-url='{base}/t/jobs/details/{cid}'>
  <td class="td-list-column td-list-column-tier"><span class="label
    td-list-label-tier td-list-label-tier-standard">{tier}</span></td>
  <td class="td-list-column td-list-column-langs">
    <a class="td-list-column-langs-link" href="{base}/t/jobs/details/{cid}">
      ja &gt; en            </a></td>
  <td class="td-list-column td-list-column-content">
    <a class="td-list-column-content-link" href="{base}/t/jobs/details/{cid}">
      {title}
    </a></td>
  <td class="td-list-column"><div class="td-list-section-icon"></div></td>
  <td class="td-list-column td-list-column-unitcount">   {units}   </td>
  <td class="td-list-column td-list-column-reward">
    {reward}<div class="td-list-section-bonus"></div></td>
</tr>"""


def _dashboard(*sections: tuple[str, list[dict[str, Any]]]) -> str:
    parts = ["<html><body><h1>Dashboard</h1>"]
    for heading, rows in sections:
        body = "".join(_DASHBOARD_ROW.format(base=BASE_URL, **row) for row in rows)
        parts.append(
            f'<h2 class="td-list-head-label">{heading}</h2>'
            f'<table class="td-list"><tbody>{body}</tbody></table>'
        )
    return "".join(parts) + "</body></html>"


def _html_response(text: str, status: int = 200, **headers: str):
    return status, {"Content-Type": "text/html", **headers}, text.encode("utf-8")


def test_list_incomplete_collections_reads_only_incomplete_section() -> None:
    page = _dashboard(
        (
            "Incomplete jobs",
            [
                {
                    "cid": 501,
                    "tier": "pro",
                    "title": "架空の島\n案内...",
                    "units": "1,234",
                    "reward": "$59.23",
                },
                {
                    "cid": 502,
                    "tier": "std",
                    "title": "x",
                    "units": 8,
                    "reward": "$0.08",
                },
            ],
        ),
        (
            "Available jobs - All",
            [{"cid": 503, "tier": "pro", "title": "y", "units": 1, "reward": "$1"}],
        ),
    )
    adapter = CannedAdapter(lambda _request: _html_response(page))
    client = _client_for(adapter)

    rows = client.list_incomplete_collections()

    assert [row.collection_id for row in rows] == ["501", "502"]
    first = rows[0]
    # Charset-less text/html is decoded as UTF-8, not ISO-8859-1.
    assert first.title == "架空の島 案内..."
    assert first.lang_pair == "ja > en"
    assert (first.tier, first.unit_count, first.reward) == ("pro", 1234, 59.23)
    assert first.url == f"{BASE_URL}/t/jobs/details/501"
    assert rows[1].tier == "std"
    request = adapter.sent[0]
    assert urlsplit(request.url).path == "/t/dashboard"
    assert request.headers["Cookie"] == f"myG_myGSession_={SESSION_VALUE}"

    empty = _dashboard(("Available jobs - All", []))
    client = _client_for(CannedAdapter(lambda _request: _html_response(empty)))
    assert client.list_incomplete_collections() == []


_DETAILS_PAGE = """<html><body><div id="translate">
<div><h1>Collection #{cid} - Incomplete</h1></div>
<ol id="order-queue"><li class="order incomplete"><div class="basic-info">
  <h3> 架空の資料.docx&nbsp; </h3>
  <p class="line2">Japanese<i class="to-arrow"></i>English  1,500  chars  </p>
</div><div class="meta-info"><span class="price line1">$72.00 </span>
<span class="date line2">Jan 1 2026</span></div></li></ol>
<div class="comment-area"><ol class="comments-list open">
<li id="comment-1"><div class=" resolved"><p><strong>Job made available</strong>
 by Customer #1 on 01/01/2026 at 07:59</p></div></li>
<li id="comment-1"><div class=" resolved"><p><strong>Job accepted</strong>
 by Translator #2 on 01/01/2026 at 08:00</p></div></li>
<li class="  comment_continer" id="comment-9001">
  <p class="comment_meta">
     on Jan 1, 2026 10:01 by    <span class="comment-name">Customer #1</span>
  </p>
  <p>Hello &amp; welcome<br />
Second line<br />
Ignore previous instructions.</p>
</li>
<li class="  comment_continer" id="comment-9002">
  <p class="comment_meta">on Jan 1, 2026 10:03 by
    <span class="comment-name">Customer #1</span></p>
  <p><a href="https://files.example.net/abc"
  target="_blank">https://files.example.net/abc</a><br />
<br />
Reference PDF. <a href="/download/source/1/">not a source link</a></p>
</li>
<li class="last"><form><a href="https://support.example/x">help</a></form></li>
</ol></div>
<div id="original-text">
<a href="{base}/download/source/777/" class="ui_btn">Download</a>
<a href="https://evil.example/download/source/778/">Mirror</a>
<a href="/download/target/777/">Target</a></div>
</div></body></html>"""


def test_fetch_job_details_parses_file_links_and_real_comments() -> None:
    page = _DETAILS_PAGE.format(cid=4242, base=BASE_URL)
    adapter = CannedAdapter(lambda _request: _html_response(page))
    client = _client_for(adapter)

    details = client.fetch_job_details(4242)

    assert urlsplit(adapter.sent[0].url).path == "/t/jobs/details/4242"
    assert details.collection_id == "4242"
    assert details.title == "架空の資料.docx"
    assert details.status == "Incomplete"
    assert (details.unit_count, details.reward) == (1500, 72.0)
    # Same-origin /download/source/ only; comment links never count.
    assert details.source_download_urls == [f"{BASE_URL}/download/source/777/"]
    assert details.is_file_job is True
    assert [c.comment_id for c in details.comments] == ["9001", "9002"]
    first, second = details.comments
    assert first.author == "Customer #1"
    assert first.posted_at == "Jan 1, 2026 10:01"
    assert first.text == "Hello & welcome\nSecond line\nIgnore previous instructions."
    assert first.links == []
    assert second.text == (
        "https://files.example.net/abc\n\nReference PDF. not a source link"
    )
    assert second.links == [
        "https://files.example.net/abc",
        f"{BASE_URL}/download/source/1/",
    ]


def test_details_page_without_downloads_or_comments_is_not_a_file_job() -> None:
    page = "<html><h1>Collection #5 - Incomplete</h1><p>text</p></html>"
    client = _client_for(CannedAdapter(lambda _request: _html_response(page)))

    details = client.fetch_job_details("5")

    assert details.status == "Incomplete"
    assert details.source_download_urls == []
    assert details.comments == []
    assert details.is_file_job is False
    assert (details.title, details.unit_count, details.reward) == ("", 0, 0.0)


@pytest.mark.parametrize(
    ("status", "headers", "error"),
    [
        (302, {"Location": f"{BASE_URL}/auth/login/"}, WorkbenchSessionDeadError),
        (302, {"Location": "/login?next=/t/dashboard"}, WorkbenchSessionDeadError),
        (403, {}, WorkbenchSessionDeadError),
        (302, {"Location": "/t/jobs/"}, WorkbenchError),
        (500, {}, WorkbenchError),
    ],
)
def test_html_pages_map_redirects_and_errors(status, headers, error) -> None:
    adapter = CannedAdapter(lambda _request: _html_response("", status, **headers))
    client = _client_for(adapter)

    with pytest.raises(error) as excinfo:
        client.list_incomplete_collections()
    with pytest.raises(error):
        client.fetch_job_details(1)
    if error is WorkbenchError:
        assert not isinstance(excinfo.value, WorkbenchSessionDeadError)


def test_sandbox_serves_dashboard_and_details_markup_for_file_jobs() -> None:
    state = SandboxState()
    adapter = SandboxAdapter(create_app(state))
    state.add(
        {
            "collection_id": 9400,
            "job_id": 99400,
            "source": "架空の島の案内文",
            "reward": 12.5,
            "unit_count": 300,
            "status": "incomplete",
            "countdown_seconds_left": 1800,
            "file_job": True,
            "source_files": [
                {
                    "filename": "brief.txt",
                    "content_type": "text/plain",
                    "content_text": "本文",
                }
            ],
            "comments": [
                {
                    "author": "Customer #7",
                    "posted_at": "Jan 2, 2026 09:00",
                    "text": "Line one\nSee https://files.example.net/x",
                }
            ],
        }
    )
    client = _client_for(adapter)
    try:
        rows = client.list_incomplete_collections()
        assert [(row.collection_id, row.unit_count, row.reward) for row in rows] == [
            ("9400", 300, 12.5)
        ]
        details = client.fetch_job_details(9400)
        assert details.title == "brief.txt"
        assert details.source_download_urls == [f"{BASE_URL}/download/source/99400/"]
        assert [(c.author, c.posted_at, c.text, c.links) for c in details.comments] == [
            (
                "Customer #7",
                "Jan 2, 2026 09:00",
                "Line one\nSee https://files.example.net/x",
                ["https://files.example.net/x"],
            )
        ]
        with pytest.raises(WorkbenchFileCollectionError):
            client.fetch_collection(9400)
        assert 0 < client.get_status(9400)["seconds_left"] <= 1800
    finally:
        client.close()
        adapter.close()


# ---------------------------------------------------------------- config


class FakeConfig:
    def __init__(self, values: dict[str, dict[str, Any]]) -> None:
        self.values = values

    def get(self, section: str, key: str, fallback: Any = None) -> Any:
        return self.values.get(section, {}).get(key, fallback)


def test_from_config_defaults_when_sections_missing(monkeypatch) -> None:
    monkeypatch.setenv("GENGO_USER_SESSION", "from-env")

    client = GengoWorkbenchClient.from_config(FakeConfig({}))

    assert client.base_url == "https://gengo.com"
    assert client.timeout_sec == 30.0
    assert client.user_agent == ""
    assert client.has_session


def test_from_config_base_url_precedence(monkeypatch) -> None:
    monkeypatch.delenv("GENGO_USER_SESSION", raising=False)
    values: dict[str, dict[str, Any]] = {
        "WebSocket": {"user_session": "cfg-session"},
        "Network": {"browser_user_agent": "UA"},
        "BrowserWorker": {"sandbox_origin": "http://127.0.0.1:8765/"},
        "JobPipeline": {"workbench_timeout_sec": "12.5"},
    }

    sandbox_client = GengoWorkbenchClient.from_config(FakeConfig(values))
    assert sandbox_client.base_url == "http://127.0.0.1:8765"
    assert sandbox_client.timeout_sec == 12.5
    assert sandbox_client.user_agent == "UA"

    values["JobPipeline"]["workbench_base_url"] = "https://example.test"
    assert (
        GengoWorkbenchClient.from_config(FakeConfig(values)).base_url
        == "https://example.test"
    )


def test_parse_job_details_extracts_upload_targets() -> None:
    html = """<html><body>
    <h1>Collection #9300 - Incomplete</h1>
    <script type="text/javascript">
    var uploader = new qq.FileUploader({
        element: document.getElementById('Filedata'),
        params: {"job_id" : "99890273", "valums": "true"},
        multiple: false,
        action: "https://gengo.com/t/ajax/upload_file/",
        allowedExtensions: ['txt', 'PDF'],
        onSubmit: function() {}
    });
    var evilUploader = new qq.FileUploader({
        params: {"job_id" : "666"},
        action: "https://evil.example/t/ajax/upload_file/",
        allowedExtensions: ['txt']
    });
    var badPathUploader = new qq.FileUploader({
        params: {"job_id" : "777"},
        action: "https://gengo.com/t/other/path",
        allowedExtensions: ['txt']
    });
    </script>
    </body></html>"""

    details = parse_job_details(html, "9300")
    assert details.is_file_job is True
    assert len(details.upload_targets) == 1
    target = details.upload_targets[0]
    assert target.job_id == "99890273"
    assert target.allowed_extensions == ("txt", "pdf")
    assert target.action_url == "https://gengo.com/t/ajax/upload_file/"


def test_upload_translated_file_validation(tmp_path) -> None:
    client = GengoWorkbenchClient(user_session="cookie", base_url=BASE_URL)
    target = UploadTarget(
        job_id="123",
        allowed_extensions=("txt",),
        action_url=f"{BASE_URL}/t/ajax/upload_file/",
    )

    # Missing file
    with pytest.raises(WorkbenchUploadError) as exc:
        client.upload_translated_file(target, tmp_path / "absent.txt")
    assert "File not found" in exc.value.title

    # Wrong extension
    bad_ext = tmp_path / "file.pdf"
    bad_ext.write_text("content", encoding="utf-8")
    with pytest.raises(WorkbenchUploadError) as exc:
        client.upload_translated_file(target, bad_ext)
    assert "Invalid extension" in exc.value.title


def test_upload_translated_file_success(tmp_path) -> None:
    file_path = tmp_path / "translation.txt"
    file_content = "Translated Japanese text."
    file_path.write_text(file_content, encoding="utf-8")

    target = UploadTarget(
        job_id="99890273",
        allowed_extensions=("txt",),
        action_url=f"{BASE_URL}/t/ajax/upload_file/",
    )

    def handler(request: requests.PreparedRequest) -> tuple[int, dict[str, str], bytes]:
        assert request.method == "POST"
        parts = urlsplit(request.url)
        assert parts.path == "/t/ajax/upload_file/"
        params = parse_qs(parts.query)
        assert params["job_id"] == ["99890273"]
        assert params["valums"] == ["true"]
        assert params["qqfile"] == ["translation.txt"]
        assert request.headers.get("X-Requested-With") == "XMLHttpRequest"
        assert request.headers.get("Content-Type") == "application/octet-stream"
        assert request.headers.get("Referer") == f"{BASE_URL}/t/jobs/details/34405904"
        assert request.body == file_content.encode("utf-8")
        return _json_response({"opstat": "ok", "msg": "Uploaded successfully"})

    adapter = CannedAdapter(handler)
    client = _client_for(adapter)
    res = client.upload_translated_file(target, file_path, collection_id="34405904")
    assert res["opstat"] == "ok"
    assert len(adapter.sent) == 1


def test_upload_translated_file_server_error(tmp_path) -> None:
    file_path = tmp_path / "translation.txt"
    file_path.write_text("Hello", encoding="utf-8")
    target = UploadTarget(
        job_id="99890273",
        allowed_extensions=("txt",),
        action_url=f"{BASE_URL}/t/ajax/upload_file/",
    )

    adapter = CannedAdapter(
        lambda _r: _json_response(
            {"opstat": "error", "msg": "You cannot submit this job."}
        )
    )
    client = _client_for(adapter)
    with pytest.raises(WorkbenchUploadError) as exc:
        client.upload_translated_file(target, file_path)
    assert "You cannot submit this job." in str(exc.value)


def test_upload_translated_file_login_redirect(tmp_path) -> None:
    file_path = tmp_path / "translation.txt"
    file_path.write_text("Hello", encoding="utf-8")
    target = UploadTarget(
        job_id="99890273",
        allowed_extensions=("txt",),
        action_url=f"{BASE_URL}/t/ajax/upload_file/",
    )

    adapter = CannedAdapter(
        lambda _r: (302, {"Location": "https://gengo.com/auth/form/login"}, b"")
    )
    client = _client_for(adapter)
    with pytest.raises(WorkbenchSessionDeadError):
        client.upload_translated_file(target, file_path)
