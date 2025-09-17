# Auto-Acceptance Module - Test Data and Scenarios

This document provides comprehensive test data and scenarios for the auto-acceptance module implementation.

## 1. Sample Job Data

### 1.1 Valid Job Data

```python
# Standard valid job data
valid_job_standard = {
    "id": "12345",
    "title": "Translate English to Japanese",
    "reward": 8.50,
    "currency": "USD",
    "url": "https://gengo.com/t/jobs/details/12345",
    "timestamp": 1623789012.345,
    "source": "websocket"
}

# RSS source job
valid_job_rss = {
    "id": "67890",
    "title": "Translate English to Spanish",
    "reward": 12.75,
    "currency": "USD",
    "url": "https://gengo.com/t/jobs/details/67890",
    "timestamp": 1623789012.678,
    "source": "rss"
}

# High reward job
valid_job_high_reward = {
    "id": "11111",
    "title": "Technical Translation - High Priority",
    "reward": 25.00,
    "currency": "USD",
    "url": "https://gengo.com/t/jobs/details/11111",
    "timestamp": 1623789012.111,
    "source": "websocket"
}

# Low reward job
valid_job_low_reward = {
    "id": "22222",
    "title": "Simple Translation - Low Priority",
    "reward": 3.50,
    "currency": "USD",
    "url": "https://gengo.com/t/jobs/details/22222",
    "timestamp": 1623789012.222,
    "source": "rss"
}
```

### 1.2 Invalid Job Data

```python
# Missing required fields
invalid_job_missing_fields = {
    "title": "Incomplete Job Data",
    "reward": 10.0,
    "url": "https://gengo.com/t/jobs/details/33333"
    # Missing id, currency, timestamp, source
}

# Invalid reward format
invalid_job_invalid_reward = {
    "id": "44444",
    "title": "Invalid Reward Job",
    "reward": "ten dollars",  # Should be numeric
    "currency": "USD",
    "url": "https://gengo.com/t/jobs/details/44444",
    "timestamp": 1623789012.444,
    "source": "websocket"
}

# Invalid URL
invalid_job_invalid_url = {
    "id": "55555",
    "title": "Invalid URL Job",
    "reward": 7.50,
    "currency": "USD",
    "url": "not a valid url",
    "timestamp": 1623789012.555,
    "source": "rss"
}

# Unknown source
invalid_job_unknown_source = {
    "id": "66666",
    "title": "Unknown Source Job",
    "reward": 9.00,
    "currency": "USD",
    "url": "https://gengo.com/t/jobs/details/66666",
    "timestamp": 1623789012.666,
    "source": "unknown_source"
}

# Malicious job data
malicious_job_data = {
    "id": "77777'; DROP TABLE jobs; --",
    "title": "<script>alert('XSS')</script>",
    "reward": -5.00,  # Negative reward
    "currency": "USD",
    "url": "javascript:alert('XSS')",
    "timestamp": "invalid_timestamp",
    "source": "../../../etc/passwd"
}
```

### 1.3 Boundary Condition Job Data

```python
# Minimum reward boundary
boundary_job_min_reward = {
    "id": "88888",
    "title": "Minimum Reward Job",
    "reward": 5.0,  # Exactly at minimum
    "currency": "USD",
    "url": "https://gengo.com/t/jobs/details/88888",
    "timestamp": 1623789012.888,
    "source": "websocket"
}

# Maximum reward boundary
boundary_job_max_reward = {
    "id": "99999",
    "title": "Maximum Reward Job",
    "reward": 20.0,  # Exactly at maximum
    "currency": "USD",
    "url": "https://gengo.com/t/jobs/details/99999",
    "timestamp": 1623789012.999,
    "source": "rss"
}

# Zero delay values
boundary_job_zero_delay = {
    "id": "00000",
    "title": "Zero Delay Job",
    "reward": 10.0,
    "currency": "USD",
    "url": "https://gengo.com/t/jobs/details/00000",
    "timestamp": 1623789012.000,
    "source": "websocket"
}
```

## 2. Sample Configuration Data

