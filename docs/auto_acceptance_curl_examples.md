# Auto-Acceptance Feature - curl Examples

These examples demonstrate how to test the auto-acceptance feature using curl commands with the GengoWatcher web API.

## 1. Configuration Management

### Get Current Auto-Accept Configuration
```bash
curl -X GET "http://localhost:8000/api/config/AutoAccept" \
  -H "Content-Type: application/json"
```

### Update Auto-Accept Configuration
```bash
curl -X PUT "http://localhost:8000/api/config/AutoAccept" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "min_reward": 3.0,
    "max_reward": 20.0,
    "job_sources": "websocket",
    "accept_delay_min": 10,
    "accept_delay_max": 45,
    "browser_profile_path": "/home/user/.mozilla/firefox/profile1",
    "notification_on_accept": true,
    "log_acceptance": true,
    "log_level": "DEBUG"
  }'
```

### Enable Auto-Accept
```bash
curl -X PUT "http://localhost:8000/api/config/AutoAccept/enabled" \
  -H "Content-Type: application/json" \
  -d '{"value": true}'
```

### Set Reward Range
```bash
curl -X PUT "http://localhost:8000/api/config/AutoAccept/min_reward" \
  -H "Content-Type: application/json" \
  -d '{"value": 5.0}'

curl -X PUT "http://localhost:8000/api/config/AutoAccept/max_reward" \
  -H "Content-Type: application/json" \
  -d '{"value": 15.0}'
```

## 2. Job Management

### Get Recent Jobs
```bash
curl -X GET "http://localhost:8000/api/jobs" \
  -H "Content-Type: application/json"
```

### Get Specific Job
```bash
curl -X GET "http://localhost:8000/api/jobs/12345" \
  -H "Content-Type: application/json"
```

### Simulate New Job (for testing auto-accept)
```bash
curl -X POST "http://localhost:8000/api/jobs/simulate" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "99999",
    "title": "TEST JOB: English > Japanese",
    "reward": 12.34,
    "currency": "USD",
    "url": "https://gengo.com/t/jobs/details/99999",
    "source": "websocket"
  }'
```

### Force Auto-Accept a Job
```bash
curl -X POST "http://localhost:8000/api/jobs/12345/accept" \
  -H "Content-Type: application/json"
```

## 3. Monitoring and Metrics

### Get Auto-Accept Status
```bash
curl -X GET "http://localhost:8000/api/autoaccept/status" \
  -H "Content-Type: application/json"
```

### Get Auto-Accept Metrics
```bash
curl -X GET "http://localhost:8000/api/autoaccept/metrics" \
  -H "Content-Type: application/json"
```

### Get Recent Auto-Accept Logs
```bash
curl -X GET "http://localhost:8000/api/autoaccept/logs?limit=50" \
  -H "Content-Type: application/json"
```

### Get Auto-Accept Logs by Category
```bash
curl -X GET "http://localhost:8000/api/autoaccept/logs?category=AUTO_ACCEPT_JOB_EVAL" \
  -H "Content-Type: application/json"
```

## 4. Error Handling and Recovery

### Get Recent Errors
```bash
curl -X GET "http://localhost:8000/api/autoaccept/errors?limit=10" \
  -H "Content-Type: application/json"
```

### Clear Error State
```bash
curl -X POST "http://localhost:8000/api/autoaccept/errors/clear" \
  -H "Content-Type: application/json"
```

### Retry Failed Job
```bash
curl -X POST "http://localhost:8000/api/autoaccept/jobs/12345/retry" \
  -H "Content-Type: application/json"
```

## 5. Testing and Diagnostics

### Run Auto-Accept Self-Test
```bash
curl -X POST "http://localhost:8000/api/autoaccept/test" \
  -H "Content-Type: application/json"
```

### Test Browser Automation
```bash
curl -X POST "http://localhost:8000/api/autoaccept/test/browser" \
  -H "Content-Type: application/json"
```

### Test Configuration Validation
```bash
curl -X POST "http://localhost:8000/api/autoaccept/test/config" \
  -H "Content-Type: application/json"
```

## 6. Notification and Alerting

### Send Test Notification
```bash
curl -X POST "http://localhost:8000/api/autoaccept/test/notification" \
  -H "Content-Type: application/json" \
  -d '{"message": "This is a test auto-accept notification"}'
```

### Get Notification Settings
```bash
curl -X GET "http://localhost:8000/api/autoaccept/notifications" \
  -H "Content-Type: application/json"
```

## 7. Security and Performance

### Get Security Status
```bash
curl -X GET "http://localhost:8000/api/autoaccept/security" \
  -H "Content-Type: application/json"
```

### Get Performance Metrics
```bash
curl -X GET "http://localhost:8000/api/autoaccept/performance" \
  -H "Content-Type: application/json"
```

## Example Response Formats

### Job Data
```json
{
  "id": "12345",
  "title": "Translate English to Japanese",
  "reward": 8.50,
  "currency": "USD",
  "url": "https://gengo.com/t/jobs/details/12345",
  "timestamp": 1623789012.345,
  "source": "websocket",
  "auto_accepted": true,
  "accept_timestamp": 1623789045.678
}
```

### Auto-Accept Metrics
```json
{
  "jobs_evaluated": 150,
  "jobs_accepted": 42,
  "acceptance_failures": 3,
  "retries_needed": 8,
  "average_delay": 22.5,
  "acceptance_rate": 0.28,
  "success_rate": 0.93,
  "retry_rate": 0.05
}
```

### Error Log Entry
```json
{
  "timestamp": "2023-06-15T14:30:22.123Z",
  "level": "ERROR",
  "category": "AUTO_ACCEPT_BROWSER",
  "message": "Failed to open job 12345 in browser: Browser not found",
  "job_id": "12345",
  "traceback": "..."
}
```

These curl examples provide a comprehensive interface for testing and managing the auto-acceptance feature in GengoWatcher. They allow for full control over configuration, job management, monitoring, and diagnostics.