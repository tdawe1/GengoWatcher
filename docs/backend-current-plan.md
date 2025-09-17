# CAPTCHA Integration Plan

## 1. Architecture for CAPTCHA Solving Integration

### Overview
The CAPTCHA solving integration follows a modular, service-oriented architecture that allows for multiple CAPTCHA solving providers while maintaining security and reliability. The architecture consists of:

1. **Abstract Base Layer**: Defines common interfaces and shared functionality
2. **Service Implementations**: Provider-specific implementations for 2Captcha and Anti-Captcha
3. **Management Layer**: Coordinates solving requests, rate limiting, and statistics
4. **Security Layer**: Securely stores API keys using encryption
5. **Integration Layer**: Connects CAPTCHA solving with job acceptance workflows

### Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    GengoWatcher Application                 │
├─────────────────────────────────────────────────────────────┤
│                  Job Acceptance Engine                      │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              CAPTCHA Solver Manager                  │   │
│  │  ┌─────────────────┐  ┌─────────────────────────┐    │   │
│  │  │   Rate Limiter  │  │      Statistics         │    │   │
│  │  └─────────────────┘  └─────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              CAPTCHA Service Abstraction             │   │
│  │  ┌─────────────────┐  ┌─────────────────────────┐    │   │
│  │  │  Base Solver    │  │   Secure Storage        │    │   │
│  │  │ (Abstract Base) │  │ (Encrypted Key Storage) │    │   │
│  │  └─────────────────┘  └─────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            CAPTCHA Service Implementations           │   │
│  │  ┌─────────────────┐  ┌─────────────────────────┐    │   │
│  │  │  2Captcha       │  │   Anti-Captcha          │    │   │
│  │  │  Solver         │  │   Solver                │    │   │
│  │  └─────────────────┘  └─────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 2. Required Components and Their Responsibilities

### 2.1 BaseCaptchaSolver (Abstract Base Class)
**Responsibilities:**
- Define common interface for all CAPTCHA services
- Handle HTTP request/response processing
- Implement polling mechanism for result checking
- Provide common error handling framework
- Manage session and authentication

**Key Methods:**
- `get_service_name()` - Return service identifier
- `get_balance()` - Retrieve account balance
- `solve_recaptcha_v2()` - Solve reCAPTCHA v2 challenges
- `solve_recaptcha_v3()` - Solve reCAPTCHA v3 challenges
- `solve_hcaptcha()` - Solve hCaptcha challenges
- `_make_request()` - HTTP request with error handling
- `_poll_for_result()` - Polling mechanism for results
- `_check_result()` - Check specific task result

### 2.2 TwoCaptchaSolver
**Responsibilities:**
- Implement 2Captcha API integration
- Handle 2Captcha-specific request/response formats
- Manage 2Captcha task submission and result retrieval
- Implement 2Captcha-specific error handling

**Integration Points:**
- API endpoint: https://2captcha.com
- Task submission: `/in.php`
- Result checking: `/res.php`

### 2.3 AntiCaptchaSolver
**Responsibilities:**
- Implement Anti-Captcha API integration
- Handle Anti-Captcha-specific request/response formats
- Manage Anti-Captcha task submission and result retrieval
- Implement Anti-Captcha-specific error handling

**Integration Points:**
- API endpoint: https://api.anti-captcha.com
- Task submission: `/createTask`
- Result checking: `/getTaskResult`

### 2.4 CaptchaSolverManager
**Responsibilities:**
- Initialize and manage solver instances
- Coordinate rate limiting across all CAPTCHA operations
- Track statistics and metrics
- Handle retry logic and error recovery
- Provide unified interface for CAPTCHA solving

**Key Features:**
- Thread-safe operations
- Configuration-driven behavior
- Statistics tracking
- Rate limiting enforcement

### 2.5 SecureKeyStorage
**Responsibilities:**
- Securely store and retrieve API keys
- Encrypt sensitive data using system-specific keys
- Manage storage file permissions and access
- Handle key deletion and updates

**Security Measures:**
- AES encryption with Fernet
- PBKDF2 key derivation with system-specific salts
- File-based storage with restricted permissions

### 2.6 RateLimiter
**Responsibilities:**
- Prevent exceeding service API rate limits
- Track request history and timing
- Calculate wait times when limits are reached
- Provide thread-safe access control

## 3. Security Considerations for Storing API Keys

### 3.1 Encryption Strategy
- **Algorithm**: Fernet symmetric encryption (AES 128 in CBC mode with PKCS7 padding)
- **Key Derivation**: PBKDF2 with SHA256, 100,000 iterations
- **Salt**: System-specific information (username, hostname, machine info)
- **Password**: Application-specific constant with version identifier

### 3.2 Storage Security
- **File Location**: Separate encrypted file (`captcha_keys.json`)
- **File Permissions**: Restricted to owner read/write only
- **Directory Creation**: Automatically create parent directories with secure permissions
- **Data Format**: JSON with service names as keys

### 3.3 Key Management
- **Storage**: Never store keys in plaintext config files
- **Retrieval**: Decrypt on demand with system-specific keys
- **Updates**: Securely overwrite existing keys
- **Deletion**: Remove specific keys or entire storage

### 3.4 Access Control
- **Application Level**: Only CAPTCHA components can access keys
- **User Level**: Keys are tied to specific user/system
- **Process Level**: Keys are only accessible during application runtime

