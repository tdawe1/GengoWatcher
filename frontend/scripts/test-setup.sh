#!/bin/bash

# Test Environment Setup Script for GengoWatcher E2E Tests
# This script sets up both backend and frontend for E2E testing

set -e

echo "🚀 Setting up GengoWatcher E2E test environment..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
BACKEND_PORT=8001
FRONTEND_PORT=5173
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

# Function to check if port is in use
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null ; then
        echo -e "${RED}❌ Port $port is already in use${NC}"
        return 1
    fi
    return 0
}

# Function to wait for service to be ready
wait_for_service() {
    local url=$1
    local service_name=$2
    local max_attempts=30
    local attempt=1

    echo -e "${YELLOW}⏳ Waiting for $service_name to be ready at $url${NC}"

    while [ $attempt -le $max_attempts ]; do
        if curl -s --max-time 5 "$url" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ $service_name is ready!${NC}"
            return 0
        fi

        echo "Attempt $attempt/$max_attempts: $service_name not ready yet..."
        sleep 2
        ((attempt++))
    done

    echo -e "${RED}❌ $service_name failed to start within expected time${NC}"
    return 1
}

# Check if required tools are installed
check_dependencies() {
    local missing_deps=()

    if ! command -v python &> /dev/null; then
        missing_deps+=("python")
    fi

    if ! command -v node &> /dev/null; then
        missing_deps+=("node")
    fi

    if ! command -v npm &> /dev/null; then
        missing_deps+=("npm")
    fi

    if [ ${#missing_deps[@]} -ne 0 ]; then
        echo -e "${RED}❌ Missing dependencies: ${missing_deps[*]}${NC}"
        echo "Please install the missing dependencies and try again."
        exit 1
    fi

    echo -e "${GREEN}✅ All dependencies are installed${NC}"
}

# Setup backend
setup_backend() {
    echo -e "${YELLOW}🔧 Setting up backend...${NC}"

    cd "$BACKEND_DIR"

    # Check if virtual environment exists
    if [ ! -d "venv" ]; then
        echo "Creating Python virtual environment..."
        python -m venv venv
    fi

    # Activate virtual environment
    source venv/bin/activate

    # Install/update dependencies
    echo "Installing Python dependencies..."
    pip install -r requirements.txt
    pip install -r requirements-dev.txt

    # Check if backend port is available
    if ! check_port $BACKEND_PORT; then
        echo -e "${RED}❌ Backend port $BACKEND_PORT is in use. Please free it or change the port.${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ Backend setup complete${NC}"
}

# Setup frontend
setup_frontend() {
    echo -e "${YELLOW}🔧 Setting up frontend...${NC}"

    cd "$FRONTEND_DIR"

    # Install dependencies
    echo "Installing Node.js dependencies..."
    npm install

    # Check if frontend port is available
    if ! check_port $FRONTEND_PORT; then
        echo -e "${RED}❌ Frontend port $FRONTEND_PORT is in use. Please free it or change the port.${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ Frontend setup complete${NC}"
}

# Start backend service
start_backend() {
    echo -e "${YELLOW}🚀 Starting backend service...${NC}"

    cd "$BACKEND_DIR"
    source venv/bin/activate

    # Start backend in background
    python -m gengowatcher.web &
    BACKEND_PID=$!

    echo $BACKEND_PID > /tmp/gengowatcher-backend.pid

    # Wait for backend to be ready
    wait_for_service "http://localhost:$BACKEND_PORT/api/health" "Backend"

    echo -e "${GREEN}✅ Backend started with PID: $BACKEND_PID${NC}"
}

# Start frontend service
start_frontend() {
    echo -e "${YELLOW}🚀 Starting frontend service...${NC}"

    cd "$FRONTEND_DIR"

    # Configure API URL for tests
    export VITE_API_URL="http://localhost:$BACKEND_PORT"

    # Start frontend in background
    npm run dev &
    FRONTEND_PID=$!

    echo $FRONTEND_PID > /tmp/gengowatcher-frontend.pid

    # Wait for frontend to be ready
    wait_for_service "http://localhost:$FRONTEND_PORT" "Frontend"

    echo -e "${GREEN}✅ Frontend started with PID: $FRONTEND_PID${NC}"
}

# Stop services
stop_services() {
    echo -e "${YELLOW}🛑 Stopping services...${NC}"

    if [ -f /tmp/gengowatcher-backend.pid ]; then
        BACKEND_PID=$(cat /tmp/gengowatcher-backend.pid)
        if kill -0 $BACKEND_PID 2>/dev/null; then
            echo "Stopping backend (PID: $BACKEND_PID)..."
            kill $BACKEND_PID
            wait $BACKEND_PID 2>/dev/null || true
        fi
        rm -f /tmp/gengowatcher-backend.pid
    fi

    if [ -f /tmp/gengowatcher-frontend.pid ]; then
        FRONTEND_PID=$(cat /tmp/gengowatcher-frontend.pid)
        if kill -0 $FRONTEND_PID 2>/dev/null; then
            echo "Stopping frontend (PID: $FRONTEND_PID)..."
            kill $FRONTEND_PID
            wait $FRONTEND_PID 2>/dev/null || true
        fi
        rm -f /tmp/gengowatcher-frontend.pid
    fi

    echo -e "${GREEN}✅ Services stopped${NC}"
}

# Cleanup function
cleanup() {
    stop_services
    exit
}

# Main execution
main() {
    local action=${1:-"start"}

    case $action in
        "setup")
            check_dependencies
            setup_backend
            setup_frontend
            echo -e "${GREEN}🎉 Setup complete! Run '$0 start' to start the services.${NC}"
            ;;
        "start")
            check_dependencies
            setup_backend
            setup_frontend
            start_backend
            start_frontend
            echo -e "${GREEN}🎉 Test environment is ready!${NC}"
            echo -e "${YELLOW}📋 Services running:${NC}"
            echo "  - Backend: http://localhost:$BACKEND_PORT"
            echo "  - Frontend: http://localhost:$FRONTEND_PORT"
            echo -e "${YELLOW}💡 Run 'npm run test:e2e' from frontend/ to run tests${NC}"
            echo -e "${YELLOW}💡 Press Ctrl+C to stop services${NC}"
            # Wait for Ctrl+C
            trap cleanup SIGINT SIGTERM
            wait
            ;;
        "stop")
            stop_services
            ;;
        "restart")
            stop_services
            sleep 2
            main "start"
            ;;
        *)
            echo "Usage: $0 {setup|start|stop|restart}"
            echo ""
            echo "Commands:"
            echo "  setup   - Install dependencies and setup environment"
            echo "  start   - Start both backend and frontend services"
            echo "  stop    - Stop all running services"
            echo "  restart - Restart all services"
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"