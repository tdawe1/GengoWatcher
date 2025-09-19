# Auto-Acceptance Configuration

## Overview
GengoWatcher now includes an auto-acceptance feature that can automatically open job links based on configurable criteria. This feature is disabled by default and must be explicitly enabled by the user.

## Configuration

### [AutoAccept] Section
Add the following section to your `config.ini` file:

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

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | Boolean | `false` | Enable/disable auto-acceptance globally |
| `min_reward` | Float | `0.0` | Minimum reward to auto-accept (USD) |
| `max_reward` | Float | `999999.0` | Maximum reward to auto-accept (USD) |
| `job_sources` | String | `rss,websocket` | Comma-separated list of sources (`rss`, `websocket`) |
| `accept_delay_min` | Integer | `5` | Minimum delay in seconds before accepting |
| `accept_delay_max` | Integer | `30` | Maximum delay in seconds before accepting |
| `browser_profile_path` | String | `` | Path to browser profile for job acceptance |
| `notification_on_accept` | Boolean | `true` | Show notification when job is auto-accepted |
| `log_acceptance` | Boolean | `true` | Log auto-acceptance events |

### Validation Rules
1. `min_reward` must be less than or equal to `max_reward`
2. `accept_delay_min` must be less than or equal to `accept_delay_max`
3. `job_sources` must be a comma-separated list containing only `rss` and/or `websocket`
4. Delay values are capped at reasonable limits (0-300 seconds)

## Usage Examples

### Basic Auto-Acceptance
To enable auto-acceptance for all jobs:
```ini
[AutoAccept]
enabled = true
min_reward = 0.0
max_reward = 999999.0
```

### Reward-Based Filtering
To only auto-accept high-paying jobs:
```ini
[AutoAccept]
enabled = true
min_reward = 5.0
max_reward = 999999.0
```

### Source-Specific Acceptance
To only auto-accept jobs from WebSocket:
```ini
[AutoAccept]
enabled = true
job_sources = websocket
```

### Delayed Acceptance
To add a random delay between 10-60 seconds before accepting:
```ini
[AutoAccept]
enabled = true
accept_delay_min = 10
accept_delay_max = 60
```

## Security Considerations

1. **Disabled by Default**: The feature is disabled by default to prevent accidental usage.

2. **Transparency**: All auto-acceptance actions are logged and can trigger notifications.

3. **Delay Mechanism**: Random delays help mimic human behavior and reduce the risk of detection.

4. **User Control**: Users have complete control over which jobs are auto-accepted through configuration.

## Best Practices

1. Start with the feature disabled and test with notifications only
2. Use reward filtering to avoid accepting low-paying jobs
3. Set appropriate delays to mimic human behavior
4. Monitor logs to ensure the feature is working as expected
5. Regularly review which jobs are being auto-accepted

## Troubleshooting

If auto-acceptance is not working:
1. Verify `enabled = true` in the configuration
2. Check that `job_sources` includes the source of your jobs
3. Confirm reward values fall within `min_reward` and `max_reward`
4. Review logs for error messages
5. Test with `notification_on_accept = true` to verify triggering