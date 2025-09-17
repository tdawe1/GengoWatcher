# GengoWatcher Frontend Launch Guide

## Overview

GengoWatcher includes a modern web-based user interface built with React that provides an alternative to the terminal-based interface. This guide explains how to launch and use the web frontend.

## Prerequisites

Before launching the frontend, ensure you have:

1. Python 3.8 or higher installed
2. All required Python packages installed:
   ```bash
   pip install -r requirements.txt
   ```
3. Node.js and npm installed (for development only)

## Launching the Web Interface

### Option 1: Using the Standalone Web Server (Recommended)

The easiest way to launch the web interface is using the standalone web server:

```bash
cd /home/thomas/GengoWatcher
python web_server.py --port 8001
```

This will start the web server on port 8001. You can then access the web interface at:
http://localhost:8001/web

### Option 2: Starting with the Main Application

You can also start the web interface alongside the terminal interface:

```bash
cd /home/thomas/GengoWatcher
python -m gengowatcher.main --web
```

Or start only the web interface:
```bash
cd /home/thomas/GengoWatcher
python -m gengowatcher.main --web-only --web-port 8001
```

## Accessing the Web Interface

Once the server is running, you can access the web interface at:
http://localhost:8001/web

The first time you access the interface, you may need to authenticate using an API key. The system will automatically generate an API key for you.

## Key Features

The web interface provides:

1. **Dashboard View**: Real-time status monitoring
2. **Job Listings**: Browse and manage available jobs
3. **Configuration Management**: Modify settings through the UI
4. **Statistics and Analytics**: View performance metrics
5. **Command Execution**: Control the watcher (pause, resume, check, etc.)

## Development Workflow

If you want to develop or modify the frontend:

1. Navigate to the frontend directory:
   ```bash
   cd /home/thomas/GengoWatcher/frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Start the development server:
   ```bash
   npm run dev
   ```

4. Access the development interface at:
   http://localhost:5173

5. To build for production:
   ```bash
   npm run build
   ```

## Troubleshooting

### Common Issues:

1. **Port Conflicts**: If port 8001 is in use, specify a different port:
   ```bash
   python web_server.py --port 8080
   ```

2. **Missing Dependencies**: Ensure all requirements are installed:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configuration Issues**: The system will create a default config.ini if one doesn't exist.

### Checking Server Status:

You can verify the server is running by checking:
```bash
curl http://localhost:8001/api/status
```

## Security Notes

The web interface uses API key authentication to prevent unauthorized access. The API key is automatically generated and can be retrieved from:
http://localhost:8001/api/auth/key

For production deployments, ensure proper firewall rules and consider using HTTPS.