## 4. Integration Points with Existing Job Acceptance Functionality

### 4.1 Job Rejection Handling
- **Trigger**: Job rejection notifications with CAPTCHA requirements
- **Detection**: Identify rejection reasons that require CAPTCHA solving
- **Extraction**: Parse CAPTCHA details from rejection data (site key, page URL, type)
- **Processing**: Submit CAPTCHA for solving and handle results

### 4.2 Workflow Integration
```
1. Job Acceptance Attempt
   ↓
2. Job Rejection Received
   ↓
3. CAPTCHA Required Detection
   ↓
4. CAPTCHA Details Extraction
   ↓
5. CAPTCHA Solver Manager
   ↓
6. Service Selection & Submission
   ↓
7. Solution Retrieval & Validation
   ↓
8. Solution Submission to Job System
   ↓
9. Job Re-acceptance Attempt
```

### 4.3 Data Flow
- **Input**: Job rejection data with CAPTCHA requirements
- **Processing**: CAPTCHA solving with configured service
- **Output**: CAPTCHA solution for job system submission
- **Feedback**: Success/failure metrics to statistics system

### 4.4 Error Handling Integration
- **Network Issues**: Retry with exponential backoff
- **Balance Issues**: Alert user and pause operations
- **Service Errors**: Failover to alternative services (if configured)
- **Timeouts**: Configurable maximum wait times

## 5. Configuration Options

### 5.1 Service Configuration
```
[Captcha]
service = 2captcha          # or anti-captcha
max_retries = 3             # retry attempts
retry_delay = 5             # seconds between retries
rate_limit = 60             # requests per minute
```

### 5.2 Service-Specific Options
- **Polling Intervals**: Time between result checks
- **Timeout Settings**: Maximum solve time before giving up
- **Task Parameters**: Service-specific options for different CAPTCHA types

### 5.3 Security Configuration
- **Storage File**: Path to encrypted key storage
- **Encryption Settings**: Algorithm and key derivation parameters
- **Access Controls**: File permissions and ownership

### 5.4 Performance Configuration
- **Concurrency Limits**: Maximum simultaneous solving requests
- **Cache Settings**: Balance caching TTL and refresh intervals
- **Timeout Values**: Various timeout configurations for different operations

## 6. Error Handling and Retry Mechanisms

### 6.1 Error Types
- **Network Errors**: Connection timeouts, DNS failures, HTTP errors
- **Service Errors**: API errors, balance issues, invalid parameters
- **Application Errors**: Configuration issues, internal failures
- **User Errors**: Invalid inputs, missing data

### 6.2 Retry Strategy
- **Exponential Backoff**: Start with short delays, increase with each retry
- **Jitter**: Add randomness to prevent thundering herd problems
- **Circuit Breaker**: Prevent continuous retries during extended outages
- **Max Retry Limits**: Configurable attempt limits per operation

### 6.3 Specific Handling
- **Insufficient Balance**: Immediate failure with user notification
- **Rate Limiting**: Automatic waiting with progress indication
- **Invalid CAPTCHA**: No retries, mark as permanent failure
- **Service Outages**: Extended retry with exponential backoff

### 6.4 Monitoring and Logging
- **Detailed Logging**: All errors logged with context and stack traces
- **Metrics Collection**: Error counts, types, and patterns
- **Alerting**: Critical errors trigger immediate notifications
- **Debug Information**: Verbose logging for troubleshooting

## 7. Rate Limiting Implementation

### 7.1 Algorithm
- **Sliding Window**: Tracks request timestamps in a time-based window
- **Thread Safety**: Lock-based synchronization for concurrent access
- **Time-based**: Real-time tracking of request timing with automatic cleanup

### 7.2 Parameters
- **Max Requests**: Maximum requests allowed within the time window
- **Time Window**: Sliding time period for rate calculation (default: 60 seconds)
- **Cleanup**: Automatic removal of expired timestamps

### 7.3 Integration Points
- **Before Request**: Check current request count in sliding window
- **On Limit Hit**: Calculate and enforce wait times based on oldest request
- **Statistics**: Track usage and limit hits with real-time rate calculation

### 7.4 Adaptive Behavior
- **Dynamic Limits**: Adjust based on service responses
- **Graceful Degradation**: Continue with reduced functionality
- **User Feedback**: Clear indication of rate limiting status

## 8. Implementation Roadmap

### Phase 1: Core Infrastructure
1. Implement BaseCaptchaSolver abstract class
2. Create SecureKeyStorage with encryption
3. Implement RateLimiter with sliding window algorithm
4. Develop CaptchaSolverManager coordination layer

### Phase 2: Service Implementations
1. Implement TwoCaptchaSolver with full API support
2. Implement AntiCaptchaSolver with full API support
3. Add comprehensive error handling for both services
4. Implement statistics tracking and reporting

### Phase 3: Integration
1. Integrate with existing job acceptance engine
2. Add CAPTCHA rejection detection and handling
3. Implement solution submission workflow
4. Add CLI commands for setup and testing

### Phase 4: Testing and Refinement
1. Unit tests for all components
2. Integration tests with mock services
3. Performance testing under load
4. Security audit and validation

### Phase 5: Documentation and Release
1. User documentation for setup and configuration
2. API documentation for developers
3. Migration guide for existing installations
4. Release with comprehensive testing