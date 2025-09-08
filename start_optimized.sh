#!/bin/bash

# Startup script for optimized Nova Sonic voice AI system
# This script ensures proper setup and launches the optimized server

set -e  # Exit on error

echo "========================================"
echo "Nova Sonic Optimized Voice AI System"
echo "========================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to print colored messages
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Check Python version
echo "Checking Python version..."
if command_exists python3; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)
    
    if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 10 ]; then
        print_success "Python $PYTHON_VERSION found"
    else
        print_error "Python 3.10+ required (found $PYTHON_VERSION)"
        exit 1
    fi
else
    print_error "Python3 not found"
    exit 1
fi

# Check for .env file
echo "Checking environment configuration..."
if [ ! -f .env ]; then
    print_error ".env file not found"
    echo "Please create .env file with required configuration"
    echo "You can copy from example_env: cp example_env .env"
    exit 1
else
    print_success ".env file found"
fi

# Check required environment variables
source .env
REQUIRED_VARS=(
    "TWILIO_ACCOUNT_SID"
    "TWILIO_AUTH_TOKEN"
    "TWILIO_PHONE_NUMBER"
    "AWS_REGION"
    "aws_access_key_id"
    "aws_secret_access_key"
    "PUBLIC_HOST"
)

MISSING_VARS=()
for VAR in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!VAR}" ]; then
        MISSING_VARS+=($VAR)
    fi
done

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    print_error "Missing required environment variables:"
    for VAR in "${MISSING_VARS[@]}"; do
        echo "  - $VAR"
    done
    exit 1
else
    print_success "All required environment variables set"
fi

# Check for system_prompt.txt
echo "Checking system prompt..."
if [ ! -f system_prompt.txt ]; then
    print_warning "system_prompt.txt not found, creating default..."
    echo "You are a helpful AI assistant." > system_prompt.txt
fi
print_success "System prompt ready"

# Create virtual environment if it doesn't exist
echo "Checking Python virtual environment..."
if [ ! -d "venv" ]; then
    print_warning "Virtual environment not found, creating..."
    python3 -m venv venv
    print_success "Virtual environment created"
fi

# Activate virtual environment
source venv/bin/activate
print_success "Virtual environment activated"

# Install/upgrade dependencies
echo "Checking dependencies..."
if [ -f "requirements_optimized.txt" ]; then
    print_warning "Installing optimized requirements..."
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements_optimized.txt
    print_success "Dependencies installed"
else
    print_error "requirements_optimized.txt not found"
    exit 1
fi

# Create logs directory
if [ ! -d "logs" ]; then
    mkdir -p logs
    print_success "Logs directory created"
fi

# Check if old server is running
if lsof -i:7860 >/dev/null 2>&1; then
    print_warning "Port 7860 is already in use"
    echo "Do you want to stop the existing process? (y/n)"
    read -r response
    if [ "$response" = "y" ]; then
        PID=$(lsof -t -i:7860)
        kill -9 $PID
        print_success "Stopped existing process"
        sleep 2
    else
        print_error "Cannot start server - port in use"
        exit 1
    fi
fi

# Run migration check
echo "Checking for old Flask app..."
if [ -f "app.py" ] && [ -f "server.py" ]; then
    print_warning "Both old (app.py) and new (server.py) servers found"
    echo "Running optimized server (server.py)..."
fi

# Display configuration
echo ""
echo "========================================"
echo "Configuration:"
echo "========================================"
echo "Public Host: ${PUBLIC_HOST}"
echo "Port: ${PORT:-7860}"
echo "HTTPS: ${USE_HTTPS:-false}"
echo "AWS Region: ${AWS_REGION}"
echo "Max Call Duration: ${MAX_CONVO_SECS:-600} seconds"
echo "Silence Threshold: ${TURN_SILENCE_MS:-700} ms"
echo "========================================"
echo ""

# Start the server
echo "Starting optimized Nova Sonic server..."
echo "Server will be available at: http://localhost:${PORT:-7860}"
echo ""
echo "Press Ctrl+C to stop the server"
echo "========================================"

# Run with proper error handling
if [ "$1" = "--docker" ]; then
    print_warning "Starting with Docker..."
    docker-compose -f docker-compose.optimized.yml up --build
elif [ "$1" = "--production" ]; then
    print_warning "Starting in production mode..."
    gunicorn server:app \
        --worker-class uvicorn.workers.UvicornWorker \
        --workers 4 \
        --bind 0.0.0.0:${PORT:-7860} \
        --access-logfile logs/access.log \
        --error-logfile logs/error.log \
        --log-level info
else
    # Development mode
    python3 -u server.py
fi
