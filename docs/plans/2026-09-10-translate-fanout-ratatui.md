# Translate fan-out CLI + Ratatui integration plan (2026-09-10)

## What was added (Phase 0, no backend change)

- `scripts/translate-gengo.sh` — core fan-out: translate per Gengo Style Guide
  (American spelling, numbers, `Month Dayth, Year`, Oxford comma, headline caps,
  double quotes, no contractions, `[[[...]]]` preserved exactly, paragraph breaks
  matched), then a second review pass, one dir per run with
  `*.translation.txt`, `*.review.txt`, `*.final.txt`, `*.status`, `COMBINED.md`.
  Missing binary / auth / quota / timeout never fails hard: records `SKIPPED`
  and continues. Notifications via `notify-send` + sound + bell.
- `bin/gengo` — single-keypress wrapper. Interactive `gengo` with no args:
  `[F]` latest file in `~/Downloads` (`[Y]` use / `[N]` next / `[R]` rescan),
  `[T]` paste (end `Ctrl+D`), `[P]` clipboard, then `[Enter]` all / `[2]`
  opencode-only / `[3]` pick, then `[Y]/[N]` review. Non-interactive:
  `gengo --latest -y`, `gengo --list-downloads`, `gengo "text"`,
  `echo text | gengo`, `gengo --paste`. Resolves core as
  `bin/../scripts/translate-gengo.sh` with `$HOME`/`PATH` fallbacks.
- `make install-user` now also links `bin/gengo`.

Validate: `bash -n scripts/translate-gengo.sh bin/gengo`, `make build`,
`gengo --help`, `gengo --list-downloads 3`.

## Why Rust must not shell out to LLMs

- `CLAUDE.md` boundary: Python owns watcher/browser/persistence; Rust is an
  out-of-process loopback API consumer (`ApiClient` enforces http + loopback,
  bearer token from `GENGOWATCHER_API_TOKEN`, token redacted in `Debug`).
  Shelling out from Rust would duplicate auth/quota handling, break the
  sandbox/origin model, and bypass `unsafe_code = "forbid"`-friendly minimal deps
  (only crossterm/ratatui/reqwest-blocking/serde).
- `LiveWorker` is a blocking-poll thread (4s snapshot, 20s action timeout,
  backoff to 15s). A translate run is minutes (4 models x 2 phases x 300s):
  it must be an async backend job (202 + poll), never a blocking worker action.
- Privacy: `state.json` deliberately strips source/accepted text; webhooks omit
  customer content unless configured. Translations are customer content: they
  must not land in `state.json`, logs at INFO, or webhook payloads by default.

## Proposed backend (Python owns orchestration)

New service, e.g. `src/gengowatcher/orchestration/translate_fanout.py`
(or `translation_fanout.py` if it needs web-only reuse):

- Job model: `run_id (uuid7/time-sortable)`, `source_hash`, `kind (text/file-ref)`,
  `char_count`, per-model `{status: queued/running/ok/skipped/failed,
  bytes, ms, error}`, `created_at`, `finished_at`. Keep in memory +
  append-only JSONL audit under `data/translate-fanout/<run-id>/`; do NOT
  persist source text in `state.json`.
- Runner: `asyncio.create_subprocess_exec` (never `shell=True`), allowlisted
  binaries resolved at startup, bounded semaphore (default 2 models at once),
  per-phase timeout from `[TranslateFanout]` config (`models`, `timeout_s=300`,
  `out_dir`, `max_chars`, `allow_binary=false`). Reuse the bash SKIP patterns
  (402/payment, usage-limit/plus, `Failed to authenticate`, OAuth expiry) as
  `skipped`, distinct from `failed` (empty output, timeout, non-zero).
- Prompts: keep the exact Gengo instruction blocks from the scripts as
  versioned constants so CLI and API cannot drift.
- Files: reuse existing `/api/files/upload` + `StoredFileEntry`. Backend must
  NOT read `~/Downloads` directly (path containment). The "latest Downloads"
  heuristic stays CLI-only.
- REST (bearer auth, loopback only):
  - `POST /api/translate {text? | file_ref?, models?, with_review=true}`
    -> `202 {run_id}` (validate length, reject binary unless allowed).
  - `GET /api/translate` (list summaries, no source text by default;
    `?include_text=1` opt-in) and `GET /api/translate/{run_id}` (detail).
  - Events on `event_bus`: `translate.run.started/progress/completed`.
    Reuse bounded-queue, drop-on-slow-consumer semantics; `/ws/status`
    broadcasts progress, never full source unless explicitly subscribed.
- Config: `[TranslateFanout] enabled=false` default (opt-in, avoids surprise
  subprocess + LLM spend). Document in `config.toml.example`.

## Proposed Rust TUI (read first, submit later)

- Model (`model.rs`): `TranslateRun { id, input_preview (truncated),
  with_review, per-model status, finished, updated_at }`; extend
  `DashboardData` with `translate_runs: Vec<TranslateRunSummary>` OR fetch
  lazily to keep snapshot small. Detail type for selected run.
- API (`api.rs`): `start_translate()`, `list_translate_runs()`,
  `get_translate_run()`; reuse `bearer_auth`, `decode_response`, loopback
  validation. New tests mirror existing `command_posts_authenticated_json`
  style with `TcpListener` fixtures.
- Worker (`live.rs`): new `UiAction::StartTranslate {…}` /
  `UiAction::RefreshTranslate`; `execute_action` maps to the POST/GET above.
  Poll translate list only while the Translate view is active (or at a slower
  cadence) to avoid loading the 2s snapshot loop. Long runs poll by run_id;
  worker thread never blocks past snapshot timeout.
- View (`lib.rs`): new `View::Translate` (7th workspace, key `7`). Reuse
  `Confirmation` (`y/enter` confirm, `n/esc` cancel) and `pending_destructive`
  patterns. Keys: `t` from Jobs/Work copies selected job title/meta into a
  translate draft (must NOT imply acceptance — keep the
  `browser.workbench.start_response`-only `job.accepted` invariant visible in
  status text), `e` edit (if we add a draft buffer; else skip editing in v1),
  `enter` submit. Footer: append `t translate`. Compact mode (`<110x30`)
  gets the tab automatically via existing `View::ALL` iteration.
- Previews (`preview.rs` + `--render`): add deterministic translate-view
  fixture so `cargo run -- --render OUT` emits a screenshot for the PR
  (required by `docs/agents/commits-and-prs.md` for UI changes).

## Rollout (small diffs per `gotchas.md`)

1. Phase 0 (this commit): scripts + docs only, no runtime change.
2. Phase 1: backend service + REST + pytest (mocked subprocess), config
   example, no TUI.
3. Phase 2: Rust read-only Translate view + `cargo test` + clippy
   (`make test-ratatui`) + `--render` screenshot.
4. Phase 3: submit-from-TUI + WS progress. Each phase its own
   `feat(translate): …` commit with validation commands listed.

## Open questions

- Should review pass be skippable per-model (cost) or global only?
- Truncation limit for `input_preview` in list snapshots (e.g. 120 chars)?
- Retention/GC for `data/translate-fanout/` runs (age + count caps)?
