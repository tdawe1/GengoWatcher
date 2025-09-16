# ADR-002: Gengo API Authentication for Job Rejection

## Status
Proposed

## Context
To implement automated job rejection functionality, the GengoWatcher application needs to interact with Gengo's web APIs. This requires proper authentication using the user's existing session credentials. Additionally, captcha solving services need to be integrated to handle the captcha challenges that Gengo presents during job rejection.

## Decision
We will implement a secure and robust authentication approach for Gengo API interactions with the following key decisions:

### 1. Authentication Method
- **Primary Method**: Session-based authentication using existing user credentials
- **Credentials Source**: Reuse `user_session` and `user_id` from existing WebSocket configuration
- **Security**: Never store passwords; only use session tokens

### 2. Session Management
- **Token Reuse**: Use the same session token configured for WebSocket connections
- **Session Validation**: Validate session before job rejection attempts
- **Error Handling**: Handle session expiration with clear user notifications

### 3. HTTP Client Approach
- **Library**: Use `aiohttp` for asynchronous HTTP requests
- **Session Persistence**: Maintain cookies and headers across requests
- **User-Agent**: Use consistent User-Agent matching WebSocket implementation

### 4. Captcha Integration Points
- **Captcha Detection**: Identify captcha challenges in Gengo's rejection flow
- **Service Integration**: Use modular captcha solver implementations
- **Solution Submission**: Properly submit solved captchas to Gengo

### 5. Security Considerations
- **Credential Storage**: Continue using existing secure configuration storage
- **Token Protection**: Never log session tokens
- **HTTPS Enforcement**: Always use HTTPS for Gengo API interactions
- **Rate Limiting**: Implement reasonable delays between requests

## Detailed Implementation

### 1. Authentication Flow
```python
# Reuse existing configuration
user_session = config.get("WebSocket", "user_session")
user_id = config.get("WebSocket", "user_id")

# Create authenticated HTTP session
headers = {
    "Cookie": f"my_gengo_session={user_session}",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": "https://gengo.com"
}

# Validate session before operations
async def validate_session():
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get("https://gengo.com/user/profile") as response:
            return response.status == 200
```

### 2. Job Rejection Flow
1. **Pre-flight Check**: Validate session and captcha configuration
2. **Rejection Request**: Submit initial rejection request to Gengo
3. **Captcha Detection**: Identify if captcha challenge is presented
4. **Captcha Solving**: Submit captcha to solving service
5. **Solution Submission**: Submit solved captcha with rejection request
6. **Result Verification**: Confirm job was successfully rejected

### 3. Error Handling
- **Session Expiration**: Prompt user to refresh session token
- **Captcha Failures**: Retry with different provider or notify user
- **Network Issues**: Implement retry logic with exponential backoff
- **Gengo Errors**: Parse and handle specific error responses

## Consequences

### Positive
- Leverages existing user credentials without requiring additional login
- Maintains consistency with WebSocket authentication approach
- Modular design allows for easy extension of captcha services
- Secure handling of sensitive credentials

### Negative
- Depends on user's session token remaining valid
- Additional HTTP requests may impact performance
- Complexity in handling captcha challenges
- Potential for rate limiting by Gengo

### Neutral
- Optional feature that doesn't affect core functionality
- Maintains existing user experience for those not using auto-rejection

## Alternatives Considered

### 1. OAuth Integration
- Would require OAuth application registration with Gengo
- More complex implementation but potentially more robust
- Would require user to authorize application separately
- **Decision**: Rejected due to complexity and lack of public OAuth support from Gengo

### 2. Separate Login Credentials
- Would require users to provide Gengo username/password
- Security risk of storing passwords
- More complex credential management
- **Decision**: Rejected due to security concerns

### 3. Browser Automation
- Using Selenium or similar to automate browser interactions
- Would handle captchas automatically
- Very resource-intensive and detectable
- **Decision**: Rejected due to performance and reliability concerns

## References
- [Gengo API Documentation](https://developers.gengo.com/)
- [aiohttp Documentation](https://docs.aiohttp.org/)
- Existing WebSocket implementation in `watcher.py`
- 2Captcha API Documentation
- Anti-Captcha API Documentation