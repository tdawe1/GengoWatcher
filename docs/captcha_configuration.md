# CAPTCHA Configuration Guide

GengoWatcher supports integration with third-party CAPTCHA solving services to automate the solving of CAPTCHA challenges during job acceptance.

## Supported Services

GengoWatcher currently supports the following CAPTCHA solving services:

### 1. 2Captcha
- **Website**: https://2captcha.com
- **API Documentation**: https://2captcha.com/2captcha-api
- **Pricing**: Pay-per-solve model with volume discounts
- **Supported CAPTCHA Types**: reCAPTCHA v2/v3, hCaptcha

### 2. Anti-Captcha
- **Website**: https://anti-captcha.com
- **API Documentation**: https://anti-captcha.com/apidoc
- **Pricing**: Pay-per-solve model with volume discounts
- **Supported CAPTCHA Types**: reCAPTCHA v2/v3, hCaptcha

## Setup and Configuration

### 1. Initial Setup

To configure CAPTCHA solving:

1. Start GengoWatcher:
   ```bash
   python -m gengowatcher.main
   ```

2. Type the following command in the TUI:
   ```
   captchasetup
   ```

3. Follow the interactive prompts:
   - Select your preferred service (2Captcha or Anti-Captcha)
   - Enter your API key when prompted
   - The API key will be stored securely and will not appear in config.ini

### 2. Configuration File Settings

The CAPTCHA solver adds the following section to your `config.ini`:

```ini
[Captcha]
service = 2captcha
max_retries = 3
retry_delay = 5
rate_limit = 60
```

#### Configuration Options:

- **service**: The CAPTCHA service to use (`2captcha` or `anti-captcha`)
- **max_retries**: Maximum number of retry attempts for failed solves (default: 3)
- **retry_delay**: Delay between retry attempts in seconds (default: 5)
- **rate_limit**: Maximum requests per minute (default: 60)

### 3. API Key Storage

API keys are stored securely using the `SecureKeyStorage` system:

- **Location**: System-specific secure storage
- **Encryption**: Fernet encryption (AES-128-CBC with HMAC) with system-specific key derivation
- **Permissions**: Restrictive file permissions (0o600)
- **No Exposure**: Keys are never logged or displayed in plain text

## Rate Limiting and Retry Behavior

### Rate Limiting

The CAPTCHA solver implements a sliding window rate limiter to prevent exceeding API limits:

- **Default Limit**: 60 requests per minute
- **Window Type**: Sliding window (more accurate than fixed windows)
- **Per-Service**: Separate limits for each CAPTCHA service
- **Configurable**: Can be adjusted in config.ini

### Retry Behavior

When a CAPTCHA solve fails, the system implements intelligent retry logic:

1. **Exponential Backoff**: Retry delays increase exponentially
2. **Error Type Handling**: Different retry strategies for different error types
3. **Maximum Retries**: Configurable maximum retry attempts
4. **Balance Check**: Verifies sufficient balance before retrying

### Adaptive Polling

The polling system uses adaptive intervals for checking solve status:

- **Initial Interval**: 5 seconds
- **Maximum Interval**: 30 seconds
- **Backoff Factor**: 1.5x (exponential)
- **Timeout**: 300 seconds (5 minutes) maximum wait time

## CAPTCHA Type Support

### reCAPTCHA v2
- Standard "I'm not a robot" checkbox
- Invisible reCAPTCHA
- Supported by both services

### reCAPTCHA v3
- Score-based verification
- Requires action parameter
- Supported by both services

### hCaptcha
- Privacy-focused alternative to reCAPTCHA
- Supported by both services

## Integration with Auto-Accept

When auto-acceptance is enabled, the CAPTCHA solver is automatically invoked when:

1. A CAPTCHA challenge is detected on the job acceptance page
2. The job meets your configured criteria (reward range, etc.)
3. You have sufficient balance in your CAPTCHA service account

### Browser Fallback for reCAPTCHA v3

In cases where reCAPTCHA v3 solving fails, the system can optionally fall back to browser-based solving:

1. **Detection**: Automatic detection of reCAPTCHA v3 challenges
2. **Fallback Strategy**: Launch browser with Selenium if configured
3. **Configuration**: Optional, controlled by browser settings in config.ini

## Testing Your Configuration

### Test API Key and Balance
```
captchatest
```

### View Statistics
```
captchastats
```

### Reset Configuration
```
captchareset
```

## Troubleshooting

### Common Issues

1. **Insufficient Balance**
   - Check balance with `captchastats`
   - Add funds to your CAPTCHA service account

2. **API Key Invalid**
   - Verify API key in your service dashboard
   - Use `captchareset` to reconfigure

3. **Rate Limit Exceeded**
   - Reduce polling frequency in config.ini
   - Check for multiple instances running

4. **Solve Failures**
   - Ensure CAPTCHA type is supported
   - Check network connectivity
   - Verify site key and page URL are correct

### Debug Logging

To enable debug logging for CAPTCHA operations:

```ini
[Logging]
log_level = DEBUG
```

Debug logs will show:
- API request timestamps
- Response status codes
- Solve timing information
- Error details (without sensitive data)

## Security Considerations

1. **API Key Protection**
   - Keys are never stored in plain text
   - Never logged or displayed
   - Encrypted at rest

2. **Solution Token Privacy**
   - Solution tokens are never logged
   - Tokens are used immediately and discarded
   - No persistent storage of solutions

3. **Network Security**
   - HTTPS-only API communication
   - Certificate validation enabled
   - No proxy support (prevents MITM attacks)

## Cost Management

### Monitoring Costs
- Use `captchastats` to track usage
- Monitor solve success rates
- Set up balance alerts in your service dashboard

### Cost Optimization
- Adjust rate limits based on needs
- Use appropriate CAPTCHA types
- Monitor for failed solves and retries

## Best Practices

1. **Start with a small balance** to test the integration
2. **Monitor solve rates** to ensure cost-effectiveness
3. **Keep API keys secure** and rotate them periodically
4. **Use appropriate rate limits** to avoid service bans
5. **Test configuration changes** before deployment

## Example Usage

```python
# Manual CAPTCHA solving example (for testing)
from gengowatcher.captcha_manager import CaptchaSolverManager
from gengowatcher.config import AppConfig
import logging

# Initialize
config = AppConfig()
logger = logging.getLogger(__name__)
solver = CaptchaSolverManager(config.config, logger)

# Check if configured
if solver.is_configured():
    # Solve a reCAPTCHA v2
    solution = solver.solve_recaptcha_v2(
        site_key="6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI",
        page_url="https://example.com"
    )

    if solution:
        print(f"Solution token: {solution.solution}")
        print(f"Cost: ${solution.cost}")
        print(f"Solve time: {solution.solved_at}")
```

## Support

For issues related to:
- **GengoWatcher integration**: Create an issue on GitHub
- **Service-specific problems**: Contact the respective service support
- **API key issues**: Check your service dashboard