# GengoWatcher Integration Testing Suite

This directory contains a comprehensive testing suite for GengoWatcher that simulates real Gengo.com behavior and tests critical functionality like job acceptance, cancellation, and real-time updates.

## 🏗️ Architecture

The testing suite consists of:

- **Mock Gengo Server** (`scripts/mock_gengo_server.py`) - Simulates Gengo.com API
- **Integration Test Scenarios** (`scripts/test_integration_scenarios.py`) - Test logic
- **Test Runner** (`scripts/run_integration_tests.py`) - Orchestrates test execution
- **Docker Environment** (`docker-compose.test.yml`) - Isolated testing environment

## 🚀 Quick Start

### Option 1: Run Tests Locally

```bash
# 1. Start the mock server
python scripts/mock_gengo_server.py --scenario normal_flow

# 2. In another terminal, run the tests
python scripts/run_integration_tests.py --scenario all

# 3. View results
cat test_results_*.json
```

### Option 2: Run with Docker

```bash
# Build and run all tests
docker-compose -f docker-compose.test.yml up --build

# Run specific scenario
docker-compose -f docker-compose.test.yml run --rm test-runner \
  python scripts/run_integration_tests.py --scenario accept_then_cancel
```

## 🧪 Test Scenarios

### 1. Accept Then Cancel (`accept_then_cancel`)
**Description**: Tests job cancellation when a higher-paying opportunity appears.

**Test Flow**:
1. Accept a low-value job ($10)
2. Create a high-value job ($100) that meets cancellation criteria
3. Verify the first job is cancelled and second is accepted
4. Check WebSocket broadcasts correct status updates

**Expected Results**:
- ✅ Job A status: `cancelled`
- ✅ Job B status: `accepted`
- ✅ WebSocket messages sent for both operations
- ✅ Cancellation statistics updated

### 2. Cancellation Disabled (`cancellation_disabled`)
**Description**: Tests behavior when cancellation is disabled or ratio unmet.

**Test Flow**:
1. Configure watcher with cancellation disabled
2. Accept multiple jobs with small reward differences
3. Verify no jobs are cancelled automatically

**Expected Results**:
- ✅ All jobs remain in `accepted` status
- ✅ No cancellation operations triggered
- ✅ Statistics show zero cancellations

### 3. Server Error Handling (`server_error`)
**Description**: Tests resilience against server failures and network issues.

**Test Flow**:
1. Set mock server to return 500 errors (30% of requests)
2. Attempt various operations (accept, cancel, status checks)
3. Verify graceful error handling and retry logic

**Expected Results**:
- ✅ Operations succeed when server responds normally
- ✅ Proper error handling when server fails
- ✅ No crashes or infinite loops
- ✅ Error statistics recorded correctly

## 📊 Test Configuration

Configure test behavior in `test_config.ini`:

```ini
[TestConfig]
# Mock server settings
mock_host = 127.0.0.1
mock_port = 3000

# Test scenarios to run
enabled_scenarios = normal_flow,cancellation_test,server_error

# Timing and validation
job_creation_delay = 1.0
expected_cancellation_ratio = 2.0
max_test_duration = 300
```

## 🔧 Manual Testing

### Start Mock Server

```bash
# Basic server
python scripts/mock_gengo_server.py

# With specific scenario
python scripts/mock_gengo_server.py --scenario cancellation_test

# Custom host/port
python scripts/mock_gengo_server.py --host 0.0.0.0 --port 8080
```

### Test API Endpoints

```bash
# Server info
curl http://127.0.0.1:3000/

# Switch scenario
curl -X POST http://127.0.0.1:3000/api/scenario/cancellation_test

# Create test job
curl -X POST http://127.0.0.1:3000/api/jobs/create

# List jobs
curl http://127.0.0.1:3000/api/jobs

# Accept job
curl -X POST http://127.0.0.1:3000/t/jobs/accept/job_1001

# Cancel job
curl -X POST http://127.0.0.1:3000/t/jobs/cancel/job_1001
```

### WebSocket Testing

```bash
# Connect to WebSocket feed
websocat ws://127.0.0.1:3000/ws/jobs

# Monitor real-time updates while running tests
```

## 📈 Test Results

Results are saved as JSON files with detailed information:

```json
{
  "test_run": {
    "start_time": 1234567890.123,
    "end_time": 1234567900.456,
    "duration": 10.333,
    "results": {
      "accept_then_cancel": {
        "status": "passed",
        "passed": 1,
        "total": 1,
        "success_rate": 100.0,
        "tests": {
          "accept_then_cancel": true
        }
      }
    }
  },
  "summary": {
    "total_scenarios": 3,
    "passed_scenarios": 3,
    "failed_scenarios": 0,
    "total_tests": 3,
    "passed_tests": 3,
    "failed_tests": 0
  }
}
```

## 🐳 Docker Environment

The Docker setup provides isolated testing:

```yaml
# docker-compose.test.yml
services:
  mock-gengo:      # Mock API server
  gengowatcher:    # GengoWatcher application
  test-runner:     # Test execution
```

### Build Images

```bash
# Build all images
docker-compose -f docker-compose.test.yml build

# Build specific image
docker build -f Dockerfile.mock -t gengo-mock .
```

### Run Individual Services

```bash
# Run only mock server
docker-compose -f docker-compose.test.yml up mock-gengo

# Run tests against running mock server
docker-compose -f docker-compose.test.yml run --rm test-runner
```

## 🔍 Debugging

### Enable Debug Logging

```bash
# Set log level
export PYTHONPATH=src
python -c "import logging; logging.basicConfig(level=logging.DEBUG)"

# Run with verbose output
python scripts/run_integration_tests.py --verbose
```

### Inspect Mock Server State

```bash
# Get server status
curl http://127.0.0.1:3000/

# List all jobs
curl http://127.0.0.1:3000/api/jobs

# Check WebSocket connections
# (View in browser or use websocat)
```

### Common Issues

1. **Port conflicts**: Change mock server port in config
2. **WebSocket timeouts**: Increase `websocket_timeout` in config
3. **Docker networking**: Use `host` networking mode if needed

## 📝 Adding New Test Scenarios

1. **Define scenario in mock server** (`mock_gengo_server.py`):
   ```python
   SCENARIOS["my_scenario"] = {
       "description": "My custom test scenario",
       "jobs": [...],
       "error_rate": 0.1
   }
   ```

2. **Add test logic** (`test_integration_scenarios.py`):
   ```python
   def test_scenario_my_custom(self):
       # Test implementation
       pass
   ```

3. **Update test runner** (`run_integration_tests.py`):
   ```python
   scenarios = ["my_scenario", ...]
   ```

## 🎯 CI/CD Integration

Add to your CI pipeline:

```yaml
# .github/workflows/test.yml
- name: Run Integration Tests
  run: |
    docker-compose -f docker-compose.test.yml up --build --abort-on-container-exit
    docker-compose -f docker-compose.test.yml logs > test_logs.txt

- name: Upload Test Results
  uses: actions/upload-artifact@v2
  with:
    name: test-results
    path: test_results_*.json
```

## 📚 API Reference

### Mock Server Endpoints

- `GET /` - Server status and configuration
- `POST /api/scenario/{name}` - Switch test scenario
- `GET /t/jobs/details/{id}` - Job details HTML page
- `POST /t/jobs/accept/{id}` - Accept a job
- `POST /t/jobs/cancel/{id}` - Cancel a job
- `POST /api/jobs/create` - Create a test job
- `GET /api/jobs` - List all jobs
- `WS /ws/jobs` - Real-time job updates

### Test Runner Options

```bash
python scripts/run_integration_tests.py --help

Options:
  --scenario {accept_then_cancel,cancellation_disabled,server_error,all}
                        Test scenario to run
  --mock-host MOCK_HOST  Mock server host (default: 127.0.0.1)
  --mock-port MOCK_PORT  Mock server port (default: 3000)
  --output OUTPUT        Output file for test results
  --verbose, -v          Verbose output
```

## 🤝 Contributing

When adding new tests:

1. Follow the existing pattern in `test_integration_scenarios.py`
2. Add appropriate mock server endpoints if needed
3. Update this README with new scenarios
4. Ensure tests are idempotent and don't interfere with each other
5. Add proper error handling and logging

---

**Happy Testing!** 🧪✨</content>
</xai:function_call"> <parameter name="filePath">TESTING_README.md