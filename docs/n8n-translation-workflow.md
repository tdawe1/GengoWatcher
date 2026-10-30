# n8n translation workflow

GengoWatcher, the Daweuchi event router, and n8n (on vps2) cover the whole life of an
accepted Gengo job: translate, review, notify the user, watch the deadline, submit, and
sort the files. The workflow definitions are in `ops/n8n/`.

```
GengoWatcher (PC)                      Daweuchi bus / router (PC)            n8n (vps2)
───────────────────                    ──────────────────────────            ──────────
job.accepted / pipeline.* ──webhook──▶ POST /events/workflows/gengo-events
  (live accept or dashboard reconcile)
                                        └─ rule forward-to-n8n ───────────▶ /webhook/gengo-events
                                                                              ├─ gengo_jobs Data Table
                                                                              ├─ Matrix room message      
/api/pipeline/commands ◀── rule gengo-commands ◀── POST /events/gengo/commands ◀┘ (start/checkpoint/submit/hold)
JobPipelineService
  fetch → translate (agent 1) → validate → /save draft → review (agent 2) → validate → /save final
  → REVIEW.md in <jobs_dir>/Active/<cid>_<slug>/ → pipeline.ready_for_review
```

## Files

| File | Purpose |
| --- | --- |
| `ops/n8n/gengo-setup-datatable.workflow.json` | `Gengo — 00 Setup Data Table` (`gengoWfSetup0001`): creates the `gengo_jobs` Data Table, or reuses it if it exists |
| `ops/n8n/gengo-matrix-alert.workflow.json` | `Gengo — 01 Matrix Alert` (`gengoWfMatrx0002`): sub-workflow that posts the message to the Matrix room *Gengo alerts* |
| `ops/n8n/gengo-job-pipeline.workflow.json` | `Gengo — 02 Job Pipeline & Deadline Monitor` (`gengoWfPipe00003`): receives events, updates the table, sends alerts, publishes commands, runs the deadline timers |
| `ops/n8n/gengo-approval-form.workflow.json` | `Gengo — 03 Review Approval Form` (`gengoWfAppr00004`): one-tap Approve or Hold form at `/form/gengo-approval` |
| `ops/n8n/deploy-to-n8n.sh` | Imports, publishes, and restarts n8n. Idempotent. It asks for confirmation and has a `--dry-run` mode |
| `src/gengowatcher/orchestration/job_pipeline.py` | `JobPipelineService`: the PC-side lifecycle |
| `src/gengowatcher/orchestration/acceptance_reconciler.py` | `AcceptanceReconciler`: finds accepted collections on the Gengo dashboard that GengoWatcher did not see accepted |
| `src/gengowatcher/workbench_client.py` | `GengoWorkbenchClient` ([API notes](agents/gengo-workbench-api.md)) |
| `~/Projects/daweuchi-local/automation/rules.toml` | Rule `gengo-commands`: `gengo/commands` → `POST http://127.0.0.1:8000/api/pipeline/commands` |

The workflows target n8n **2.45.5** (`docker.n8n.io/n8nio/n8n:2.45.5`). The one Code node
(`Normalize Event`) uses plain JS, with no `$env` and no `$evaluateExpression`, because 2.x
blocks both in Code nodes. Workflow, node, and credential IDs are fixed, so re-importing
updates the existing objects in place.

## Configuration

### GengoWatcher (`config.toml`)

