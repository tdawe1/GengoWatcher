# CAPTCHA Solver Statistics

## Overview

The CAPTCHA solver now includes detailed statistics tracking to help monitor performance, costs, and success rates. This document explains the available statistics and how to access them.

## Available Statistics

### Overall Statistics
- `solved_count`: Total number of CAPTCHAs solved successfully
- `failed_count`: Total number of CAPTCHA solving attempts that failed
- `success_rate`: Percentage of successful CAPTCHA solves
- `total_cost`: Total cost incurred for all CAPTCHA solving attempts
- `last_solved_at`: Timestamp of the last successful CAPTCHA solve
- `current_rate`: Current rate of CAPTCHA solving requests

### CAPTCHA Type Statistics
Tracks statistics for each CAPTCHA type:
- `recaptcha_v2`: Google reCAPTCHA v2
- `recaptcha_v3`: Google reCAPTCHA v3
- `hcaptcha`: hCaptcha

For each type:
- `solved`: Number of successful solves
- `failed`: Number of failed attempts
- `success_rate`: Success rate percentage
- `total_cost`: Total cost for this CAPTCHA type

### Service Statistics
Tracks statistics for each CAPTCHA solving service:
- Service name (e.g., "2Captcha", "Anti-Captcha")
- `solved`: Number of successful solves
- `failed`: Number of failed attempts
- `success_rate`: Success rate percentage
- `total_cost`: Total cost for this service
- `avg_solve_time`: Average time to solve CAPTCHAs
- `min_solve_time`: Minimum solve time
- `max_solve_time`: Maximum solve time

### Performance Statistics
- `solve_times`: List of recent solve times for overall performance tracking
- `avg_solve_time`: Average solve time across all CAPTCHAs
- `min_solve_time`: Minimum solve time
- `max_solve_time`: Maximum solve time

### Error Statistics
Tracks frequency of different error types:
- `balance_error`: Insufficient account balance
- `timeout_error`: Request timeouts
- Specific exception names for other errors

## Accessing Statistics

### Programmatically
```python
# Get statistics dictionary
stats = captcha_solver.get_stats()

# Access specific statistics
print(f"Total solved: {stats['solved_count']}")
print(f"Success rate: {stats['success_rate']:.1f}%")
print(f"Total cost: ${stats['total_cost']:.4f}")
```

### Command Line Interface
Use the `captchastats` command in the GengoWatcher CLI to display detailed statistics:

```
=== CAPTCHA Solver Statistics ===
Service: 2Captcha
Balance: $10.5000
Solved CAPTCHAs: 42
Failed attempts: 3
Success rate: 93.3%
Total cost: $0.8400
Last solved: 2025-09-15 14:30:22

CAPTCHA Type Statistics:
  recaptcha_v2:
    Solved: 25
    Failed: 1
    Success Rate: 96.2%
    Cost: $0.5000
  recaptcha_v3:
    Solved: 10
    Failed: 1
    Success Rate: 90.9%
    Cost: $0.2000
  hcaptcha:
    Solved: 7
    Failed: 1
    Success Rate: 87.5%
    Cost: $0.1400

Service Statistics:
  2Captcha:
    Solved: 42
    Failed: 3
    Success Rate: 93.3%
    Cost: $0.8400
    Avg Solve Time: 12.45s
    Min Solve Time: 8.21s
    Max Solve Time: 25.67s

Overall Performance:
  Avg Solve Time: 12.45s
  Min Solve Time: 8.21s
  Max Solve Time: 25.67s

Error Statistics:
  timeout_error: 2
  balance_error: 1
```

## Benefits

1. **Cost Tracking**: Monitor expenses for CAPTCHA solving services
2. **Performance Monitoring**: Track solve times and identify performance issues
3. **Success Rate Analysis**: Understand which CAPTCHA types and services perform best
4. **Error Analysis**: Identify common failure modes and address them
5. **Service Comparison**: Compare different CAPTCHA solving services to optimize selection