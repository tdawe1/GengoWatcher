# Gengo Reverse Engineering - Safe Testing Guidelines

## 🚨 IMPORTANT: READ FIRST

This document outlines methods to safely analyze Gengo's rate limits and detection mechanisms. **All testing should be done conservatively to avoid account suspension.**

## Testing Philosophy

1. **Passive First**: Always start with monitoring without taking any actions
2. **Conservative Limits**: Assume limits are much lower than technical capabilities
3. **Gradual Approach**: Increase rates very slowly while monitoring for reactions
4. **Human Simulation**: Emulate human behavior patterns

## Phase 1: Passive Monitoring (No Risk)

### 1. Job Pattern Analysis
Run for 24-72 hours to understand:
- Job posting frequency and patterns
- Peak hours and volume
- Reward distribution
- Language pair availability

```bash
python scripts/analyze_gengo_patterns.py
```

### 2. Historical Log Analysis
Analyze existing logs for:
- CAPTCHA frequency patterns
- Error rates
- Acceptance success/failure ratios
- Time-based patterns

```bash
python scripts/analyze_logs.py
```

### 3. WebSocket Traffic Analysis
Monitor WebSocket messages:
- Message types and frequency
- Job notification patterns
- System heartbeat intervals

## Phase 2: Conservative Manual Testing (Low Risk)

### Test 1: Manual Acceptance Pattern
- Accept 1 job every 2 hours manually
- Monitor for CAPTCHAs
- Check if job quality changes
- Watch for any warnings

### Test 2: Automated Low-Frequency
Modify config.ini:
```ini
[AutoAccept]
enabled = true
min_reward = 5.00  # Set a reasonable minimum
max_reward = 50.00
accept_delay_min = 300  # 5 minutes
accept_delay_max = 1800  # 30 minutes
```

Run for 24 hours and analyze logs.

### Test 3: Gradual Increase
Every 3 days, slightly increase frequency:
- Week 1: 1 job per 6 hours
- Week 2: 1 job per 4 hours
- Week 3: 1 job per 2 hours
- Week 4: 1 job per hour (MAX RECOMMENDED)

## Phase 3: Pattern Detection (Monitor These Signs)

### Early Warning Signs
1. **Increased CAPTCHAs**
   - More than 1 CAPTCHA per hour
   - CAPTCHA type changes (v2 → v3 → hCaptcha)
   - Solving failures increase

2. **Rate Limiting**
   - HTTP 429 responses
   - Job acceptance timeouts
   - WebSocket disconnections

3. **Job Quality Changes**
   - Only low-paying jobs shown
   - Fewer job notifications
   - Delayed job postings

4. **Account Warnings**
   - Email notifications
   - Dashboard messages
   - UI changes/warnings

### Critical Signs (STOP IMMEDIATELY)
1. **HTTP 403/401 Errors**
   - Forbidden responses
   - Authentication failures
   - Session invalidation

2. **Account Restrictions**
   - Cannot view jobs
   - Acceptance disabled
   - Account locked

3. **Email Warnings**
   - Terms of Service notices
   - Automated activity warnings
   - Suspension threats

## Phase 4: Multi-Client Testing (Advanced)

If single client is stable, test multiple clients:

### Setup
```python
# Example: Multiple WebSocket connections
clients = [
    GengoWatcher(config1),
    GengoWatcher(config2),
    # ... more clients
]

# Each client needs:
# - Unique session (if possible)
# - Separate rate limiting
# - Coordinated acceptance logic
```

### Rules for Multi-Client
1. Never share sessions
2. Implement global rate limit across all clients
3. Add 5-10 second jitter between client actions
4. Monitor total account-level rate limits

## Detection Mechanisms Gengo Likely Uses

### 1. Time-Based Analysis
- Request frequency patterns
- Intervals between actions
- 24/7 activity vs human patterns
- Response times too consistent

### 2. Behavioral Analysis
- Always accepting highest paying jobs
- No browsing/viewing behavior
- Instant decision making
- Perfect CAPTCHA solving

### 3. Technical Signatures
- User-Agent patterns
- Header consistency
- Request timing
- Browser fingerprinting

### 4. Business Logic
- Acceptance rates vs completion rates
- Quality scores
- Customer feedback
- Rush hour patterns

## Safe Operating Parameters

### Conservative (Recommended)
- Max 1 job per hour
- 8-12 hour active window
- 70% acceptance rate (skip some jobs)
- Random delays (30s - 5min)
- Weekends off

### Moderate (Use with Caution)
- Max 2-3 jobs per hour
- 16 hour active window
- 80% acceptance rate
- Some manual mixing
- Occasional weekends

### Risky (Not Recommended)
- >5 jobs per hour
- 24/7 operation
- >90% acceptance rate
- Minimal delays
- No breaks

## Monitoring Script

Create a monitoring dashboard:
```python
# Monitor these metrics in real-time
metrics = {
    'jobs_per_hour': current_rate,
    'acceptance_rate': accepted/available,
    'captcha_rate': captchas/hour,
    'error_rate': errors/requests,
    'success_rate': successful_attempts/total_attempts
}

# Alert thresholds
alerts = {
    'jobs_per_hour': 5,  # Alert if > 5/hour
    'captcha_rate': 0.5,  # Alert if > 0.5/hour
    'error_rate': 0.1,   # Alert if > 10%
}
```

## Emergency Procedures

If you detect warnings:
1. **Immediately stop** all automation
2. **Wait 24-48 hours**
3. **Continue manual** use only
4. **Reduce rates** by 75% when restarting
5. **Monitor closely** for 1 week

Remember: It's better to be too conservative than lose your account.