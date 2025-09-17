# Job Acceptance Engine Documentation

## Overview

The Job Acceptance Engine is a feature of GengoWatcher that automatically accepts jobs based on configurable criteria. It includes rate limiting, error handling, and retry mechanisms to ensure reliable operation.

## Configuration

The job acceptance engine is configured through the `[AutoAccept]` section in `config.ini`:

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
```

### Configuration Options

- `enabled`: Enable/disable auto job acceptance (true/false)
- `min_reward`: Minimum reward amount for auto acceptance
- `max_reward`: Maximum reward amount for auto acceptance
- `job_sources`: Comma-separated list of sources (rss, websocket)
- `accept_delay_min`: Minimum delay in seconds before accepting a job
- `accept_delay_max`: Maximum delay in seconds before accepting a job
- `browser_profile_path`: Path to browser profile for job acceptance (if needed)
- `notification_on_accept`: Show notification when a job is accepted
- `log_acceptance`: Log accepted jobs to a file

## Features

### Rate Limiting

The engine includes built-in rate limiting to prevent exceeding API limits. By default, it allows up to 30 job acceptances per minute.

### Error Handling and Retry

The engine implements retry mechanisms for failed acceptance attempts with exponential backoff.

### Job Filtering

Jobs are filtered based on:
- Reward range (min/max)
- Source (RSS, WebSocket)
- Additional criteria can be added as needed

### Logging

Accepted jobs are logged to `logs/accepted_jobs.log` when the `log_acceptance` option is enabled.

## Implementation Details

### JobAcceptanceEngine Class

The main class that handles job acceptance logic:

```python
class JobAcceptanceEngine:
    def __init__(self, config: AppConfig, logger: logging.Logger):
        # Initialize the engine with configuration and logger
    
    def is_job_eligible(self, job_data: Dict[str, Any]) -> bool:
        # Check if a job meets the auto-accept criteria
    
    async def accept_job(self, job_data: Dict[str, Any]) -> bool:
        # Attempt to accept a job with retry and rate limiting
    
    def get_stats(self) -> Dict[str, Any]:
        # Get statistics about job acceptance
```

### Integration with GengoWatcher

The engine is integrated with the main `GengoWatcher` class and automatically processes new jobs that meet the configured criteria.

## Commands

### acceptstats

Display job acceptance statistics:

```
acceptstats
```

Shows:
- Enabled status
- Number of accepted jobs
- Number of failed acceptances
- Rate limited requests
- Current request rate

## Future Enhancements

Planned improvements:
- Integration with browser automation for actual job acceptance
- Advanced filtering based on language pairs, job types, etc.
- Web UI integration for real-time monitoring
- Configurable rate limits per API endpoint