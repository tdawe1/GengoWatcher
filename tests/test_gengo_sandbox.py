from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import feedparser
import httpx
import pytest

from gengowatcher.gengo_sandbox import SandboxState, create_app
from gengowatcher.gengo_sandbox.app import (
    MAX_WEBSOCKET_CLIENTS,
    WEBSOCKET_QUEUE_SIZE,
    _websocket_origin_is_allowed,
)
from gengowatcher.gengo_sandbox.main import main


def make_client() -> httpx.AsyncClient:
    app = create_app(SandboxState())
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://sandbox"
    )


@pytest.mark.asyncio
async def test_workbench_html_redirects_available_collections() -> None:
    async with make_client() as client:
        response = await client.get("/t/workbench/34176080", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/t/jobs/details/34176080"
        assert "window.__GENGO_WORKBENCH_DATA__" not in response.text


@pytest.mark.asyncio
async def test_available_details_accept_and_workbench_payload_flow() -> None:
    async with make_client() as client:
        available = await client.get("/t/jobs/status/available/realtime")
        assert available.status_code == 200
        assert "/t/jobs/details/34176080" in available.text
        assert "US$1.20" in available.text

        details = await client.get("/t/jobs/details/34176080")
        assert details.status_code == 200
        assert 'id="accept"' in details.text

        accepted = await client.post(
            "/t/jobs/details/34176080/accept", follow_redirects=False
        )
        assert accepted.status_code == 303
        assert accepted.headers["location"] == "/t/workbench/34176080#!/"

        workbench = await client.get(accepted.headers["location"])
        assert workbench.status_code == 200
        assert "window.__GENGO_WORKBENCH_DATA__" in workbench.text

        payload = (await client.get("/t/workbench/collection/34176080?page=1")).json()
        assert payload["summary"]["status"] == "incomplete"
        assert payload["summary"]["allotted_seconds"] == 3600
        assert payload["jobs"][0]["segments"][0]["source_content"].startswith(
            "1.つける"
        )


@pytest.mark.asyncio
async def test_save_status_submit_and_reset_are_stateful() -> None:
    async with make_client() as client:
        await client.post("/t/workbench/collection/34176023/start")

        saved = (
            await client.post(
                "/t/workbench/collection/34176023/save",
                json={
                    "segments": [
                        {
                            "segment_id": "98937760",
                            "target_content": "A house spirit",
                        }
                    ]
                },
            )
        ).json()
        assert saved["jobs"][0]["segments"][0]["target_content"] == "A house spirit"
        assert saved["summary"]["job_counts"]["submittable"] == 1

        submitted = (
            await client.post("/t/workbench/collection/34176023/submit")
        ).json()
        assert submitted["summary"]["status"] == "reviewable"
        assert submitted["jobs"][0]["status"] == "submitted"
        assert (
            "/t/jobs/details/34176023"
            not in (await client.get("/t/jobs/status/available")).text
        )

        reset = await client.post("/__sandbox__/reset")
        assert reset.json() == {"ok": True, "collections": 2}
        current = (await client.get("/t/workbench/collection/34176023")).json()
        assert current["summary"]["status"] == "available"


@pytest.mark.asyncio
async def test_rss_and_websocket_expose_available_collection_contract() -> None:
    state = SandboxState()
    app = create_app(state)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://sandbox"
    ) as client:
        feed_response = await client.get("/rss/available_jobs/test-token")
        feed = feedparser.parse(feed_response.text)
        assert len(feed.entries) == 2
        assert feed.entries[0].link.endswith("/t/jobs/details/34176023")

    event = state.available()[0].event()
    assert event["type"] == "available_collection"
    assert event["collection"]["id"] == 34176023


@pytest.mark.asyncio
async def test_sandbox_state_publishes_live_available_events() -> None:
    state = SandboxState()
    create_app(state)
    queue = state.subscribe()
    try:
        item = state.add(
            {
                "collection_id": 9991,
                "job_id": 99901,
                "order_id": 89991,
                "source": "Live source",
                "reward": 9.99,
                "unit_count": 5,
            }
        )
        await state.publish(item.event())
        event = await asyncio.wait_for(queue.get(), timeout=0.1)
        assert event["collection"]["id"] == 9991
        assert event["collection"]["rewards"] == "9.99"
    finally:
        state.unsubscribe(queue)