```toml
[Webhooks]
outbound_enabled = true
outbound_urls = ["https://omp.daweuchi.com/events/workflows/gengo-events"]
outbound_auth_token = "<EVENT_PUBLISH_TOKEN>"          # bus bearer token
outbound_event_types = ["job.accepted", "pipeline.*"]  # fnmatch filter

[WebServer]
enabled = true
host = "127.0.0.1"
port = 8000
auth_token = "<GENGOWATCHER_API_TOKEN>"               # router uses this as Bearer

[JobPipeline]
enabled = true
auto_start_on_accept = false   # n8n sends the start command; true starts on the PC directly
jobs_dir = "~/Nextcloud/Gengo"  # must sit inside the Nextcloud desktop sync root
nextcloud_web_url = "https://files.daweuchi.com"
nextcloud_rel_dir = "Gengo"      # jobs_dir's path on the server, used for the job-folder links
translator_model = "omp:google-antigravity/gemini-4-argon"
translator_fallback_model = "opencode:openai/gpt-6-luna"
reviewer_model = "opencode:openai/gpt-5.6-terra"
reviewer_fallback_model = "opencode:openai/gpt-6-luna"
omp_profile = "gengo-translate"
agent_timeout_sec = 240.0
agent_cooldown_sec = 900      # skip an agent after a quota/rate-limit error
glossary_path = "data/gengo-glossary.json"
reconcile_interval_sec = 300  # dashboard acceptance reconcile; 0 disables
comment_check_interval_sec = 300  # poll tracked jobs for new customer comments; 0 disables
auto_revise_on_comments = true    # new comments auto-run patch + full review, hold for approval
stage_to_workbench = true
autosubmit_enabled = true      # set false to turn off the T-15 rule on the PC side
alert_minutes_before = 30
autosubmit_minutes_before = 15
```

Customer text is untrusted, so neither agent gets tools. Each model setting is a
`runner:model` spec (a bare model means opencode). If the primary fails (non-zero exit,
quota, rate limit, empty output), the role retries with its `*_fallback_model`.
`job.json` and `REVIEW.md` record the agent that actually answered.

A quota, rate-limit, or auth failure (including `QUOTA_EXHAUSTED`) also puts that
`runner:model` on cooldown until the `quotaResetTimeStamp` in the error text, or for
`agent_cooldown_sec` when the error has none. Later batches and jobs skip a cooling
agent and go straight to the next one. If every agent for the role is cooling, they are
all tried in order anyway. Other failures do not start a cooldown.

- `opencode:<model>` runs `opencode run` in an isolated work dir whose `opencode.json`
  (also passed as `OPENCODE_CONFIG`) is the deny-all `OPENCODE_DENY_CONFIG`; the prompt
  goes over stdin.
- `omp:<provider/model>` runs `omp -p --no-tools ...` under the dedicated `omp_profile`,
  with the prompt in a mode-0600 file that is deleted after the call. Do not point this
  at the default omp profile: it loads your user MCP servers (cloud, DNS, mail, deploy
  tools) into every request even with `--no-tools`. The pipeline refuses an empty or
  `default` profile and any profile with an `mcp.json`.

### omp profile setup

A named profile has its own auth, settings and user MCP config, and foreign discovery
sources (`~/.claude`, `~/.codex`, ...) stay off unless the profile's `enabledProviders`
lists them. The profile holds only the credentials the translator needs: currently
`google-antigravity` (the primary), plus the API-key providers `openrouter` and
`opencode-zen` as funded fallbacks. Add nothing else. OAuth providers whose refresh
tokens rotate can sign the default profile out once the copy refreshes, so prefer
API-key providers or providers whose refresh tokens do not rotate:

```bash
omp --profile gengo-translate config path      # creates ~/.omp/profiles/gengo-translate
omp auth export | jq '{version, credentials: [.credentials[]
  | select(.provider | IN("google-antigravity", "openrouter", "opencode-zen"))]}' \
  | omp --profile gengo-translate auth import -
```

Never add an `mcp.json` to this profile. omp writes customer text to the profile's
`logs/` directory: failed provider requests with their full body under
`logs/http-*-requests/*.json`, and the per-process `logs/omp.<date>.<pid>.log`. After
every omp call the pipeline deletes the regular files under
`~/.omp/profiles/<omp_profile>/logs/` that the call created or wrote. It does not touch
older files, anything outside that profile's `logs/`, or symlink targets, so logs from
your own use of the profile stay until you remove them.

`outbound_include_customer_content` stays `false`. The events carry metadata only:
`segments`, `source_text`, `target_content`, and similar keys are stripped before an
event leaves the PC.

