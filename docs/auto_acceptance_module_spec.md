# Auto-Acceptance Module Specification

## 1. Overview

This document specifies the implementation of the auto-acceptance module for GengoWatcher. The module will automatically open job links in a browser based on configurable criteria, providing an automated alternative to manual job acceptance.

## 2. Module Structure

### 2.1 Files

```
src/gengowatcher/
├── auto_accept.py          # Main auto-acceptance implementation
├── auto_accept_exceptions.py  # Exception classes
└── auto_accept_metrics.py  # Metrics collection (optional)
```

### 2.2 Dependencies

- `logging` - For logging functionality
- `random` - For delay calculation
- `time` - For delays and timing
- `threading` - For concurrent operations
- `configparser` - For configuration handling
- Existing GengoWatcher modules:
  - `config.py` - For accessing configuration
  - `ui.py` - For notifications (if needed)

## 3. Core Classes

### 3.1 AutoAcceptManager

Main class for managing auto-acceptance functionality.

#### Constructor

```python
def __init__(self, config: AppConfig, logger: logging.Logger)
```

**Parameters:**
- `config`: AppConfig instance for accessing configuration
- `logger`: Logger instance for logging

#### Public Methods

##### should_accept_job

```python
def should_accept_job(self, job_data: Dict[str, Any]) -> bool
```

Determines if a job should be auto-accepted based on configuration.

**Parameters:**
- `job_data`: Dictionary containing job information with keys:
  - `id`: Job ID
  - `title`: Job title
  - `reward`: Job reward (float)
  - `currency`: Currency code (string)
  - `url`: Job URL (string)
  - `timestamp`: Job timestamp (float)
  - `source`: Job source (string: "rss" or "websocket")

**Returns:**
- `bool`: True if job should be accepted, False otherwise

##### accept_job

```python
def accept_job(self, job_data: Dict[str, Any]) -> bool
```

Attempts to auto-accept a job.

**Parameters:**
- `job_data`: Dictionary containing job information (same format as should_accept_job)

**Returns:**
- `bool`: True if job was accepted, False otherwise

#### Private Methods

##### _setup_logging

```python
def _setup_logging(self)
```

Sets up logging for the auto-acceptance module.

##### _calculate_accept_delay

```python
def _calculate_accept_delay(self) -> float
```

Calculates a random delay before accepting a job.

**Returns:**
- `float`: Delay in seconds

##### _open_job_in_browser

```python
def _open_job_in_browser(self, job_data: Dict[str, Any]) -> bool
```

Opens job URL in browser with specified profile.

**Parameters:**
- `job_data`: Dictionary containing job information

**Returns:**
- `bool`: True if successful, False otherwise

##### _retry_with_backoff

```python
def _retry_with_backoff(self, func, max_retries=3, base_delay=1.0)
```

Executes a function with exponential backoff retry.

**Parameters:**
- `func`: Function to execute
- `max_retries`: Maximum number of retry attempts
- `base_delay`: Base delay in seconds

**Returns:**
- Result of the function or raises the last exception

##### _send_accept_notification

```python
def _send_accept_notification(self, job_data: Dict[str, Any])
```

Sends notification about job acceptance.

**Parameters:**
- `job_data`: Dictionary containing job information

##### _log_acceptance

```python
def _log_acceptance(self, job_data: Dict[str, Any])
```

Logs job acceptance to file.

**Parameters:**
- `job_data`: Dictionary containing job information

##### _send_critical_alert

```python
def _send_critical_alert(self, message: str)
```

Sends a critical alert.

**Parameters:**
- `message`: Alert message

### 3.2 Exception Classes

#### AutoAcceptError

Base exception for auto-acceptance errors.

#### BrowserNotFoundError

Raised when browser is not found.

#### NavigationError

Raised when navigation fails.

#### TransientError

Raised for transient errors that may be retried.

## 4. Configuration

### 4.1 New Configuration Section

The auto-acceptance feature adds a new `[AutoAccept]` section to config.ini:

```ini
[AutoAccept]
enabled = false
min_reward = 0.0
max_reward = 999999.0
job_sources = rss,websocket
accept_delay_min = 5
accept_delay_max = 30
browser_profile_path = 
notification_on_accept = true
log_acceptance = true
log_level = INFO
```

### 4.2 Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable/disable auto-acceptance globally |
| `min_reward` | float | `0.0` | Minimum reward for auto-acceptance |
| `max_reward` | float | `999999.0` | Maximum reward for auto-acceptance |
| `job_sources` | string | `rss,websocket` | Comma-separated list of job sources |
| `accept_delay_min` | integer | `5` | Minimum delay in seconds before accepting |
| `accept_delay_max` | integer | `30` | Maximum delay in seconds before accepting |
| `browser_profile_path` | string | `` | Path to browser profile (empty for default) |
| `notification_on_accept` | boolean | `true` | Notify when job is auto-accepted |
| `log_acceptance` | boolean | `true` | Log auto-acceptance events |
| `log_level` | string | `INFO` | Log level for auto-acceptance module |

## 5. Logging

### 5.1 Log Categories