### 2.1 Valid Configuration Data

```ini
# Standard valid configuration
[AutoAccept]
enabled = true
min_reward = 5.0
max_reward = 20.0
job_sources = rss,websocket
accept_delay_min = 10
accept_delay_max = 30
browser_profile_path = /home/user/.mozilla/firefox/profile1
notification_on_accept = true
log_acceptance = true
log_level = INFO

# Minimal configuration
[AutoAccept]
enabled = true
min_reward = 0.0
max_reward = 999999.0
job_sources = rss
accept_delay_min = 5
accept_delay_max = 15
notification_on_accept = false
log_acceptance = false
log_level = WARNING

# WebSocket only configuration
[AutoAccept]
enabled = true
min_reward = 3.0
max_reward = 15.0
job_sources = websocket
accept_delay_min = 20
accept_delay_max = 60
browser_profile_path = /home/user/.config/google-chrome/Default
notification_on_accept = true
log_acceptance = true
log_level = DEBUG
```

### 2.2 Invalid Configuration Data

```ini
# Invalid enabled value
[AutoAccept]
enabled = invalid_boolean
min_reward = 5.0
max_reward = 20.0
job_sources = rss,websocket
accept_delay_min = 10
accept_delay_max = 30
notification_on_accept = true
log_acceptance = true
log_level = INFO

# Invalid reward range (min > max)
[AutoAccept]
enabled = true
min_reward = 20.0  # Greater than max_reward
max_reward = 5.0   # Less than min_reward
job_sources = rss,websocket
accept_delay_min = 10
accept_delay_max = 30
notification_on_accept = true
log_acceptance = true
log_level = INFO

# Invalid delay range (min > max)
[AutoAccept]
enabled = true
min_reward = 5.0
max_reward = 20.0
job_sources = rss,websocket
accept_delay_min = 30  # Greater than accept_delay_max
accept_delay_max = 10  # Less than accept_delay_min
notification_on_accept = true
log_acceptance = true
log_level = INFO

# Invalid job sources
[AutoAccept]
enabled = true
min_reward = 5.0
max_reward = 20.0
job_sources = invalid,source,values
accept_delay_min = 10
accept_delay_max = 30
notification_on_accept = true
log_acceptance = true
log_level = INFO

# Invalid notification/log values
[AutoAccept]
enabled = true
min_reward = 5.0
max_reward = 20.0
job_sources = rss,websocket
accept_delay_min = 10
accept_delay_max = 30
notification_on_accept = invalid_value
log_acceptance = invalid_value
log_level = INVALID_LEVEL

# Empty configuration section
[AutoAccept]
# All values missing
```

### 2.3 Edge Case Configuration Data

```ini
# Extremely large reward values
[AutoAccept]
enabled = true
min_reward = 0.0
max_reward = 999999.99
job_sources = rss,websocket
accept_delay_min = 1
accept_delay_max = 300
notification_on_accept = true
log_acceptance = true
log_level = INFO

# Zero delay values
[AutoAccept]
enabled = true
min_reward = 5.0
max_reward = 20.0
job_sources = rss,websocket
accept_delay_min = 0
accept_delay_max = 0
notification_on_accept = true
log_acceptance = true
log_level = INFO

# Negative delay values (should be corrected)
[AutoAccept]
enabled = true
min_reward = 5.0
max_reward = 20.0
job_sources = rss,websocket
accept_delay_min = -5
accept_delay_max = -1
notification_on_accept = true
log_acceptance = true
log_level = INFO

# Equal delay values
[AutoAccept]
enabled = true
min_reward = 5.0
max_reward = 20.0
job_sources = rss,websocket
accept_delay_min = 15
accept_delay_max = 15
notification_on_accept = true
log_acceptance = true
log_level = INFO
```

## 3. Test Scenarios

### 3.1 Normal Operation Scenarios

