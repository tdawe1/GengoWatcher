# ADR-001: Captcha Solving Service Integration

## Status
Proposed

## Context
Research has shown that Gengo requires captcha solving for job rejection operations, but not for job acceptance. To provide users with automated job rejection capabilities based on their criteria (such as minimum reward thresholds), the GengoWatcher application needs to integrate with captcha solving services.

## Decision
We will implement a modular captcha solving service integration with the following key decisions:

### 1. Service Provider Selection
- **Primary Provider**: 2Captcha - Most established provider with good success rates
- **Secondary Provider**: Anti-Captcha - Reliable fallback option
- **Architecture**: Plugin-based design to allow easy addition of new providers

### 2. Integration Approach
- Implement an abstract `CaptchaSolver` interface
- Create concrete implementations for each provider
- Use dependency injection for service selection
- Maintain backward compatibility (captcha solving is optional)

### 3. Configuration Management
- Add new `[Captcha]` section to `config.ini`
- Support for multiple providers with provider-specific settings
- Secure handling of API keys (never logged or exposed)

### 4. Error Handling Strategy
- Implement comprehensive error handling with specific exception types
- Provide graceful degradation when captcha services are unavailable
- Implement retry logic with exponential backoff
- Add fallback to manual captcha solving when automated approaches fail

### 5. Security Considerations
- API keys stored only in config file with appropriate file permissions
- No logging of sensitive information
- Rate limiting to prevent service abuse
- Session management for Gengo interactions

## Consequences

### Positive
- Enables automated job rejection based on user criteria
- Modular design allows for easy addition of new captcha providers
- Graceful degradation maintains application functionality even when captcha services fail
- Secure handling of sensitive credentials

### Negative
- Additional complexity in the codebase
- Dependency on third-party services
- Potential costs for captcha solving services
- Additional configuration required from users

### Neutral
- Optional feature that doesn't affect core functionality
- Maintains existing user experience for those not using captcha solving

## Alternatives Considered

### 1. No Captcha Integration
- Would leave job rejection as a manual process
- Simpler implementation but less user value

### 2. Single Provider Integration
- Would tie the application to a specific service
- Less flexible for users with preferences for different providers

### 3. Browser Automation Approach
- Using tools like Selenium to automate captcha solving in a browser
- More resource-intensive and complex
- Higher likelihood of detection/banning by Gengo

## References
- [2Captcha API Documentation](https://2captcha.com/)
- [Anti-Captcha API Documentation](https://anti-captcha.com/)
- GengoWatcher GitHub repository