@pytest.mark.asyncio
async def test_slow_subscriber_queue_stays_bounded_and_keeps_newest_event() -> None:
    state = SandboxState()
    queue = state.subscribe()
    try:
        for collection_id in range(WEBSOCKET_QUEUE_SIZE + 1):
            await state.publish({"collection_id": collection_id})
        assert queue.qsize() == WEBSOCKET_QUEUE_SIZE
        assert queue.get_nowait() == {"collection_id": 1}
        newest = None
        while not queue.empty():
            newest = queue.get_nowait()
        assert newest == {"collection_id": WEBSOCKET_QUEUE_SIZE}
    finally:
        state.unsubscribe(queue)


@pytest.mark.asyncio
async def test_seed_custom_job_and_decline_removes_it_from_discovery() -> None:
    async with make_client() as client:
        created = await client.post(
            "/__sandbox__/jobs",
            json={
                "collection_id": 9001,
                "job_id": 99001,
                "order_id": 80001,
                "source": "Local test source",
                "reward": 4.25,
                "unit_count": 10,
            },
        )
        assert created.status_code == 201
        assert (
            "/t/jobs/details/9001"
            in (await client.get("/t/jobs/status/available")).text
        )

        await client.post("/t/workbench/collection/9001/start")
        assert (await client.post("/t/workbench/collection/9001/decline")).json() == {}
        assert (
            "/t/jobs/details/9001"
            not in (await client.get("/t/jobs/status/available")).text
        )


@pytest.mark.asyncio
async def test_start_status_and_expiry_follow_captured_contract() -> None:
    async with make_client() as client:
        started = (
            await client.post(
                "/t/workbench/collection/34176080/start",
                json={"page": 2, "token": "local-captcha-token"},
            )
        ).json()
        assert started["summary"]["status"] == "incomplete"
        assert started["summary"]["seconds_left"] in {3599, 3600}
        assert started["jobs"][0]["translator"] == 789487
        assert started["jobs"][0]["is_editable"] is True

        status = (await client.get("/t/workbench/collection/34176080/status")).json()
        assert "summary" not in status
        assert status["order_id"] == 8012277
        assert status["status"] == "incomplete"

        expired = (await client.post("/__sandbox__/collections/34176080/expire")).json()
        assert expired == {
            "code": 3302,
            "description": (
                "Sorry, you have run out of time to complete this collection."
            ),
            "opstat": "critical",
            "title": "Collection expired",
        }
        assert (
            await client.get("/t/workbench/collection/34176080/status")
        ).json() == expired
        assert (
            await client.post(
                "/t/workbench/collection/34176080/save", json={"jobs": []}
            )
        ).json() == expired
        assert (
            await client.post("/t/workbench/collection/34176080/submit")
        ).json() == expired


@pytest.mark.asyncio
async def test_activity_comments_flags_and_segment_state_are_persistent() -> None:
    async with make_client() as client:
        activity = (
            await client.get(
                "/t/workbench/activity/collection/34176080?order_id=8012277"
            )
        ).json()[0]
        assert activity["id"] == 70615746
        assert activity["attachments"] is None
        assert activity["user_id"] == 1119138
        assert activity["user_type"] == "customer"

        assert (
            await client.post(
                "/t/workbench/comment/job/98938270",
                json={"comment": "Translator note"},
            )
        ).json() == {"opstat": "ok"}
        job_activity = (
            await client.get("/t/workbench/activity/job/98938270?tier=pro")
        ).json()
        assert job_activity[-1]["body"] == "Translator note"

        flagged = (
            await client.post(
                "/t/workbench/collection/34176080/job/98938270/flag",
                json={"flag": 1, "comment": "Wrong language"},
            )
        ).json()
        assert flagged == {"id": 1}
        payload = (await client.get("/t/workbench/collection/34176080")).json()
        assert payload["jobs"][0]["has_flag"] is True
        resolved = (
            await client.post(
                "/t/workbench/collection/34176080/job/98938270/flag/resolve",
                json={"flag": 1},
            )
        ).json()
        assert resolved == {"id": 1, "has_flag": False}

        states = [{"segment_id": "98938270", "is_edited": True}]
        saved_states = (
            await client.post(
                "/t/workbench/job/segments/set_state",
                json={
                    "job_id": 98938270,
                    "is_edit_service": False,
                    "states": states,
                },
            )
        ).json()
        assert saved_states == {"segments": states}
        assert (
            await client.get(
                "/t/workbench/job/segments/get_state",
                params={"job_id": 98938270, "is_edit_service": False},
            )
        ).json() == {"segments": states}
        assert (
            await client.post(
                "/t/workbench/logger",
                json={"type": "exception", "message": "local test"},
            )
        ).json() == {"opstat": "ok"}


