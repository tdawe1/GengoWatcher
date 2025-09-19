# ADR: Auto-Acceptance Configuration Feature

## Context
GengoWatcher currently notifies users of new translation jobs but requires manual action to accept them. Users have requested an auto-acceptance feature that would automatically open job links based on configurable criteria.

## Decision
We will implement a new configuration section `[AutoAccept]` that allows users to configure automatic job acceptance based on reward thresholds, job sources, and timing parameters.

## Status
Proposed

## Consequences

### Positive
1. Users can automatically accept jobs that meet their criteria
2. Increases efficiency for active translators
3. Reduces manual intervention for routine tasks
4. Provides flexible configuration options

### Negative
1. Potential for accidentally accepting unwanted jobs
2. Security considerations with automatic browser actions
3. Complexity in configuration management
4. Risk of account suspension if used inappropriately

## Implementation Details

### Configuration Options
- `enabled`: Enable/disable auto-acceptance globally
- `min_reward`/`max_reward`: Accept jobs within reward range
- `job_sources`: Accept from RSS, WebSocket, or both
- `accept_delay_min`/`accept_delay_max`: Random delay before accepting (anti-bot detection)
- `browser_profile_path`: Specify browser profile for job acceptance
- `notification_on_accept`: Notify when job is auto-accepted
- `log_acceptance`: Log auto-acceptance events

### Safety Measures
1. Feature disabled by default
2. Configuration validation
3. Delayed acceptance to mimic human behavior
4. Detailed logging of all auto-acceptance actions
5. Notifications for transparency

### Technical Considerations
1. Integration with existing config management
2. Thread-safe configuration access
3. Backward compatibility with existing configs
4. Secure handling of any sensitive configuration