### Router (`~/.config/daweuchi-automation/env`)

The `gengo-commands` rule needs `GENGOWATCHER_API_TOKEN` (the value of
`[WebServer] auth_token`) in the router env file, next to the existing
`N8N_WEBHOOK_TOKEN`. Add it yourself; the file is mode 600. Saving a valid `rules.toml`
restarts the router.

### n8n credentials

| ID | Name | Type | Value |
| --- | --- | --- | --- |
| `daweuchiWebhookHdr` | Daweuchi Webhook Header Token | Header Auth | name `X-Daweuchi-Token`, value `N8N_WEBHOOK_TOKEN` |
| `daweuchiEventBusBr` | Daweuchi Event Bus Bearer Token | Bearer Auth | `EVENT_PUBLISH_TOKEN` |
| `matrixNotifyBot0` | Matrix notify bot (@journal) | Bearer Auth | `as_token` of `notify.yaml`; already exists (created by the trading deploy), not imported by this script |

Create these in the editor with exactly these IDs and names, or run
`deploy-to-n8n.sh --with-credentials`. That option reads the two values from the
environment and sends them over ssh stdin, so they never appear in argv or on screen.

### Matrix alerts

Alerts go to the private Matrix room **Gengo alerts** (`!lfpd8yvk6tHZY0_IbrhrQPHP3sFMH2Q6I_GSuXgGGiM`) on
`matrix.daweuchi.com`. They are sent by the existing send-only appservice user
`@journal:daweuchi.com` (`/docker/matrix/data/appservices/notify.yaml` on vps1, also used by
the trading journal), which has the per-room display name "Gengo". No new account,
appservice or Tuwunel restart is needed.

The sub-workflow `Build Matrix Message` turns the Markdown `message` from the callers
into `m.room.message` content: `body` keeps the Markdown text, and `formatted_body` is HTML
with `[text](url)` links, `**bold**` and line breaks converted. `silent: true` sends an
`m.notice`. `Send to Matrix` does
`PUT /_matrix/client/v3/rooms/{roomId}/send/m.room.message/{txnId}` with the n8n
credential `matrixNotifyBot0` (Bearer = the appservice `as_token`). The transaction ID is
`gengo-<execution>-<item>-<referenceId>`, so n8n retries are idempotent. A caller may pass
`matrixRoomId` to post somewhere else.

To invite someone else, use Element as a room admin (`@thomas:daweuchi.com` has power 100).

## Acceptance detection

GengoWatcher records an acceptance live when the browser's workbench `/start` call
succeeds (`browser.workbench.start_response`). That misses some jobs:

- File jobs are accepted on `/t/jobs/details/{cid}` and never call workbench `/start`.
- Jobs accepted from another device, or while the watcher was down, are never seen.

`AcceptanceReconciler` closes the gap. Every `reconcile_interval_sec` (first run a few
seconds after startup) it reads the "Incomplete jobs" section of the Gengo translator
dashboard (`/t/dashboard`). Each collection listed there that the state does not already
mark accepted goes through the normal acceptance path, so it emits `job.accepted` with
`acceptance_source = "dashboard_reconcile"`, and auto-start, webhooks and n8n behave
exactly as for a live acceptance. The Matrix alert then ends with
`(detected on the Gengo dashboard)`. The reconciler runs only when `[JobPipeline]
enabled` is true; `reconcile_interval_sec = 0` turns it off. A dead session logs one
warning per transition and the loop keeps polling.

## File jobs

File collections answer the workbench collection endpoint with code 3009, so they have
no segments. The pipeline no longer needs a hand-written `job_hint` for them:

- Source download URLs come from the job details page (`/t/jobs/details/{cid}`), plus
  any URLs in the hint. Only `gengo.com` URLs are downloaded.
- Deadline (`deadline_epoch`, `seconds_left`, `allotted_seconds`) comes from
  `/t/workbench/collection/{cid}/status`, which works for file collections.
- Title, unit count and reward come from the details page; the hint is a fallback.

