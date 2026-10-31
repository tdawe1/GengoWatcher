# Gengo Workbench HTTP API

Browserless way to read a translator collection and (after review) submit work to it.
Reconstructed from the artifacts in `scrape/`; the client is `GengoWorkbenchClient` — see
[Client status](#client-status).

## Submission requires user review

**Never call the `submit` endpoint on your own initiative.** Fetching and translating is
fine. `POST /t/workbench/collection/{cid}/submit` is irreversible, bills the customer, and
ends the collection's editing window.

Required sequence:

1. Fetch and translate.
2. Show the user the source/target pairs and wait for an explicit go-ahead.
3. Only then `save`, then `submit`.

If the user asks for "translate this job" that is **not** permission to submit. Treat
approval as per-job and per-response; prior approval of an earlier job does not carry over.

`save` on its own is reversible and is the right way to stage work for review.

## Identifier: the URL number is a collection id

`https://gengo.com/t/workbench/34252746` — `34252746` is a **collection_id**, not a job id.
Job ids live at `jobs[].id` (typically an eight-digit number, a different space entirely).
Passing a job id to the collection endpoints returns nothing useful.

## Auth: one cookie, nothing else

```
Cookie: myG_myGSession_=<session>
Accept: application/json, text/plain, */*
Referer: https://gengo.com/t/workbench/<collection_id>
Origin: https://gengo.com                  # POST only
Content-Type: application/json;charset=utf-8   # POST only
```

There is **no** CSRF header, no bearer token, no API key. `myG_ci_csrf_token` exists in the
cookie jar but is `HttpOnly`, set only by the legacy PHP tier, and never sent by the
workbench app. `X-Requested-With` appears only on legacy `/t/ajax/*` endpoints, never on
`/t/workbench/*`. Do not add CSRF handling; it is not part of the contract.

Credential source: `[WebSocket].user_session` in `config.toml` (env `GENGO_USER_SESSION`),
which holds the `myG_myGSession_` value. See
[Credential traps](#credential-traps) before assuming a cookie is live.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/t/workbench/collection/{cid}?page=N` | Fetch a batch. Add `&specific_job_id=` for one job, `&filter=` when a filter tab is active. |
| GET | `/t/workbench/collection/{cid}/status` | Summary only, no `jobs`. Poll at 60 s while working. |
| POST | `/t/workbench/collection/{cid}/start` | Accept. Body `{"page":N,"token":"<reCAPTCHA Enterprise>"}`. |
| POST | `/t/workbench/collection/{cid}/save` | Write translations. Body below. |
| POST | `/t/workbench/collection/{cid}/submit` | Mark submitted. Body `{"page":N}`. |
| POST | `/t/workbench/collection/{cid}/decline` | Body `{"decline":99}`. |
| POST | `/t/workbench/collection/{cid}/job/{job_id}/flag` | Body `{"flag":N,"comment":"..."}`. |
| POST | `/t/workbench/job/segments/set_state` | Mark edited: `{job_id, is_edit_service, states:[{segment_id, is_edited}]}`. |
| POST | `/t/workbench/segment/translate` | Per-segment confirm: `{segment_id, author, target_content, tokenized_target, collection_id}`. |
| POST | `/t/workbench/mt/translate` | MT suggestion: `{text, lc_src, lc_tgt, job_id, segment_id}`. |
| POST | `/t/workbench/tm/matches/{TmID}` | TM lookup: `{source, previous_source, next_source}`. |
| POST | `/t/workbench/comment/{type}/{id}` | Body `{"comment":"..."}`. |

Source of truth for this table: `scrape/1app.js:6108-6122` (collection `$resource` actions),
`scrape/SegmentService.ts`, `scrape/JobService.ts`, `scrape/activityService.ts`.
`src/gengowatcher/gengo_sandbox/app.py` implements the same routes for local testing.

## Fetch response shape

```
{ "summary": {...}, "jobs": [ {...,"segments":[...]} ], "pagination": {"last":"1"}, "position_map": {...} }
```

Per segment the fields that matter:

```
segment_id        string (equals job id for single-segment jobs)
source_content    Japanese source
target_content    "" when untranslated; pre-filled when TM matched
tokenized_source  [{content, type, level}]  type: text | number_missing | ...
tokenized_target  null until translated; then carries the QA verdicts
matches           [{score, tm_source, tm_target}]  present only on TM-prefilled segments
last_author       e.g. "TM-1.00" when the fill came from translation memory
glossary, flag_id, hasErrors, hasWarnings
```

`summary.job_counts` is the state to assert on after a write: `not_submitted`,
`submitted`, `has_translation`, `has_errors`, `has_warnings`.

## Submitting is two calls

`save` writes the text, `submit` marks the job done. The text lives only in the `save`
body; `submit` carries no translation data.

```
POST /t/workbench/collection/{cid}/save
{"jobs":[{"id":<job_id>,"segments":[{"segment_id":"<segment_id>","target_content":"..."}]}]}

POST /t/workbench/collection/{cid}/submit
{"page":<N>}
```

`page` in the `submit` body is the page **after** the last batch you loaded. Fetch
`?page=1` and submit `{"page": 2}`. Neither call takes a query string — `collection_id` is
a `$resource` template parameter, so it is consumed by the URL path and never re-sent in
the body or query.

## Gotchas

**`{n}` tags are DO-NOT-TRANSLATE and are validated by the server.** Preserve the exact
multiset of `{1}`, `{2}`, `{/2}`, `{3}`… from the source. Adding or dropping one produces a
`type: "tag", level: "error"` on the segment, and **a single error blocks `submit`** — the
call fails with an opaque `{"opstat":"error","code":1,"title":"Sorry, something's gone
wrong"}`. Assert tag parity between source and target before saving.

**Warnings do not block submission; errors do.** After a successful translation the job
typically carries dozens of `misspelling` warnings on proper nouns (*Tokaido, Shinkansen,
Shin-Osaka, Yaesu, Touken Ranbu*, URLs, emails) plus `number_missing` where a source figure
was reformatted to an English convention. Gengo's tokenizer also mis-reads the ordinal
suffix — `th` in `December 7th` is flagged as a misspelling. Per the style rules in
`scripts/translate-gengo.sh`, `Month Dayth, Year` is the required form, so keep it and
ignore the warning. Fix real `level: "error"` entries; ignore the warnings.

**`unit_count` is not a segment count.** A collection can report `unit_count: 868` across
45 segments. Pricing units ≠ segments. Check `pagination.last` to learn how many batches
exist; `{"last":"1"}` means one batch and you have seen everything.

**Business errors arrive as HTTP 200.** A failed call returns
`{"opstat":"critical","code":3302,"title":"Collection expired","description":"..."}` with
status 200. Always inspect the body rather than trusting the status code.

**A workbench URL is only reachable for a collection you are actually working.** Expired or
declined collections answer with the expired/critical payload rather than the jobs.

## Credential traps

Two cookie jars exist and they drift apart. Before assuming either is live, test it
directly against the collection endpoint — a `GET` returning 200 with a `summary` body means
good; a redirect to `/auth/form/login` means the session is dead.

- `[WebSocket].user_session` in `config.toml` is the reliable one for the HTTP API.
- The browser profile cookie can be the stale one. Do not infer liveness from a cookie
  being present on disk, nor from its expiry timestamp.

The home page is a poor liveness probe: an authenticated and an anonymous fetch can return
byte-identical HTML. Probe the workbench endpoint itself.

The `myG_myGEE2` cookie rotates on every response and is not an auth credential.

## Why not the WebSocket

`wss://live-dashboard.gengo.com/` (see `docs/websocket-contract.md`) is for *job discovery*
— it broadcasts available work and updates countdown. It is not how you fetch or submit
translations, and `ws.gengo.com` does not resolve at all. Auth rejection there shows up as
a `1000 OK` close about a second after the auth frame.

## Attaching to a live browser is often unavailable here

The CachyOS Firefox build hard-locks remote debugging off:

```
/usr/lib/firefox/browser/defaults/preferences/cachyos.js
  pref("devtools.debugger.remote-enabled", false, locked);
```

No user pref or `user.js` overrides a locked default, so `make firefox-debug` and the
native browser listener cannot attach on that build. Point
`Paths.browser_debug_browser_path` at a stock Mozilla build to re-enable it.

Playwright is a fallback, not a clean one: its bundled Firefox is older than the system
build, so it refuses the profile until `compatibility.ini` `LastVersion` is patched, and
`headless=False` hangs on this box. Use the HTTP API instead.

## Client status

`GengoWorkbenchClient` in `src/gengowatcher/workbench_client.py` wraps these endpoints:
`fetch_collection` (all pages merged into a `WorkbenchCollection` of `WorkbenchJob` /
`WorkbenchSegment`), `get_status`, `save_segments`, `submit_collection` (sends
`{"page": last_page + 1}`), and `upload_translated_file` (submits file collections).
`from_config` reads the `myG_myGSession_` value from `[WebSocket] user_session`
(`GENGO_USER_SESSION`). Failures raise `WorkbenchError` or a subclass:
`WorkbenchSessionDeadError` (login redirect, 401/403), `WorkbenchExpiredError` (code 3302),
`WorkbenchFileCollectionError` (code 3009), `WorkbenchUploadError`, and
`WorkbenchValidationError`. `extract_gengo_tags`, `extract_triple_brackets`, and
`validate_segment_preservation` check `{n}` tag parity and `[[[...]]]` spans before anything
is staged.

Two HTML readers cover what the JSON endpoints do not:

- `list_incomplete_collections()` → `list[IncompleteCollection]`: `GET /t/dashboard`,
  parsing the "Incomplete jobs" section (collections you have accepted and not finished;
  rows link to `/t/jobs/details/{cid}`). Each item has `collection_id`, `title` (contents
  preview), `lang_pair`, `tier`, `unit_count`, `reward`, `url`. No section means an empty
  list. The acceptance reconciler uses it to find jobs accepted without a workbench
  `/start` call.
- `fetch_job_details(cid)` → `JobDetails`: `GET /t/jobs/details/{cid}`, giving `title`,
  `status` (e.g. `Incomplete`), `unit_count`, `reward`, `source_download_urls` (absolute
  `/download/source/<job_id>/` links on the client's origin only), `is_file_job`,
  `upload_targets` (`UploadTarget`: `job_id`, `allowed_extensions`, `action_url`), and
  `comments` (`CustomerComment`: `comment_id`, `author`, `posted_at`, plain `text`,
  `links`). Activity lines such as "Job accepted" are not comments. Comment text and
  links are untrusted customer content; never fetch external links.

Both send the session cookie with `allow_redirects=False`. A redirect to `/auth` or
`/login`, or 401/403, raises `WorkbenchSessionDeadError`; any other non-200 raises
`WorkbenchError`.

**File collections** return `{"opstat":"error","code":3009,...}` from
`GET /t/workbench/collection/{cid}` (`WorkbenchFileCollectionError`), but
`GET /t/workbench/collection/{cid}/status` still works for them. Use `/status` for the
deadline and the details page for source files, comments, and `upload_targets`.

Submitting a file collection is done via `client.upload_translated_file(target, path, collection_id=cid)`.
The endpoint is `POST /t/ajax/upload_file/?job_id=<job_id>&valums=true&qqfile=<filename>`
with headers `X-Requested-With: XMLHttpRequest`, `X-File-Name: <urlencoded filename>`,
`Content-Type: application/octet-stream`, and raw binary body. Returns `{"opstat": "ok"}` on
success or raises `WorkbenchUploadError` with the server error message.
`JobPipelineService` in `src/gengowatcher/orchestration/job_pipeline.py` is the consumer.
It submits only for a user-approved job, or for the n8n T-15 deadline rule described in
[docs/n8n-translation-workflow.md](../n8n-translation-workflow.md).
`JobAcceptanceEngine` in `src/gengowatcher/job_acceptance.py` still handles the separate
job-acceptance routes.