#### Scenario 1: Standard Auto-Acceptance Workflow
```
Description: Test the standard workflow where a job meets all criteria and is auto-accepted
Preconditions:
  - AutoAccept enabled = true
  - Job reward within configured range
  - Job source in configured sources
  - Valid browser profile path
Steps:
  1. Configure AutoAccept with standard settings
  2. Create a valid job within reward range and source
  3. Call should_accept_job() with the job data
  4. Call accept_job() with the job data
  5. Verify job is opened in browser
  6. Verify notification is sent
  7. Verify acceptance is logged
Expected Results:
  - should_accept_job() returns True
  - accept_job() returns True
  - Browser opens with job URL
  - Notification is displayed
  - Acceptance is logged
```

#### Scenario 2: Job Outside Reward Range
```
Description: Test that jobs outside the configured reward range are not auto-accepted
Preconditions:
  - AutoAccept enabled = true
  - Valid configuration with specific reward range
Steps:
  1. Configure AutoAccept with min_reward=5.0, max_reward=15.0
  2. Create a job with reward=3.0 (below minimum)
  3. Call should_accept_job() with the job data
  4. Create a job with reward=20.0 (above maximum)
  5. Call should_accept_job() with the job data
Expected Results:
  - should_accept_job() returns False for both jobs
  - No browser interaction
  - No notifications
  - No logging of acceptance
```

#### Scenario 3: Invalid Job Source
```
Description: Test that jobs from sources not in the configured list are not auto-accepted
Preconditions:
  - AutoAccept enabled = true
  - Configured to accept only RSS jobs
Steps:
  1. Configure AutoAccept with job_sources=rss
  2. Create a WebSocket job
  3. Call should_accept_job() with the job data
Expected Results:
  - should_accept_job() returns False
  - No browser interaction
  - No notifications
  - No logging of acceptance
```

### 3.2 Error Handling Scenarios

#### Scenario 4: Browser Not Found
```
Description: Test behavior when configured browser is not found
Preconditions:
  - AutoAccept enabled = true
  - Valid job data
  - Invalid browser profile path
Steps:
  1. Configure AutoAccept with invalid browser profile path
  2. Create a valid job
  3. Call accept_job() with the job data
  4. Verify error handling
Expected Results:
  - accept_job() returns False or raises BrowserNotFoundError
  - Appropriate error logged
  - Notification sent about failure (if configured)
  - System falls back to regular notification
```

#### Scenario 5: Navigation Error
```
Description: Test behavior when browser navigation fails
Preconditions:
  - AutoAccept enabled = true
  - Valid job data
  - Valid browser profile path
Steps:
  1. Configure AutoAccept with valid settings
  2. Mock browser navigation to fail
  3. Create a valid job
  4. Call accept_job() with the job data
  5. Verify error handling
Expected Results:
  - accept_job() returns False or raises NavigationError
  - Appropriate error logged
  - Notification sent about failure (if configured)
  - Retry mechanism attempted (if configured)
  - System falls back to regular notification
```

#### Scenario 6: Configuration Error
```
Description: Test behavior when configuration is invalid
Preconditions:
  - Invalid AutoAccept configuration
Steps:
  1. Create configuration with invalid values
  2. Initialize AutoAcceptManager
  3. Verify error handling
Expected Results:
  - AutoAcceptManager handles invalid configuration gracefully
  - Appropriate warnings logged
  - Auto-acceptance disabled
  - System continues to operate with regular notifications
```

### 3.3 Edge Case Scenarios

#### Scenario 7: Boundary Conditions
```
Description: Test behavior with boundary condition values
Preconditions:
  - AutoAccept configured with boundary values
Steps:
  1. Configure with min_reward=max_reward
  2. Create job with reward exactly at boundary
  3. Call should_accept_job()
  4. Configure with accept_delay_min=accept_delay_max
  5. Call _calculate_accept_delay()
Expected Results:
  - Jobs at exact boundaries are handled correctly
  - Delay calculation with equal min/max works correctly
```

#### Scenario 8: Concurrent Operations
```
Description: Test behavior with multiple concurrent job evaluations
Preconditions:
  - AutoAccept enabled
  - Valid configuration
Steps:
  1. Create multiple threads evaluating different jobs
  2. Verify thread safety
  3. Verify no race conditions
Expected Results:
  - All jobs evaluated correctly
  - No data corruption
  - Thread-safe operations
```

