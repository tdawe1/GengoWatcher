# CAPTCHA Integration Implementation Details

## API Endpoints

### Service Configuration
```
POST /captcha/setup
Description: Configure CAPTCHA solving service
Request Body:
{
  "service": "2captcha",  // or "anti-captcha"
  "api_key": "encrypted_api_key"
}
Response:
{
  "status": "success",
  "message": "CAPTCHA solver configured successfully"
}

GET /captcha/balance
Description: Get current account balance
Response:
{
  "service": "2Captcha",
  "balance": 5.75,
  "currency": "USD"
}

GET /captcha/stats
Description: Get CAPTCHA solving statistics
Response:
{
  "solved_count": 42,
  "failed_count": 3,
  "total_cost": 0.84,
  "last_solved_at": "2025-06-15T14:30:22Z"
}
```

### CAPTCHA Solving Operations
```
POST /captcha/solve
Description: Solve a CAPTCHA challenge
Request Body:
{
  "type": "recaptcha_v2",  // or "recaptcha_v3", "hcaptcha"
    "site_key": "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI",
  "page_url": "https://example.com/login",
  "action": "login"  // for recaptcha_v3
}
Response:
{
  "status": "success",
  "solution": "P5mK4Rz8N2pQ9Xv3W7yA1bC6dE0fG4hJ9kL2mN5...",
  "captcha_id": "1234567890",
  "solved_at": "2025-06-15T14:30:22Z"
}

GET /captcha/status/{task_id}
Description: Check CAPTCHA solving status
Response:
{
  "status": "pending",  // or "solved", "failed"
  "solution": null,     // populated when solved
  "error": null         // populated when failed
}
```

## Configuration Schema

### CAPTCHA Section in config.ini
```ini
[Captcha]
service = 2captcha
max_retries = 3
retry_delay = 5
rate_limit = 60
polling_interval = 5
max_wait_time = 300
```

### Secure Storage Structure
```json
{
  "2captcha": "encrypted_api_key_1",
  "anti-captcha": "encrypted_api_key_2"
}
```

## Error Handling

### HTTP Status Codes
- 200: Success
- 400: Bad Request (invalid parameters)
- 401: Unauthorized (invalid API key)
- 429: Too Many Requests (rate limited)
- 500: Internal Server Error
- 503: Service Unavailable (solver service down)

### Error Response Format
```json
{
  "error": {
    "code": "INSUFFICIENT_BALANCE",
    "message": "Account balance is insufficient to solve CAPTCHAs",
    "details": {
      "balance": 0.00,
      "required": 0.003
    }
  }
}
```

## Rate Limiting Headers
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 42
X-RateLimit-Reset: 1623758422
Retry-After: 45
```

## Authentication
API keys are stored securely and never transmitted in requests. The service uses the configured API key based on the selected service.

## Test Cases

### Successful CAPTCHA Solving
```bash
# Setup 2Captcha
curl -X POST http://localhost:8000/captcha/setup \\
  -H "Content-Type: application/json" \\
  -d '{"service": "2captcha", "api_key": "SECURE_ENCRYPTED_KEY"}'

# Check balance
curl -X GET http://localhost:8000/captcha/balance

# Solve reCAPTCHA v2
curl -X POST http://localhost:8000/captcha/solve \\
  -H "Content-Type: application/json" \\
  -d '{
    "type": "recaptcha_v2",
    "site_key": "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI",
    "page_url": "https://example.com/login"
  }'
```

### Error Cases
- Invalid API key returns 401
- Insufficient balance returns specific error code
- Rate limiting returns 429 with Retry-After header
- Service timeouts return 503 with appropriate message

## Acceptance Criteria

### Functional Requirements
1. ✅ CAPTCHA solver can be configured with 2Captcha or Anti-Captcha
2. ✅ API keys are stored securely using encryption
3. ✅ Rate limiting prevents exceeding service quotas
4. ✅ Statistics are tracked for solved/failed CAPTCHAs
5. ✅ Error handling includes retry mechanisms
6. ✅ Multiple CAPTCHA types are supported (reCAPTCHA v2/v3, hCaptcha)
7. ✅ Integration with job acceptance workflow functions correctly

### Security Requirements
1. ✅ API keys are never stored in plaintext
2. ✅ Encrypted storage uses system-specific encryption keys
3. ✅ File permissions restrict access to storage files
4. ✅ Secure key derivation prevents brute force attacks

### Performance Requirements
1. ✅ Rate limiting prevents service abuse
2. ✅ Retry mechanisms handle temporary failures
3. ✅ Timeout handling prevents hanging operations
4. ✅ Concurrent operations are thread-safe

### Reliability Requirements
1. ✅ Error recovery handles network issues
2. ✅ Balance checking prevents failed attempts
3. ✅ Logging provides debugging information
4. ✅ Statistics tracking enables usage monitoring