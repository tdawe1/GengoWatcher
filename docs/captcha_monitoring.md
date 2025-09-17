# CAPTCHA Service Monitoring and Alerting

## Overview

The CAPTCHA service monitoring system provides real-time health checks, performance monitoring, and alerting for CAPTCHA solving services. This document explains how to configure and use these features.

## Features

### Health Monitoring
- Real-time health checks for CAPTCHA services
- Response time monitoring
- Error detection and counting
- Service availability tracking

### Performance Monitoring
- Average response time tracking
- Success and error rate monitoring
- Request volume metrics
- Performance trend analysis

### Alerting System
- Configurable alert thresholds
- Multiple alert levels (INFO, WARNING, ERROR, CRITICAL)
- Notification integration with GengoWatcher's notification system
- Custom alert callbacks

## Configuration

Monitoring is automatically enabled when a CAPTCHA service is configured. The monitoring interval can be adjusted through the CLI or programmatically.

## Usage

### Command Line Interface

#### Start Monitoring
```
# Start monitoring with default interval (5 minutes)
captchamonitor start

# Start monitoring with custom interval (in seconds)
captchamonitor start 600  # 10 minutes
```

#### Stop Monitoring
```
captchamonitor stop
```

#### Show Health Status
```
captchamonitor health
```

#### Show Performance Metrics
```
captchamonitor performance
```

### Programmatic Usage

```python
# Start monitoring
watcher.start_captcha_monitoring(interval=300)  # 5 minutes

# Stop monitoring
watcher.stop_captcha_monitoring()

# Show health status
watcher.show_captcha_health_status()

# Show performance metrics
watcher.show_captcha_performance_metrics()
```

## Alert Thresholds

The system automatically generates alerts based on the following thresholds:

1. **Service Unhealthy**: When a service fails health checks
2. **Slow Response**: When response time exceeds 30 seconds
3. **Low Success Rate**: When success rate drops below 80%
4. **Slow Average Response**: When average response time exceeds 60 seconds

## Alert Levels

- **INFO**: General information about service status
- **WARNING**: Potential issues that may require attention
- **ERROR**: Service problems that are affecting operations
- **CRITICAL**: Severe issues requiring immediate attention

## Notifications

Alerts are integrated with GengoWatcher's notification system. Critical alerts will trigger desktop notifications and sound alerts if enabled.

## Custom Alert Callbacks

Developers can register custom alert callbacks to handle alerts in application-specific ways:

```python
def my_alert_handler(service_name: str, level: str, message: str):
    # Custom alert handling logic
    pass

# Register the callback
captcha_monitor.add_alert_callback(my_alert_handler)
```

## Performance Impact

The monitoring system is designed to have minimal performance impact:
- Health checks are lightweight (balance queries)
- Monitoring runs in a separate thread
- Configurable check intervals to balance responsiveness with resource usage
- Efficient data structures for metric storage

## Data Retention

Performance metrics and health status are kept in memory:
- Recent solve times: Last 1000 entries
- Service-specific metrics: Last 100 entries per service
- Health status: Current status only

For long-term analytics, consider implementing custom logging or external monitoring solutions.