#### Scenario 9: Resource Exhaustion
```
Description: Test behavior under resource constraints
Preconditions:
  - System under resource pressure
Steps:
  1. Simulate low memory conditions
  2. Simulate high CPU load
  3. Process auto-acceptance requests
  4. Verify graceful degradation
Expected Results:
  - System handles resource constraints gracefully
  - Auto-acceptance may fail but doesn't crash
  - Appropriate errors logged
  - System continues to operate
```

### 3.4 Security Scenarios

#### Scenario 10: Malicious Input
```
Description: Test behavior with malicious input data
Preconditions:
  - AutoAccept enabled
Steps:
  1. Create job data with malicious content (SQL injection, XSS, etc.)
  2. Call should_accept_job() with malicious data
  3. Call accept_job() with malicious data
  4. Verify input validation
Expected Results:
  - Malicious input is properly sanitized/validated
  - No security vulnerabilities exploited
  - Appropriate errors logged
  - System continues to operate safely
```

#### Scenario 11: Path Traversal
```
Description: Test behavior with path traversal attempts in configuration
Preconditions:
  - AutoAccept configuration with path values
Steps:
  1. Configure with malicious path traversal values
  2. Verify path validation
  3. Attempt to access restricted files
Expected Results:
  - Path traversal attempts are blocked
  - Only valid paths are accepted
  - Appropriate errors logged
  - System security maintained
```

## 4. Performance Test Data

### 4.1 Load Testing Data

```python
# Generate large dataset for load testing
def generate_load_test_jobs(count=1000):
    """Generate a large number of test jobs for load testing"""
    jobs = []
    sources = ["rss", "websocket"]
    
    for i in range(count):
        job = {
            "id": f"load_test_{i:06d}",
            "title": f"Load Test Job {i}",
            "reward": round(5.0 + (i % 16), 2),  # Rewards from 5.0 to 20.0
            "currency": "USD",
            "url": f"https://gengo.com/t/jobs/details/load_test_{i:06d}",
            "timestamp": 1623789012.000 + i,
            "source": sources[i % 2]
        }
        jobs.append(job)
    
    return jobs

# Generate 10,000 test jobs
load_test_jobs = generate_load_test_jobs(10000)
```

### 4.2 Stress Test Data

```python
# Generate stress test data with extreme values
stress_test_configurations = [
    {
        "name": "High Frequency",
        "config": {
            "accept_delay_min": 0,
            "accept_delay_max": 1
        }
    },
    {
        "name": "Long Delays",
        "config": {
            "accept_delay_min": 300,
            "accept_delay_max": 600
        }
    },
    {
        "name": "Wide Reward Range",
        "config": {
            "min_reward": 0.0,
            "max_reward": 999999.99
        }
    }
]
```

## 5. Test Execution Matrix

### 5.1 Test Coverage Matrix

| Feature | Unit Tests | Integration Tests | Performance Tests | Security Tests | Edge Case Tests |
|---------|------------|-------------------|-------------------|----------------|-----------------|
| Exception Handling | ✓ | ✓ |   | ✓ | ✓ |
| Configuration Validation | ✓ | ✓ |   | ✓ | ✓ |
| Job Evaluation Logic | ✓ | ✓ |   | ✓ | ✓ |
| Delay Calculation | ✓ |   | ✓ |   | ✓ |
| Browser Automation | ✓ | ✓ |   | ✓ | ✓ |
| Retry Mechanism | ✓ |   |   |   | ✓ |
| Notifications | ✓ | ✓ |   |   |   |
| Logging | ✓ | ✓ |   | ✓ |   |
| Error Recovery | ✓ | ✓ |   |   | ✓ |
| Concurrency |   |   | ✓ |   | ✓ |
| Resource Management |   |   | ✓ |   | ✓ |

This comprehensive test data and scenarios provide a solid foundation for thoroughly testing the auto-acceptance module implementation. The data covers normal operations, error conditions, edge cases, security concerns, and performance considerations.