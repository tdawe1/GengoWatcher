# ADR 001: CAPTCHA Integration Architecture

## Status
Accepted

## Context
GengoWatcher needs to integrate CAPTCHA solving capabilities to handle job rejections that require CAPTCHA verification. The system must support multiple CAPTCHA solving services while maintaining security, reliability, and performance.

## Decision
We will implement a modular CAPTCHA solving architecture with the following components:

1. **Abstract Base Solver**: Define a common interface for all CAPTCHA solving services
2. **Service Implementations**: Implement specific solvers for 2Captcha and Anti-Captcha
3. **Secure Storage**: Store API keys securely using encryption
4. **Rate Limiting**: Prevent exceeding service API limits
5. **Error Handling**: Implement retry mechanisms and proper error handling
6. **Statistics Tracking**: Monitor usage and performance metrics

## Consequences

### Positive
- Modular design allows easy addition of new CAPTCHA services
- Secure storage protects API keys
- Rate limiting prevents account bans
- Retry mechanisms improve reliability
- Statistics help monitor usage and costs

### Negative
- Increased complexity in the codebase
- Dependency on external CAPTCHA solving services
- Potential costs for CAPTCHA solving

## Implementation Details

### Core Components

1. **BaseCaptchaSolver (Abstract)**
   - Defines common interface for all CAPTCHA services
   - Handles common functionality like HTTP requests and polling

2. **TwoCaptchaSolver**
   - Implements 2Captcha API integration
   - Supports reCAPTCHA v2, v3, and hCaptcha

3. **AntiCaptchaSolver**
   - Implements Anti-Captcha API integration
   - Supports reCAPTCHA v2, v3, and hCaptcha

4. **CaptchaSolverManager**
   - Manages solver initialization and configuration
   - Handles rate limiting and statistics
   - Provides unified interface for CAPTCHA solving

5. **SecureKeyStorage**
   - Encrypts and stores API keys
   - Uses system-specific keys for encryption

6. **RateLimiter**
   - Prevents exceeding API request limits
   - Implements sliding window algorithm

### Security Considerations
- API keys are stored encrypted, not in plaintext config files
- Encryption uses system-specific salts for added security
- Secure storage file permissions restrict access

### Configuration Options
- Service selection (2Captcha or Anti-Captcha)
- Maximum retry attempts
- Retry delay between attempts
- Rate limiting parameters
- Polling intervals for result checking

### Error Handling
- Network errors with exponential backoff
- Balance checking to prevent failed attempts
- Timeout handling for long-running CAPTCHA solves
- Comprehensive logging for debugging

## References
- 2Captcha API Documentation
- Anti-Captcha API Documentation
- CAPTCHA.md security analysis