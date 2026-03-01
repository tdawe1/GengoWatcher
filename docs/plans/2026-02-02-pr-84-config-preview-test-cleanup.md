# PR 84 Config Preview Test Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the stray review text embedded in `test_config_preview_truncates_long_values` so the test is valid Python again.

**Architecture:** This is a test-only cleanup on the PR 84 branch (`test/config-preview`). The change is limited to removing the pasted review text between the config setup and app initialization, preserving the test name and existing ConfigPreview references.

**Tech Stack:** Python, pytest, Textual

---

### Task 1: Prepare isolated PR 84 workspace

**Files:**
- Modify: None (workspace setup only)

**Step 1: Create worktree on PR 84 branch**

Run:

```bash
git worktree add .worktrees/test-config-preview test/config-preview
```

Expected: Worktree created at `.worktrees/test-config-preview`.

**Step 2: Fast-forward to origin**

Run:

```bash
git pull --ff-only origin test/config-preview
```

Expected: Branch aligns to origin with the review text present.

**Step 3: Baseline test run**

Run:

```bash
python -m pytest -q
```

Expected: Fails during collection in `scripts/` due to missing modules; record and proceed with explicit user confirmation.

### Task 2: Remove pasted review text from the test

**Files:**
- Modify: `tests/test_dashboard_quadrants.py`

**Step 1: Locate the test**

Find:

```python
async def test_config_preview_truncates_long_values():
```

**Step 2: Remove the pasted review text**

Ensure the config creation closes cleanly and the app instantiation follows immediately:

```python
    config = create_mock_config(
        {
            "Paths": {"feed_url": "https://example.com/very/long/path/to/resource"},
        }
    )

    app = ConfigPreviewTestApp(config)
```

**Step 3: Keep test name and ConfigPreview usage unchanged**

Confirm the function name remains `test_config_preview_truncates_long_values` and references to `ConfigPreview` and `_render_config` are intact.

### Task 3: Verify targeted test (best-effort)

**Files:**
- Test: `tests/test_dashboard_quadrants.py`

**Step 1: Run the single test**

Run:

```bash
python -m pytest tests/test_dashboard_quadrants.py::test_config_preview_truncates_long_values -v
```

Expected: Pass, or fail for external dependency reasons noted in Task 1. Record results.

### Task 4: Commit (only if requested)

**Files:**
- Modify: `tests/test_dashboard_quadrants.py`

**Step 1: Commit cleanup**

```bash
git add tests/test_dashboard_quadrants.py
git commit -m "test: remove stray review text from config preview test"
```
