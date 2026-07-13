# Commits and Pull Requests

## Commit Message Style
- Conventional Commits: type(scope): summary. Example: `refactor(watcher): move implementation helpers into orchestration package`.
- Other examples from history: fix(tests): add legacy symbol shims, chore: bump version to 2.9.3, feat: ..., docs: ..., stealth: ...
- Acceptable types seen in history: refactor, fix, feat, chore, docs, stealth. Agent-authored commits are sometimes prefixed with [codex].
- Keep commits scoped to one logical change.
- Recent history is dominated by `refactor(watcher): ...` commits; keep future orchestration changes under that scope.

## Pull Request Requirements
- Describe the behavior change clearly.
- List validation commands actually run (pytest -q ..., make lint, make format, make build).
- Link related issues.
- UI/TUI changes should include a screenshot or short clip from assets/.
