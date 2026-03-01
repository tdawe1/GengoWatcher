# Fixer Demo Parsing Test Design

**Goal:** Add a tiny unit test covering `_parse_job_title_fallback` behavior.

**Scope:** Test-only change in `tests/test_ui_textual_components.py`. No production code modifications.

**Approach (recommended):** Add a focused pytest that directly calls the helper with a few representative titles.

**Test cases:**
- Standard format: "JA→EN | 120 words" -> ("JA→EN", "120")
- Alternate separator: "EN-JA 350 words" -> ("EN→JA", "350")
- Missing/empty title -> ("??→??", "0")

**Notes:**
- Keep test unit-level (no Textual app boot).
- Use ASCII-only strings in test inputs.