The translated files are uploaded to Gengo via the details page upload endpoint
(`/t/ajax/upload_file/?job_id=<id>&valums=true&qqfile=<filename>`). Uploading is the final
submission (sending the file to the customer). The pipeline handles this on user
approval (Approve link) or automatically at T-15.

## Customer comments

The pipeline reads customer comments from the details page for every job. Activity
lines such as "Job accepted" are dropped.

- `job.json` stores them as `customer_comments`. `REVIEW.md` lists them under
  `## Customer comments` (author, time, text, links), before the corrections, so read it
  before approving.
- The translator, repair and reviewer prompts include them in a delimited block marked
  as untrusted context. Agents must never follow instructions in them.
- Links in comments are marked "external link — not fetched". The pipeline never
  downloads them (for example a gigafile.nu link); open them yourself if needed.
- Events and Matrix carry only `comments_count`, never comment text.

### New comments after review or submission

`CommentReconciler` polls every tracked job in `ready_for_review`,
`needs_attention`, `submitted`, or archived-as-Submitted every
`comment_check_interval_sec` (default 300; `auto_revise_on_comments = false` or
an interval of 0 disables it). `job.json` records `seen_comment_ids`, seeded
from the comments the first pass already consumed, so only genuinely new
comments trigger work:

1. The PC emits `pipeline.comments_detected` (`new_comments_count` only) and
   n8n sends a 💬 Matrix alert. Comment text never leaves the PC.
2. The reviewer runs again over every segment with the new comments as
   untrusted context: it patches only the segments the comments require, then
   the full review pass re-validates tags, brackets, and glossary.
3. Changed segments are staged with `/save` (file jobs rewrite their translated
   files), `REVIEW.md` and `translation/revision-<n>.json` are rewritten, and
   the job returns to `ready_for_review` with `revision_count` incremented.
   Archived Submitted jobs move back to `Active/` first.
4. Revisions always hold for explicit approval: `auto_submit_pending` is
   cleared and nothing resubmits on its own. Approve as usual, or let the
   T-15 deadline rule submit. A manual `{"command": "revise", ...}` runs the
   same check on demand.

## Glossary and terms to verify

Proper nouns are the most likely error. For example, 黄島 is Ōshima in Goto City, not
Kuroshima or Kijima. Two safeguards address them:

- **Glossary.** `glossary_path` (default `data/gengo-glossary.json`, relative to the
  working directory) is loaded for every job. A missing file means an empty glossary; an
  invalid one logs a warning and is ignored. Format, UTF-8 JSON:

  ```json
  [{"source": "黄島", "target": "Ōshima", "note": "Island in Goto City (おうしま); not Kuroshima/Kijima"}]
  ```

  A plain `{"source term": "target term"}` object also works. Entries whose source term
  appears in the job are given to the translator, repair and reviewer prompts as
  required renderings. After review, every final segment whose source contains a
  glossary term but whose text lacks the target (case- and diacritic-insensitive, so
  `Oshima` matches `Ōshima`) is recorded in `glossary_warnings` and listed in
  `REVIEW.md` under `## Glossary warnings`. Warnings do not block the job.
- **Terms to verify.** The reviewer lists the proper nouns (places, people,
  organizations, products) and kanji readings it cannot confirm with high confidence.
  They are stored as `uncertain_terms` in `job.json` and listed in `REVIEW.md` under
  `## Terms to verify`. Add confirmed renderings to the glossary.

`pipeline.ready_for_review` carries `uncertain_terms_count` and
`glossary_warnings_count`; Matrix shows each count only when it is non-zero.

## Event contract (GengoWatcher → n8n)

GengoWatcher POSTs `{event_id, event_type, created_at, payload}` to the bus. The router
forwards the whole bus event (`{id, topic, source, payload: <that envelope>}`) to the
webhook. `Normalize Event` accepts the router shape, a raw envelope, and either one
wrapped in the n8n Webhook item. `Acknowledge Router` responds `{"ok": true}` before any
other node runs, so the router's 30 s HTTP timeout never waits on a Wait node.