| Category | Description |
|----------|-------------|
| `AUTO_ACCEPT_SYSTEM` | System-level events |
| `AUTO_ACCEPT_CONFIG` | Configuration validation and loading |
| `AUTO_ACCEPT_JOB_EVAL` | Job evaluation against acceptance criteria |
| `AUTO_ACCEPT_DELAY` | Delay calculation and timing events |
| `AUTO_ACCEPT_BROWSER` | Browser interaction and automation events |
| `AUTO_ACCEPT_NOTIFICATION` | Notification events |
| `AUTO_ACCEPT_ERROR` | Error conditions and exceptions |
| `AUTO_ACCEPT_RETRY` | Retry mechanism events |
| `AUTO_ACCEPT_SECURITY` | Security-related events |

### 5.2 Log Format

All auto-acceptance logs follow the format:
```
[{timestamp}] {log_level} - [AUTO_ACCEPT_{CATEGORY}] {message}
```

Example:
```
[2023-06-15 14:30:22,123] INFO - [AUTO_ACCEPT_JOB_EVAL] Job 12345 evaluated: reward=5.50, min_reward=3.00, max_reward=10.00, accepted=true
```

## 6. Error Handling

### 6.1 Exception Hierarchy

```
Exception
 +-- AutoAcceptError
      +-- BrowserNotFoundError
      +-- NavigationError
      +-- TransientError
```

### 6.2 Error Recovery

- Transient errors are retried with exponential backoff
- Critical errors disable auto-acceptance and send alerts
- Configuration errors are logged and auto-acceptance is disabled
- Browser automation errors fall back to manual notifications

## 7. Integration Points

### 7.1 With Watcher

The AutoAcceptManager integrates with the existing GengoWatcher:

1. In `main.py`, instantiate AutoAcceptManager alongside other components
2. In `watcher.py`, modify `_process_new_job` to check for auto-acceptance
3. If auto-acceptance is enabled and job meets criteria, call `accept_job`
4. If auto-acceptance fails, fall back to regular notification

### 7.2 With Configuration

AutoAcceptManager uses the existing AppConfig system:

1. Access configuration through `config.get("AutoAccept", "option")`
2. Validate configuration on initialization
3. Log configuration errors and disable feature if needed

### 7.3 With Logging

AutoAcceptManager integrates with the existing logging system:

1. Use `logger.getChild("autoaccept")` for module-specific logging
2. Respect existing log file rotation settings
3. Appear in TUI log display through existing mechanisms

## 8. Security Considerations

### 8.1 Input Validation

- Validate all job data before processing
- Sanitize log messages to prevent injection
- Validate configuration values

### 8.2 Secure Logging

- Never log sensitive information
- Validate browser profile paths
- Restrict browser automation to Gengo domains

### 8.3 Resource Management

- Implement timeouts for all operations
- Limit concurrent browser instances
- Clean up resources properly

## 9. Performance Considerations

### 9.1 Threading

Auto-acceptance operations run in separate threads to avoid blocking:

```python
# In watcher.py
accept_thread = threading.Thread(
    target=self._handle_auto_accept,
    args=(job_data,),
    daemon=True
)
accept_thread.start()
```

### 9.2 Resource Limits

- Limit concurrent browser automation processes
- Implement operation timeouts
- Use connection pooling where applicable

## 10. Testing

### 10.1 Unit Tests

Key areas to test:
- Exception handling
- Configuration validation
- Job evaluation logic
- Delay calculation
- Retry mechanisms
- Alerting functions

### 10.2 Integration Tests

Key areas to test:
- Configuration loading
- Job evaluation with real data
- Browser automation integration
- Error recovery scenarios
- Notification integration

### 10.3 Manual Tests

Key scenarios to test:
- Valid configurations
- Invalid configurations
- Error recovery
- Performance under load
- Edge cases

## 11. Monitoring and Metrics

### 11.1 Key Metrics

- Acceptance rate
- Success rate
- Error rate
- Average delay
- Retry rate

### 11.2 Metrics Collection

Metrics are collected through:
- Log analysis
- In-memory counters
- Periodic reporting (if implemented)

## 12. Example Usage

### 12.1 Basic Integration

```python
# In main.py
from gengowatcher.auto_accept import AutoAcceptManager

# During initialization
auto_accept_manager = AutoAcceptManager(config, logger)

# In watcher.py
if auto_accept_manager.should_accept_job(job_data):
    success = auto_accept_manager.accept_job(job_data)
    if not success:
        # Fall back to regular notification
        self.show_notification(...)
```

### 12.2 Configuration Example

```ini
[AutoAccept]
enabled = true
min_reward = 3.0
max_reward = 20.0
job_sources = websocket
accept_delay_min = 10
accept_delay_max = 45
browser_profile_path = /home/user/.mozilla/firefox/profile1
notification_on_accept = true
log_acceptance = true
log_level = DEBUG
```

## 13. Future Extensions

### 13.1 CAPTCHA Integration

Future versions may integrate with CAPTCHA solving services for jobs that require verification.

### 13.2 Advanced Filtering

Future versions may add more sophisticated filtering options:
- Language pair filtering
- Job type filtering
- Time-based acceptance rules

### 13.3 Machine Learning

Future versions may use ML to optimize acceptance criteria based on user behavior.