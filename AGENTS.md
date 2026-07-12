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

## Other Contributor Docs
- docs/websocket-contract.md - WebSocket protocol reference.
- docs/prometheus-setup.md - Prometheus integration.
- docs/SECURITY_REMEDIATION.md - security review and remediation history.
- docs/browser-worker-black-box-test-procedure.md - browser-worker manual test procedure.
- docs/plans/ - design plans and proposals.