| `event_type` | Payload keys used | n8n action |
| --- | --- | --- |
| `job.accepted` | `collection_id`/`id`, `title`, `lc_src`, `lc_tgt`, `reward`, `unit_count`, `url`, `acceptance_source` | mints a 32-hex approval token (Crypto node), upserts `status=accepted`, sends a Matrix alert (noting dashboard-reconciled acceptances), publishes `start` |
| `pipeline.started` | `collection_id`, `deadline_epoch`, `seconds_left`, `alert_minutes_before`, `autosubmit_minutes_before`, `approval_token`, `workbench_url`, `nextcloud_url` | upserts `status=translating` plus the deadline columns, then arms the deadline monitor |
| `pipeline.ready_for_review` | `segment_count`, `corrections_count`, `review_summary`, `has_errors`, `validation_errors`, `requires_manual_upload`, `comments_count`, `revision_count`, `uncertain_terms_count`, `glossary_warnings_count`, `nextcloud_url`, `approval_token` | upserts `ready_for_review` (`needs_attention` when there are errors), sends a Matrix alert with the non-zero comment/term/glossary counts and Approve/Hold/Nextcloud/Workbench links |
| `pipeline.comments_detected` | `new_comments_count`, `state`, `workbench_url` | records `lastEvent`, sends a 💬 Matrix alert; the PC starts the revision itself |
| `pipeline.submitted` | `submit_reason`, `auto_submitted` | upserts `status=submitted`, sends a Matrix alert |
| `pipeline.archived` | `outcome`, `archived_dir` | upserts `status=archived`, sends a Matrix alert |
| `pipeline.failed`, `pipeline.submit_failed`, `pipeline.submit_refused`, `pipeline.submit_deferred`, `pipeline.revision_failed` | `reason`, `error`, `error_type`, `seconds_left` | records `lastEvent`, sends a `⚠️ Gengo Pipeline Alert` |
| `pipeline.held` | — | upserts `hold=true` |
| any other event (`pipeline.deadline_warning`, `pipeline.auto_submit_skipped`, …) | — | records `lastEvent` only |

Events whose collection ID is not numeric are dropped at `Valid Collection ID?`.

## Command contract (n8n → GengoWatcher)

n8n POSTs to `https://omp.daweuchi.com/events/gengo/commands` (Bearer
`EVENT_PUBLISH_TOKEN`, header `X-Event-Source: n8n-gengo`). The router rule
`gengo-commands` matches `payload.command` in
`start|submit|hold|checkpoint|archive|status|accept_and_start` and a numeric
`payload.collection_id`, then POSTs the payload unchanged to
`http://127.0.0.1:8000/api/pipeline/commands`. Each command node retries up to 3 times,
5 s apart. Every command is idempotent on the PC.

| Sent by | Body |
| --- | --- |
| `job.accepted` | `{"command": "start", "collection_id", "approval_token", "job_hint": {title, reward, lang_pair, word_count, url}}`. The hint is optional; the PC fills gaps from the details page and `/status` |
| T-30 | `{"command": "checkpoint", "collection_id"}`: the PC re-reads live `/status` and emits `pipeline.deadline_warning` |
| T-15 | `{"command": "submit", "collection_id", "reason": "deadline"}` |
| Approve form | `{"command": "submit", "collection_id", "reason": "approved", "approval_token"}` |
| Hold form | `{"command": "hold", "collection_id", "reason": "user_hold", "approval_token"}` |

## `gengo_jobs` Data Table

Columns: `collectionId`, `title`, `langPair`, `reward` (number), `unitCount` (number),
`status`, `hold` (boolean), `deadlineEpoch` (number), `deadlineIso`, `alertAtIso`,
`submitAtIso`, `approvalToken`, `workbenchUrl`, `nextcloudUrl`, `reviewSummary`,
`submitReason`, `archivedDir`, `lastEvent`. Every write is an upsert keyed on
`collectionId`, except the form's `update`.

