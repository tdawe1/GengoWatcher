# Security Remediation Plan

Based on comprehensive codebase review (Jan 2026).

## Priority Legend
- **P0**: Critical - secrets exposure, auth bypass
- **P1**: High - resilience gaps, data integrity
- **P2**: Medium - hardening, best practices

---

## P0: Secrets Management

### Issue 1: Cleartext secrets in `config.ini`
**Files**: `config.ini`, `src/config.ini`, `src/gengowatcher/config.py`

**Current State**: Session cookies, API tokens, OAuth creds stored in plaintext.

**Remediation**:
1. Create `config.ini.example` with placeholder values only
2. Add `.env` support via `python-dotenv` for sensitive values
3. Migrate secrets to environment variables:
   ```bash
   GENGO_USER_ID=
   GENGO_USER_SESSION=
   GENGO_USER_KEY=
   GENGOWATCHER_API_TOKEN=
   GMAIL_CLIENT_ID=
   GMAIL_CLIENT_SECRET=
   GMAIL_REFRESH_TOKEN=
   ```
4. Update `AppConfig` to prefer env vars over config.ini for secrets
5. Remove `src/config.ini` from repo (rotate any exposed credentials)

### Issue 2: Static API bearer token
**Files**: `src/gengowatcher/web.py`

**Current State**: Single long-lived token, no rotation, no per-IP limits.

**Remediation**:
1. Add token expiry (configurable TTL, default 24h)
2. Implement token refresh endpoint
3. Add rate limiting per IP (e.g., 100 req/min)
4. Log all auth failures with IP/timestamp

### Issue 3: OAuth tokens in config
**Files**: `src/gengowatcher/email_monitor.py`, `src/gengowatcher/oauth_setup.py`

**Current State**: Refresh/access tokens + client secret in plaintext config.

**Remediation**:
1. Store OAuth tokens in OS keyring (via `keyring` package) or encrypted file
2. Never persist client_secret in config (use env var)
3. Add token encryption at rest if keyring unavailable

---

## P1: Network Resilience

### Issue 4: OAuth refresh lacks timeout/retry
**Files**: `src/gengowatcher/email_monitor.py`

**Remediation**:
```python
# Add to _ensure_valid_token()
async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
    for attempt in range(3):
        try:
            async with session.post(token_url, data=payload) as resp:
                ...
        except (aiohttp.ClientError, asyncio.TimeoutError):
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)
```

### Issue 5: Blocking RSS fetch
**Files**: `src/gengowatcher/watcher.py`

**Remediation**:
```python
# Wrap feedparser in thread with timeout
import concurrent.futures

def fetch_rss_with_timeout(url, timeout=30):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(feedparser.parse, url)
        return future.result(timeout=timeout)
```

### Issue 6: Single-shot cancellation
**Files**: `src/gengowatcher/job_cancellation_manager.py`

**Remediation**: Add retry logic (2-3 attempts) with backoff for transient failures.

---

## P2: Config Hardening

### Issue 7: Config schema mismatch
**Files**: `src/gengowatcher/main.py`, `src/gengowatcher/config.py`

**Current State**: CLI writes `[Credentials]`, runtime reads `[WebSocket]`.

**Remediation**:
1. Unify config sections or add migration logic
2. Validate config on startup and warn on unused sections
3. Document expected config schema

### Issue 8: Concurrent config writes
**Files**: `src/gengowatcher/config.py`

**Current State**: In-process lock only; multi-process writes can corrupt.

**Remediation**:
1. Use file-based locking (`fcntl.flock` or `portalocker`)
2. Or use atomic write pattern (write to temp, rename)

### Issue 9: Silent config repair
**Files**: `src/gengowatcher/config.py`

**Remediation**: Log all auto-repairs at WARNING level so users know their config was modified.

---

## Implementation Order

1. **Week 1**: P0 Issues 1-3 (secrets)
   - Create `config.ini.example`
   - Add env var support to `AppConfig`
   - Rotate any exposed credentials
   - Update `.gitignore` for `.env`

2. **Week 2**: P1 Issues 4-6 (resilience)
   - Add timeout/retry to OAuth refresh
   - Wrap feedparser in timeout
   - Add retry to cancellation

3. **Week 3**: P2 Issues 7-9 (hardening)
   - Fix config schema mismatch
   - Add file locking
   - Improve logging for config repairs

---

## Files to Create

### `config.ini.example`
```ini
[RSS]
url = https://gengo.com/t/jobs.rss
check_interval = 60
min_reward = 0.0

[WebSocket]
enabled = true
url = wss://live-dashboard.gengo.com/socket
; Set via GENGO_USER_ID env var
user_id = YOUR_USER_ID
; Set via GENGO_USER_SESSION env var
user_session = YOUR_SESSION
; Set via GENGO_USER_KEY env var
user_key = YOUR_KEY

[WebServer]
enabled = false
host = 127.0.0.1
port = 8080
; Set via GENGOWATCHER_API_TOKEN env var
auth_token = CHANGE_ME

[AutoAccept]
enabled = false
min_reward = 5.0
max_reward = 50.0

[Notifications]
enabled = true
sound = true

[EmailMonitor]
enabled = false
; OAuth credentials - set via environment variables:
; GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN
```

### `.env.example`
```bash
# Gengo credentials
GENGO_USER_ID=
GENGO_USER_SESSION=
GENGO_USER_KEY=

# API auth
GENGOWATCHER_API_TOKEN=

# Gmail OAuth (optional)
GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
GMAIL_REFRESH_TOKEN=
```

---

## Verification Checklist

- [ ] No secrets in git history (run `git log -p | grep -i "session\|token\|secret"`)
- [ ] `config.ini` loads secrets from env vars when present
- [ ] API token rotation works
- [ ] OAuth refresh handles timeouts gracefully
- [ ] RSS fetch doesn't block on slow feeds
- [ ] Config repairs are logged
