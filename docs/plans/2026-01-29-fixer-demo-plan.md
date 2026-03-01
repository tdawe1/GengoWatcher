# Fixer Demo Test Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a small unit test for `_parse_job_title_fallback` without changing production code.

**Architecture:** Pure unit test calling the helper function directly, asserting the tuple output for common title formats and empty input.

**Tech Stack:** Python, pytest.

---

### Task 1: Add unit test for `_parse_job_title_fallback`

**Files:**
- Modify: `tests/test_ui_textual_components.py`

**Step 1: Write the failing test**

```python
def test_parse_job_title_fallback_cases():
    from gengowatcher.ui_textual import _parse_job_title_fallback

    assert _parse_job_title_fallback("JA→EN | 120 words") == ("JA→EN", "120")
    assert _parse_job_title_fallback("EN-JA 350 words") == ("EN→JA", "350")
    assert _parse_job_title_fallback("") == ("??→??", "0")
```

**Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_ui_textual_components.py::test_parse_job_title_fallback_cases -q`
Expected: FAIL if test not yet added or mismatched output.

**Step 3: Write minimal implementation**

No production code changes expected. Ensure test expectations match the helper behavior.

**Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_ui_textual_components.py::test_parse_job_title_fallback_cases -q`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_ui_textual_components.py
git commit -m "test(ui): cover job title fallback parsing"
```
