# GengoWatcher Auto-Accept Feature

The auto-accept feature allows GengoWatcher to automatically accept translation jobs that meet your specified criteria, reducing the need for manual intervention.

## How It Works

1. **Job Detection**: GengoWatcher monitors for new jobs via RSS feeds and WebSocket connections
2. **Eligibility Check**: Each new job is evaluated against your configured criteria
3. **Auto-Accept**: Eligible jobs are automatically accepted via the Gengo API
4. **Captcha Handling**: If a captcha is required, the system uses configured captcha solving services
5. **Notification**: You can receive notifications when jobs are auto-accepted

## Configuration

The auto-accept feature is configured through the `[AutoAccept]` section in your `config.ini` file:

```ini
[AutoAccept]
enabled = false
min_reward = 0.0
max_reward = 999999.0
job_sources = rss,websocket
accept_delay_min = 5
accept_delay_max = 30
browser_profile_path = 
notification_on_accept = true
log_acceptance = true
```

### Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `enabled` | Enable/disable auto-accept feature | `false` |
| `min_reward` | Minimum reward amount to auto-accept | `0.0` |
| `max_reward` | Maximum reward amount to auto-accept | `999999.0` |
| `job_sources` | Comma-separated list of job sources (`rss`, `websocket`) | `rss,websocket` |
| `accept_delay_min` | Minimum delay before accepting job (seconds) | `5` |
| `accept_delay_max` | Maximum delay before accepting job (seconds) | `30` |
| `browser_profile_path` | Path to browser profile (if using browser automation) | `` |
| `notification_on_accept` | Show notification when job is auto-accepted | `true` |
| `log_acceptance` | Log auto-accepted jobs to file | `true` |

## Captcha Solving

Some job acceptance operations may require solving captchas. GengoWatcher supports integration with popular captcha solving services:

### Supported Services

1. **2Captcha** - https://2captcha.com/
2. **Anti-Captcha** - https://anti-captcha.com/

### Captcha Configuration

Configure captcha solving through the `[Captcha]` section in `config.ini`:

```ini
[Captcha]
service = 2captcha
api_key = YOUR_API_KEY_HERE
max_retries = 3
retry_delay = 5
rate_limit = 60
```

## Usage

### Enabling Auto-Accept

1. Set `enabled = true` in the `[AutoAccept]` section of `config.ini`
2. Configure your reward range and other criteria
3. (Optional) Configure captcha solving if needed
4. Restart GengoWatcher

### TUI Commands

When running GengoWatcher, you can use these commands to control auto-accept:

- `acceptstats` - Display job acceptance statistics
- `setminautoaccept <amount>` - Set minimum reward for auto-acceptance
- `setmaxautoaccept <amount>` - Set maximum reward for auto-acceptance

### Web API Endpoints

The web API provides these endpoints for auto-accept functionality:

- `POST /api/jobs/{job_id}/accept` - Force accept a specific job
- `GET /api/autoaccept/status` - Get auto-accept status
- `GET /api/autoaccept/metrics` - Get acceptance metrics

## Security Considerations

1. **Credentials**: Your Gengo session token is stored securely in config.ini
2. **Captcha API Keys**: Captcha service API keys are stored encrypted
3. **Rate Limiting**: The system implements rate limiting to prevent abuse
4. **Delay Simulation**: Random delays help avoid detection as automated activity

## Troubleshooting

### Common Issues

1. **Jobs not being auto-accepted**:
   - Check that auto-accept is enabled
   - Verify your reward range settings
   - Ensure your Gengo credentials are valid

2. **Captcha solving failures**:
   - Check your captcha service configuration
   - Verify your API key is valid
   - Check your account balance

3. **Authentication errors**:
   - Your Gengo session token may have expired
   - Update your session token in config.ini

### Log Files

Check these log files for debugging information:

- `logs/gengowatcher.log` - Main application logs
- `logs/accepted_jobs.log` - Auto-accepted job logs (if enabled)

## Limitations

1. **API Access**: The Gengo API for translators has limited functionality compared to customer APIs
2. **Captcha Requirements**: Some operations may still require manual captcha solving
3. **Rate Limits**: Gengo may impose rate limits on job acceptance operations
4. **Job Availability**: Jobs may be accepted by other translators before the system can process them

## Best Practices

1. **Start Conservative**: Begin with narrow reward ranges and monitor results
2. **Monitor Activity**: Regularly check your logs and acceptance statistics
3. **Update Credentials**: Keep your Gengo session token fresh
4. **Balance Settings**: Configure appropriate delays to appear human-like
5. **Captcha Budget**: Monitor your captcha solving service usage and costs