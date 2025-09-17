# Testing Auto-Acceptance Configuration

## Overview
This document explains how to test the new auto-acceptance configuration feature.

## Prerequisites
1. Updated GengoWatcher with auto-acceptance feature
2. Valid config.ini file

## Testing Steps

### 1. Verify Configuration Section Addition
Run GengoWatcher and check that the `[AutoAccept]` section has been added to your config.ini:

```bash
python -m src.gengowatcher.main --list
```

Look for the `[AutoAccept]` section in the output.

### 2. Test Configuration Validation
Try setting invalid values to verify validation works:

```bash
# Test reward range validation
python -m src.gengowatcher.main --set AutoAccept min_reward 10.0
python -m src.gengowatcher.main --set AutoAccept max_reward 5.0

# Run GengoWatcher and check for warning message about swapped values
python -m src.gengowatcher.main
```

### 3. Test Job Source Validation
Try setting invalid job sources:

```bash
# Test invalid job sources
python -m src.gengowatcher.main --set AutoAccept job_sources rss,invalid_source

# Run GengoWatcher and check for warning message
python -m src.gengowatcher.main
```

### 4. Test Delay Range Validation
Try setting invalid delay ranges:

```bash
# Test delay range validation
python -m src.gengowatcher.main --set AutoAccept accept_delay_min 30
python -m src.gengowatcher.main --set AutoAccept accept_delay_max 5

# Run GengoWatcher and check for warning message about swapped values
python -m src.gengowatcher.main
```

### 5. Test Reasonable Limits
Try setting unreasonable delay values:

```bash
# Test unreasonable delay limits
python -m src.gengowatcher.main --set AutoAccept accept_delay_max 500

# Run GengoWatcher and check that value is capped at 300
python -m src.gengowatcher.main --get AutoAccept accept_delay_max
```

## Configuration Examples

### Basic Test Configuration
```ini
[AutoAccept]
enabled = true
min_reward = 0.0
max_reward = 999999.0
job_sources = rss
accept_delay_min = 1
accept_delay_max = 5
```

### Reward-Based Filtering Test
```ini
[AutoAccept]
enabled = true
min_reward = 5.0
max_reward = 20.0
job_sources = websocket
accept_delay_min = 10
accept_delay_max = 30
```

### Dual Source Test
```ini
[AutoAccept]
enabled = true
job_sources = rss,websocket
accept_delay_min = 5
accept_delay_max = 15
```

## Verification Commands

### List All Configuration
```bash
python -m src.gengowatcher.main --list
```

### Get Specific AutoAccept Values
```bash
python -m src.gengowatcher.main --get AutoAccept enabled
python -m src.gengowatcher.main --get AutoAccept min_reward
python -m src.gengowatcher.main --get AutoAccept max_reward
python -m src.gengowatcher.main --get AutoAccept job_sources
python -m src.gengowatcher.main --get AutoAccept accept_delay_min
python -m src.gengowatcher.main --get AutoAccept accept_delay_max
```

### Set AutoAccept Values
```bash
python -m src.gengowatcher.main --set AutoAccept enabled true
python -m src.gengowatcher.main --set AutoAccept min_reward 3.0
python -m src.gengowatcher.main --set AutoAccept max_reward 50.0
python -m src.gengowatcher.main --set AutoAccept job_sources "rss,websocket"
python -m src.gengowatcher.main --set AutoAccept accept_delay_min 5
python -m src.gengowatcher.main --set AutoAccept accept_delay_max 20
```

## Troubleshooting

### Configuration Not Appearing
If the `[AutoAccept]` section doesn't appear in your config:
1. Ensure you're running the updated version of GengoWatcher
2. Check that your config.ini file is writable
3. Try deleting config.ini and letting it regenerate

### Validation Warnings Not Appearing
If validation warnings don't appear:
1. Ensure you're running with debug logging enabled
2. Check that the validation method is being called
3. Verify your configuration values are actually invalid

### Values Not Being Corrected
If invalid values aren't being corrected:
1. Check that the validation logic is implemented correctly
2. Ensure the corrected values are being saved to config
3. Verify that the application is restarting properly

## Logging

Check the log file (`logs/gengowatcher.log`) for validation messages:
- Look for "Added missing config section" messages
- Look for "Warning:" messages about corrected values
- Check that configuration values are loaded correctly

## Best Practices for Testing

1. Always test with a copy of your production config
2. Enable logging to see validation messages
3. Test edge cases (boundary values, invalid formats)
4. Verify both programmatic and manual config changes
5. Test with both new and existing configuration files