@pytest.mark.asyncio
async def test_cat_glossary_memory_and_suggestion_endpoints() -> None:
    async with make_client() as client:
        created = await client.post(
            "/__sandbox__/jobs",
            json={
                "collection_id": 9100,
                "job_id": 99100,
                "order_id": 80100,
                "source": "A red house",
                "reward": 2.5,
                "unit_count": 3,
                "glossary_entries": [
                    {
                        "term": "house",
                        "translations": [
                            {"text": "maison", "definition": "A building"}
                        ],
                    }
                ],
                "tm_matches": [
                    {
                        "type": "tm",
                        "score": 95,
                        "source": "A red house",
                        "target": "Une maison rouge",
                        "sub_type": "tm",
                    }
                ],
                "mt_translation": "Une maison rouge (MT)",
            },
        )
        created_payload = created.json()
        assert created_payload["summary"]["has_tm"] is True
        assert created_payload["jobs"][0]["tm_id"] == 1

        glossary = (
            await client.get(
                "/t/workbench/glossary", params={"tm_id": 1, "segment_id": 99100}
            )
        ).json()
        assert glossary[0]["term"] == "house"

        tokens = (
            await client.post(
                "/t/workbench/segment/tokenize",
                json={
                    "glossary": glossary,
                    "source": "A red house",
                    "target": "Une maison rouge",
                    "lc_src": "en",
                    "lc_tgt": "fr",
                    "max_chars": 0,
                    "job_id": 99100,
                },
            )
        ).json()
        assert any(token["type"] == "glossary" for token in tokens["tokenized_source"])
        assert any(token["type"] == "glossary" for token in tokens["tokenized_target"])

        tm = (
            await client.post(
                "/t/workbench/tm/matches/1",
                json={"source": "A red house", "job_id": 99100},
            )
        ).json()
        assert tm["matches"][0]["score"] == 95
        mt = (
            await client.post(
                "/t/workbench/mt/translate",
                json={
                    "text": "A red house",
                    "lc_src": "en",
                    "lc_tgt": "fr",
                    "job_id": 99100,
                    "segment_id": "99100",
                },
            )
        ).json()
        assert mt == {
            "translated_text": "Une maison rouge (MT)",
            "provider": "sandbox",
            "flag_id": None,
        }

        await client.post("/t/workbench/collection/9100/start", json={"page": 1})
        translated = (
            await client.post(
                "/t/workbench/segment/translate",
                json={
                    "segment_id": "99100",
                    "author": [{"content": "manual"}],
                    "target_content": "Une maison rouge",
                    "tokenized_target": tokens["tokenized_target"],
                    "collection_id": 9100,
                },
            )
        ).json()
        assert translated["summary"]["job_counts"]["has_translation"] == 1

        flagged = (
            await client.post(
                "/t/workbench/flappy",
                json={
                    "job_id": 99100,
                    "segment_id": "99100",
                    "content_tgt": "Une maison rouge",
                    "suggestion_type": "tm",
                    "sub_type": "tm",
                },
            )
        ).json()
        assert flagged == {"id": 1}
        assert (
            await client.request(
                "DELETE",
                "/t/workbench/flappy/delete",
                json={"flag_id": flagged["id"]},
            )
        ).json() == {"deleted": True}


@pytest.mark.asyncio
async def test_invalid_lifecycle_mutations_return_conflict() -> None:
    async with make_client() as client:
        save = await client.post(
            "/t/workbench/collection/34176023/save",
            json={"segments": [{"target_content": "too early"}]},
        )
        assert save.status_code == 409
        assert "available state" in save.json()["detail"]

        submit = await client.post("/t/workbench/collection/34176023/submit")
        assert submit.status_code == 409

        await client.post("/t/workbench/collection/34176023/start")
        assert (
            await client.post("/t/workbench/collection/34176023/start")
        ).status_code == 200
        blank = await client.post("/t/workbench/collection/34176023/submit")
        assert blank.status_code == 409
        assert "without a translation" in blank.json()["detail"]

        await client.post("/t/workbench/collection/34176023/decline")
        for action in ("start", "save", "submit", "decline"):
            response = await client.post(
                f"/t/workbench/collection/34176023/{action}", json={}
            )
            assert response.status_code == 409, action
        translated = await client.post(
            "/t/workbench/segment/translate",
            json={
                "collection_id": 34176023,
                "segment_id": "98937760",
                "target_content": "resurrected",
            },
        )
        assert translated.status_code == 409
        stale_accept = await client.post(
            "/t/jobs/details/34176023/accept", follow_redirects=False
        )
        assert stale_accept.status_code == 409