`status` takes these values: `accepted` → `translating` → `ready_for_review` /
`needs_attention` → `approved` → `submitted` → `archived`.

## Deadline monitor

After `pipeline.started`, the pipeline execution itself waits on the timers. Waits longer
than 65 s are stored in the n8n database and survive restarts.

1. **Arm**: only when `deadlineEpoch > 0` and the row has no monitor for this deadline yet
   (`alertAtIso` empty, or the stored `deadlineEpoch` differs by more than 120 s). A
   repeated `pipeline.started`, for example from an idempotent re-start, does not create
   duplicate timers. To re-arm by hand, clear `alertAtIso` on the row.
2. **Wait until `deadline − alert_minutes_before`** (T-30). If the row is not
   `submitted` or `archived`, n8n publishes `checkpoint` and sends a Matrix alert: time left,
   status, hold flag, and Approve/Hold/Workbench links.
3. **Wait until `deadline − autosubmit_minutes_before`** (T-15). If the job is not
   submitted and not held, n8n sends a Matrix alert `🚨 Auto-Submitting` and publishes `submit`
   with `reason: "deadline"`. If the job is held, it sends a reminder to submit manually.

If the deadline is already past a timer, that Wait node resumes immediately.

The PC applies its own guards in `JobPipelineService.submit_job(reason="deadline")`:

- It refuses unless `[JobPipeline] autosubmit_enabled` is set.
- It skips held jobs (`pipeline.auto_submit_skipped`).
- If the job is still translating or reviewing, it defers (`pipeline.submit_deferred`)
  and submits as soon as the job reaches `ready_for_review`.
- It re-reads live `/status` and requires `seconds_left <= autosubmit_minutes_before * 60 + 120`.
- For file jobs, it fetches upload targets from the details page and uploads the translated file directly.
- It requires `has_errors == 0` and no blank segments before calling `/submit` with
  `{"page": last_page + 1}`.

## Approval form

The Matrix links open
`https://n8n.daweuchi.com/form/gengo-approval?collection_id=<cid>&token=<approval_token>&decision=<label>`.
The hidden fields and the dropdown are pre-filled from the query string (Form Trigger
v2.5 matches query keys to `fieldName`). `(` and `)` are percent-encoded so the Markdown
links in Matrix do not end early. Opening a link only renders the form, and
`ignoreBots` turns away link previewers. Nothing happens until **Confirm Decision** is
pressed.

On submit, the form looks up the row. If the token does not match `approvalToken`, it
sends a Matrix warning and no command. Otherwise:

- **Approve & Submit Now** sets `status=approved` and `hold=false`, then publishes
  `submit`/`approved` with the token.
- **Hold (Disable 15m Auto-Submit)** sets `hold=true`, then publishes `hold` with the
  token.

Either way n8n confirms in Matrix. The PC checks the token again with
`secrets.compare_digest`.

## File sorting

While it runs, a job lives in `<jobs_dir>/Active/<cid>_<slug>/`: `job.json`, `source/`,
`translation/` (`draft.json`, `review.json`, `final.json`, `translation.txt`, translated
`files/` for file jobs), and `REVIEW.md`. After submission or archive it moves to
`<jobs_dir>/<Outcome>/<YYYY-MM>/<cid>_<slug>/`, where `<Outcome>` is one of:

| Outcome | When |
| --- | --- |
| `Submitted` | the user approved it (`reason=approved`) |
| `Submitted-Auto` | the T-15 deadline rule submitted it (`reason=deadline`) |
| `Unsubmitted` | archived without submitting (`archive` command, `outcome=Unsubmitted`) |

## T-15 auto-submit vs the interactive review rule

`AGENTS.md` says interactive agents must never submit without the user reviewing that
specific job. That rule is unchanged. **No agent submits a job.** Submission happens only
in these cases:

- The user taps Approve, which counts as explicit per-job approval.
- The **user-configured T-15 deadline rule** fires. This is a standing instruction from
  the account owner, enabled by `[JobPipeline] autosubmit_enabled = true`, the n8n
  pipeline workflow being published, and the T-15 branch existing. Its purpose is to stop
  a finished, validated translation from expiring unsubmitted.

