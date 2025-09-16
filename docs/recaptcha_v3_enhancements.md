# reCAPTCHA v3 Integration Documentation

## Overview

This document describes the enhanced reCAPTCHA v3 detection and handling capabilities in GengoWatcher. The improvements include robust site key and action extraction from HTML content, fallback behaviors, and optional browser automation fallback for token generation.

## Configuration Options

The following new configuration options have been added to the `[Captcha]` section of `config.ini`:

```ini
[Captcha]
# ... existing options ...
skip_on_v3_extraction_failure = true
recaptcha_v3_fallback_site_key = 6Lc6BAAAAAAAAAChqR2QwNcAAAAA
recaptcha_v3_default_action = job_acceptance
enable_browser_automation_fallback = false
```

### Option Details

1. `skip_on_v3_extraction_failure` (boolean, default: `true`)
   - When `true`, the system will skip reCAPTCHA v3 solving if site key extraction fails
   - When `false`, the system will use the fallback site key

2. `recaptcha_v3_fallback_site_key` (string, default: `6Lc6BAAAAAAAAAChqR2QwNcAAAAA`)
   - Fallback site key to use when extraction fails and `skip_on_v3_extraction_failure` is `false`

3. `recaptcha_v3_default_action` (string, default: `job_acceptance`)
   - Default action name to use when action extraction fails

4. `enable_browser_automation_fallback` (boolean, default: `false`)
   - When `true`, enables browser automation fallback for reCAPTCHA v3 token generation
   - Requires Selenium WebDriver and Chrome browser to be installed

## Implementation Details

### Site Key Extraction

The system attempts to extract the reCAPTCHA v3 site key from HTML content using multiple methods:

1. Data attributes (`data-sitekey`)
2. JavaScript `grecaptcha.execute()` calls
3. JavaScript `grecaptcha.ready()` calls
4. Variable assignments (`recaptcha_site_key`)

### Action Extraction

The system attempts to extract the reCAPTCHA v3 action from JavaScript code:

1. Action parameter in `grecaptcha.execute()` calls
2. Action properties in JavaScript objects

### Fallback Behavior

When extraction fails:

1. If `skip_on_v3_extraction_failure` is `true`, skip reCAPTCHA v3 solving
2. If `skip_on_v3_extraction_failure` is `false`, use the fallback site key
3. If action extraction fails, use the default action

### Browser Automation Fallback

When enabled, the browser automation fallback can generate reCAPTCHA v3 tokens by:

1. Loading the job page in a headless browser
2. Executing the reCAPTCHA v3 challenge via JavaScript
3. Returning the generated token

## Testing

Unit tests are provided in `tests/test_recaptcha_v3_extraction.py` covering:

1. Site key extraction from various HTML patterns
2. Action extraction from JavaScript code
3. Fallback behavior when extraction fails

To run the tests:
```bash
cd /path/to/GengoWatcher
python -m pytest tests/test_recaptcha_v3_extraction.py -v
```

## Logging

The system provides detailed logging for reCAPTCHA v3 operations:

- Site key extraction success/failure
- Action extraction success/failure
- Fallback behavior activation
- Browser automation usage (when enabled)