@pytest.mark.asyncio
async def test_submitted_collection_cannot_be_changed_or_reaccepted() -> None:
    async with make_client() as client:
        await client.post("/t/workbench/collection/34176023/start")
        await client.post(
            "/t/workbench/collection/34176023/save",
            json={"segments": [{"target_content": "Complete translation"}]},
        )
        assert (
            await client.post("/t/workbench/collection/34176023/submit")
        ).status_code == 200
        for action in ("start", "save", "submit", "decline"):
            assert (
                await client.post(f"/t/workbench/collection/34176023/{action}", json={})
            ).status_code == 409
        assert (
            await client.post("/t/jobs/details/34176023/accept", follow_redirects=False)
        ).status_code == 409


@pytest.mark.asyncio
async def test_adversarial_custom_text_is_safe_in_html_and_inline_json() -> None:
    source = "</script><script>window.pwned=true</script>&\u2028\u2029"
    purpose = '" onmouseover="window.pwned=true'
    async with make_client() as client:
        await client.post(
            "/__sandbox__/jobs",
            json={
                "collection_id": 9200,
                "job_id": 99200,
                "source": source,
                "purpose": purpose,
            },
        )
        listing = (await client.get("/t/jobs/status/available")).text
        assert "&quot; onmouseover=&quot;window.pwned=true" in listing
        assert 'title="Japanese to English — &quot; onmouseover=' in listing
        assert 'title="Japanese to English — " onmouseover=' not in listing

        accepted = await client.post(
            "/t/jobs/details/9200/accept", follow_redirects=False
        )
        assert accepted.status_code == 303
        workbench = (await client.get(accepted.headers["location"])).text
        script_data = workbench.split("window.__GENGO_WORKBENCH_DATA__=", 1)[1].split(
            ";\n", 1
        )[0]
        assert "</script>" not in script_data.lower()
        assert "<" not in script_data
        assert ">" not in script_data
        assert "&" not in script_data
        assert "\u2028" not in script_data
        assert "\u2029" not in script_data
        assert (
            json.loads(script_data)["jobs"][0]["segments"][0]["source_content"]
            == source
        )


def test_websocket_origin_and_subscriber_bounds() -> None:
    class FakeWebSocket:
        def __init__(self, origin: str | None, host: str = "127.0.0.1:8765"):
            self.headers = {"host": host}
            self.url = SimpleNamespace(scheme="ws")
            if origin is not None:
                self.headers["origin"] = origin

    assert _websocket_origin_is_allowed(FakeWebSocket(None))
    assert _websocket_origin_is_allowed(FakeWebSocket("http://127.0.0.1:8765"))
    assert not _websocket_origin_is_allowed(FakeWebSocket("http://127.0.0.1:3000"))
    assert not _websocket_origin_is_allowed(FakeWebSocket("https://evil.example"))
    assert not _websocket_origin_is_allowed(FakeWebSocket("http://127.0.0.1:bad"))
    assert not _websocket_origin_is_allowed(
        FakeWebSocket("http://127.0.0.1:8765", host="127.0.0.1:bad")
    )
    assert not _websocket_origin_is_allowed(
        FakeWebSocket("http://localhost:8765", host="127.0.0.1:8765")
    )

    state = SandboxState()
    queues = [state.subscribe() for _ in range(MAX_WEBSOCKET_CLIENTS)]
    assert all(queue.maxsize == WEBSOCKET_QUEUE_SIZE for queue in queues)
    with pytest.raises(RuntimeError, match="too many"):
        state.subscribe()
    for queue in queues:
        state.unsubscribe(queue)


def test_cli_refuses_non_loopback_host_without_explicit_override() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--host", "0.0.0.0"])
    assert exc_info.value.code == 2

    with patch("gengowatcher.gengo_sandbox.main.uvicorn.run") as run:
        assert main(["--host", "0.0.0.0", "--unsafe-expose"]) == 0
    assert run.call_args.kwargs["host"] == "0.0.0.0"
