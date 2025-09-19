# GengoWatcher CAPTCHA Solver Architecture

This document describes the architecture and implementation of the CAPTCHA solver system for GengoWatcher.

## Overview

The CAPTCHA solver system provides integration with popular CAPTCHA solving services to handle CAPTCHA challenges that may occur during job acceptance. The system is designed with the following principles:

1. **Security**: API keys are stored securely using encryption
2. **Extensibility**: Easy to add new CAPTCHA solving services
3. **Rate Limiting**: Prevents exceeding service quotas
4. **Error Handling**: Robust retry mechanisms with exponential backoff
5. **Statistics**: Tracks usage and performance metrics

## Components

### 1. BaseCaptchaSolver (Abstract Base Class)

Defines the interface for all CAPTCHA solving services:

- `get_service_name()` - Returns the service name
- `get_balance()` - Gets account balance
- `solve_recaptcha_v2()` - Solves reCAPTCHA v2
- `solve_recaptcha_v3()` - Solves reCAPTCHA v3
- `solve_hcaptcha()` - Solves hCaptcha
- `_check_result()` - Checks CAPTCHA solving result (abstract)

### 2. Service Implementations

#### TwoCaptchaSolver
Implementation for the 2Captcha service (https://2captcha.com)

#### AntiCaptchaSolver
Implementation for the Anti-Captcha service (https://anti-captcha.com)

### 3. CaptchaSolverManager

Coordinates CAPTCHA solving operations:

- Initializes the appropriate solver based on configuration
- Manages rate limiting
- Handles retries with exponential backoff
- Tracks statistics
- Provides unified interface for solving different CAPTCHA types

### 4. SecureKeyStorage

Securely stores and retrieves API keys:

- Uses system-specific encryption keys
- Stores data in encrypted JSON files
- Provides methods for storing, retrieving, and deleting API keys

### 5. RateLimiter

Prevents exceeding API request limits:

- Sliding window algorithm implementation
- Configurable request limits and time windows
- Thread-safe operations

### 6. Data Classes

#### CaptchaSolution
Represents a solved CAPTCHA:
- `captcha_id`: Task identifier
- `solution`: The CAPTCHA solution
- `solved_at`: Timestamp when solved
- `cost`: Cost of solving (optional)

#### CaptchaTask
Represents a CAPTCHA solving task:
- `task_id`: Task identifier
- `captcha_type`: Type of CAPTCHA
- `site_key`: Site key for the CAPTCHA
- `page_url`: URL where CAPTCHA appears
- `created_at`: Timestamp when task was created
- `action`: Action for reCAPTCHA v3 (optional)

### 7. Exception Hierarchy

#### CaptchaSolverError (Base)
Base exception for all CAPTCHA solver errors

#### CaptchaSolverAPIError
For API-related errors

#### CaptchaSolverBalanceError
For insufficient balance errors

#### CaptchaSolverTimeoutError
For timeout errors

## Integration with Job Acceptance Engine

The CAPTCHA solver integrates with the job acceptance engine through the following workflow:

1. When attempting to accept a job, the system checks if a CAPTCHA challenge is presented
2. If a CAPTCHA is detected, the system extracts the necessary information (site key, page URL)
3. The appropriate CAPTCHA solver method is called based on the CAPTCHA type
4. Once solved, the solution is submitted along with the job acceptance request
5. Statistics are updated to track usage and performance

## Configuration

The CAPTCHA solver is configured through the `[Captcha]` section in `config.ini`:

```ini
[Captcha]
service = 2captcha
max_retries = 3
retry_delay = 5
rate_limit = 60
```

API keys are stored securely and not included in the configuration file.

## Security Considerations

1. **API Key Storage**: API keys are encrypted using system-specific keys
2. **Rate Limiting**: Prevents abuse of CAPTCHA solving services
3. **Retry Logic**: Prevents excessive requests in case of failures
4. **Error Handling**: Graceful degradation when CAPTCHA solving fails

## Extending with New Services

To add support for a new CAPTCHA solving service:

1. Create a new class that inherits from `BaseCaptchaSolver`
2. Implement all abstract methods
3. Add the service to the service type enumeration
4. Update the initialization logic in `CaptchaSolverManager`
5. Add any service-specific configuration options if needed

## Usage Example

```python
# Initialize the CAPTCHA manager
captcha_manager = CaptchaSolverManager(config, logger)

# Solve a reCAPTCHA v2
solution = captcha_manager.solve_recaptcha_v2(
    site_key="6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI",
    page_url="https://example.com/page-with-captcha"
)

if solution:
    print(f"CAPTCHA solved: {solution.solution}")
else:
    print("Failed to solve CAPTCHA")
```