The rule is narrow. It fires only at `deadline − autosubmit_minutes_before`, only after
the T-30 Matrix warning offered Hold, only when the job is not on Hold, and only when the
PC's own guards pass: live deadline check, no workbench errors, no blank segments (or
unambiguous upload targets for file jobs). To turn it off, choose one:

- Set `autosubmit_enabled = false`. The PC then refuses with `pipeline.submit_refused`.
- Unpublish `gengoWfPipe00003`.
- Press Hold for that job.

Agents working in this repo must still not call `/submit`, send `submit` commands, or
change these settings on their own.

## Deployment

```sh
ops/n8n/deploy-to-n8n.sh --dry-run          # show every remote command
N8N_WEBHOOK_TOKEN=... EVENT_PUBLISH_TOKEN=... \
  ops/n8n/deploy-to-n8n.sh [--with-credentials] [--yes]
```

Steps:

1. Validate the JSON locally.
2. Copy the workflows into `n8n-n8n-1` on `vps2` over ssh stdin.
3. Optionally import the credentials.
4. `n8n import:workflow` each file.
5. `n8n publish:workflow` for all four workflows, Matrix first.
6. `docker compose restart n8n` in `/opt/n8n` and wait for `/healthz`.
7. Trigger the Data Table setup once.

`n8n execute --id=gengoWfSetup0001` cannot do the setup: in 2.45.5 the CLI `execute`
command does not load the data-table module and fails with "Data table node … module is
disabled". The setup workflow therefore also has a header-authenticated webhook,
`/webhook/gengo-setup-datatable`. The script calls it with `N8N_WEBHOOK_TOKEN`, or
through `publish-event workflows/gengo-setup-datatable '{}'`. Running it again returns
the existing table.

## Testing

- Router:
  `cd ~/Projects/daweuchi-local/automation && ./router.py check && GENGOWATCHER_API_TOKEN=dummy ./router.py dry-run gengo-commands event.json`
  with `event.json` = `{"topic": "gengo/commands", "payload": {"command": "start", "collection_id": "12345678"}}`.
  Expect `matches: True` and a POST to `/api/pipeline/commands`. A non-numeric ID or an
  unknown command gives `matches: False`.
- Offline n8n smoke test: run `docker.n8n.io/n8nio/n8n:2.45.5` with `--network none`. Add
  `/etc/hosts` entries that point `omp.daweuchi.com` and `files.daweuchi.com` at a local
  HTTPS mock, and set `NODE_TLS_REJECT_UNAUTHORIZED=0` in that throwaway container only.
  Then import dummy credentials and the four workflows, publish, and `n8n start`. POST
  router-shaped events to `/webhook/gengo-events`. Use small `alert_minutes_before` /
  `autosubmit_minutes_before` values in `pipeline.started` so the timers fire within
  seconds. Inspect the data with `n8n export:entities --includeExecutionHistoryDataTables=true`.
  Rows are encrypted with the instance key: `openssl enc -d -aes-256-cbc -md md5 -a -A -k <key>`.
- End to end against `gengo_sandbox`: point `[JobPipeline] workbench_base_url` at the
  sandbox origin (see `docs/gengo-sandbox.md`) before testing with real n8n. Never test
  submit against real Gengo.

## Gotchas

- Form Trigger answers `401` to bot user agents (`wget`, link unfurlers) when
  `ignoreBots` is on. Use a browser to test it.
- `pkill` does not stop n8n immediately while executions are running; graceful shutdown
  waits for them. Use `docker compose restart` so the new published version actually
  loads.
- `import:workflow` unpublishes the workflow and creates a new version. Always run
  `publish:workflow` and restart afterwards; the deploy script does both.
- The alert room ID is baked into `Build Matrix Message`; if the room is replaced, update
  `DEFAULT_ROOM` there (see [Matrix alerts](#matrix-alerts)).
