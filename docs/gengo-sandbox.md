# Local Gengo sandbox

`gengowatcher-gengo-sandbox` is a localhost reconstruction of the captured
Gengo translator web app. It is intended for deterministic browser, RSS,
WebSocket, acceptance, and workbench tests without touching production.

Run it from the repository root:

```bash
PYTHONPATH=src python3 -m gengowatcher.gengo_sandbox.main
```

Then open <http://127.0.0.1:8765/t/jobs/status/available/realtime>.

The default data reproduces the two available collections captured in
`scrape/browser_Archive [26-06-30 03-36-03].har`, including their collection,
order and internal job IDs; reward, units, language pair, source segments,
purpose, warning state and customer comment. The response structure follows
the captured `summary`, `jobs`, `pagination`, and `position_map` payloads.

## Useful endpoints

- `GET /t/jobs/status/available/realtime` — browser-scrapable available jobs
- `GET /t/jobs/details/{collection_id}` — details and Accept button
- `GET /t/workbench/{collection_id}` — functional translation workbench
- `GET /rss/available_jobs/{token}` — RSS discovery feed
- `WS /live-dashboard` — auth then `available_collection` events
- `POST /__sandbox__/reset` — restore captured fixtures
- `POST /__sandbox__/jobs` — seed a custom collection from JSON
- `POST /__sandbox__/events/available/{id}` — replay a WebSocket job event
- `POST /__sandbox__/collections/{id}/expire` — force captured expiry behavior
- `GET /__sandbox__/state` — inspect all state

The collection API implements captured `get`, `start`, `status`, `save`,
`decline`, and `submit` lifecycle routes. The workbench exposes its current
payload as `window.__GENGO_WORKBENCH_DATA__`, matching the browser worker's
accepted-workbench extractor.

Status polling follows the captured contract: while active it returns the
collection summary directly. Once its countdown expires it remains HTTP 200
and returns Gengo's captured `code: 3302`, `opstat: "critical"` response.
Job and collection activities, comments, flags, and per-segment edit state are
also stateful.

The captured CAT service surface is available for richer tests: segment
tokenization/translation, glossary lookup, TM matches, MT suggestions, and
suggestion flag/unflag routes. Custom jobs can seed `glossary_entries`,
`tm_matches`, and `mt_translation` through `POST /__sandbox__/jobs`.

Seeding a new available job immediately publishes its `available_collection`
event to connected `/live-dashboard` clients. The replay endpoint can emit any
existing collection again without changing its state.

The server binds to `127.0.0.1:8765` by default. It deliberately has no
production authentication and refuses a non-loopback `--host` by default. The
`--unsafe-expose` flag is required to acknowledge the risk of exposing it to a
network. Browser WebSocket connections must also present an Origin whose host
matches the loopback server host; non-browser CLI clients may omit Origin.

To let the browser worker accept sandbox job URLs, opt in on both sides:

```toml
[BrowserWorker]
sandbox_origin = "http://127.0.0.1:8765"
```

```bash
gengowatcher-browser-worker \
  --profile-path profiles/browser-worker \
  --browser-executable-path /usr/bin/chromium \
  --sandbox-origin http://127.0.0.1:8765
```

The origin must use `localhost`, an address in `127.0.0.0/8`, or `::1`, and
must match exactly. Private-network, link-local, metadata-service, and public
hosts are rejected. Production URL validation remains restricted to HTTPS URLs
on `gengo.com` and its subdomains.

## Real-browser acceptance test

The opt-in E2E test launches this ASGI app, a real persistent Chromium context,
and the browser worker acceptance flow:

```bash
GENGOWATCHER_RUN_BROWSER_E2E=1 \
GENGOWATCHER_BROWSER_EXECUTABLE=/usr/bin/chromium \
PYTHONPATH=src python3 -m pytest \
  tests/e2e/test_gengo_sandbox_browser.py -q
```

It navigates to a captured details page, clicks the real Accept button, waits
for the workbench URL, and extracts `window.__GENGO_WORKBENCH_DATA__` through
the production browser-worker extractor.
