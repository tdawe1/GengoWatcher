# Auto-Acceptance Configuration Plan

## Overview
This document outlines the plan for adding configuration options for the auto-acceptance feature to GengoWatcher.

## 1. New Configuration Sections

### [AutoAccept] Section
We'll add a new `[AutoAccept]` section to the config.ini file with the following options:

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

## 2. Default Values

The default values will be:
- `enabled`: `false` (disabled by default for safety)
- `min_reward`: `0.0` (accept all jobs by default)
- `max_reward`: `999999.0` (accept all jobs by default)
- `job_sources`: `rss,websocket` (accept from both sources)
- `accept_delay_min`: `5` (minimum delay in seconds before accepting)
- `accept_delay_max`: `30` (maximum delay in seconds before accepting)
- `browser_profile_path`: `` (empty by default, uses system default browser)
- `notification_on_accept`: `true` (notify when job is auto-accepted)
- `log_acceptance`: `true` (log auto-acceptance events)

## 3. Validation Logic

The validation logic will include:
- Type validation for all configuration values
- Range validation for numeric values (min_reward, max_reward, delays)
- Format validation for paths
- Source validation (must be rss, websocket, or both)
- Logical validation (min_reward <= max_reward, accept_delay_min <= accept_delay_max)

## 4. Secure Storage of Sensitive Information

Since the auto-acceptance feature might require storing sensitive information like browser profile paths or API keys:
- Browser profile paths will be stored in plain text in the config file (as they're not sensitive)
- Any future sensitive information (like API keys) will be stored using keyring or similar secure storage
- Passwords or tokens will never be stored in the config file directly

## 5. Integration with Existing Config Management

The new configuration will integrate with the existing AppConfig class:
- Add the new section to DEFAULT_CONFIG
- Extend the validation logic in load_config()
- Ensure the new configuration is saved properly in save_config()

## 6. Migration Strategy for Existing Users

For existing users:
- On first run after the update, the new `[AutoAccept]` section will be automatically added to their config.ini with default values
- The application will detect missing sections and add them without overwriting existing configuration
- A message will be displayed to inform users of the new feature

## 7. Configuration Structure for config.py

The following structure will be added to the DEFAULT_CONFIG in config.py:

```python
"AutoAccept": {
    "enabled": False,
    "min_reward": 0.0,
    "max_reward": 999999.0,
    "job_sources": "rss,websocket",
    "accept_delay_min": 5,
    "accept_delay_max": 30,
    "browser_profile_path": "",
    "notification_on_accept": True,
    "log_acceptance": True,
}
```

## Implementation Steps

1. Update the DEFAULT_CONFIG in config.py
2. Add validation logic in load_config()
3. Test the new configuration with existing config files
4. Update documentation
5. Add command-line options for configuring auto-acceptance