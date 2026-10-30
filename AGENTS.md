# GengoWatcher Agent Guide

Agent-facing contributor guide. Detailed content lives in docs/agents/; this file is the table of contents.

## Project Overview
- [Overview](docs/agents/overview.md) - purpose, version, repo layout, agent rule sources.
- [Environment](docs/agents/environment.md) - Python version, runtime/dev deps, virtualenv setup.

## Running and Building
- [Run and Makefile](docs/agents/run-and-makefile.md) - launch the TUI/web/browser-worker, Makefile targets, firefox-debug flow.

## Coding Standards
- [Formatting and Style](docs/agents/formatting-and-style.md) - Black config, imports, typing, naming.
- [Code Organization](docs/agents/code-organization.md) - module layout, error handling, logging, config/state conventions.
- [Testing](docs/agents/testing.md) - pytest runner, fixtures, single-test commands, validation suggestions.

## Workflow
- [Commits and Pull Requests](docs/agents/commits-and-prs.md) - Conventional Commits style, PR requirements.
- [Editing Guidelines and Gotchas](docs/agents/gotchas.md) - small-diff rule, thread/async boundaries, known agent traps.

## Gengo Workbench Tasks
- [Workbench HTTP API](docs/agents/gengo-workbench-api.md) - browserless fetch/submit endpoints, auth, payload shapes, gotchas.

**Never submit a translation without the user reviewing it first.** Fetching and
translating is fine; `POST /t/workbench/collection/{cid}/submit` is irreversible, bills the
customer, and closes the collection's editing window. Show the user the source/target pairs
and wait for an explicit go-ahead on that specific job before submitting. "Translate this
job" is not permission to submit, and approval of an earlier job does not carry over. Use
`/save` alone to stage work for review.

## Other Contributor Docs
- docs/websocket-contract.md - WebSocket protocol reference.
- docs/prometheus-setup.md - Prometheus integration.
- docs/n8n-translation-workflow.md - n8n job pipeline, deadline monitor, and T-15 auto-submit rule.
- docs/SECURITY_REMEDIATION.md - security review and remediation history.
- docs/browser-worker-black-box-test-procedure.md - browser-worker manual test procedure.
- docs/plans/ - design plans and proposals.
