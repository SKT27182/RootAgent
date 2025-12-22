#!/bin/bash

# RootAgent Setup Script
# This script sets up the local development environment.

set -e  # Exit on any error

echo "================================================"
echo "  RootAgent - Development Environment Setup"
echo "================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print status messages
info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check for required tools
check_requirements() {
    info "Checking required tools..."
    
    if ! command -v python3 &> /dev/null; then
        error "Python 3 is required but not installed."
        exit 1
    fi
    
    if ! command -v docker &> /dev/null; then
        warn "Docker is not installed. Required for Redis and production deployment."
    fi
    
    info "Python version: $(python3 --version)"
}

# Create virtual environment if it doesn't exist
setup_venv() {
    if [ ! -d ".venv" ]; then
        info "Creating Python virtual environment..."
        python3 -m venv .venv
    else
        info "Virtual environment already exists."
    fi
    
    info "Activating virtual environment..."
    source .venv/bin/activate
    
    # Check and install uv if needed
    if ! command -v uv &> /dev/null; then
        info "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi
}

# Install Python dependencies
install_dependencies() {
    info "Installing Python dependencies..."
    
    if ! command -v uv &> /dev/null; then
        error "uv is required but not installed. Visit https://docs.astral.sh/uv/getting-started/"
        exit 1
    fi
    
    info "Installing dependencies with uv..."
    uv sync
}

# Setup environment file
setup_env() {
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            info "Creating .env from .env.example..."
            cp .env.example .env
            warn "Please edit .env and add your API keys!"
        else
            error ".env.example not found!"
            exit 1
        fi
    else
        info ".env file already exists."
    fi
}

# Generate JWT secret key
generate_jwt_secret() {
    if grep -q "change-this-in-production" .env 2>/dev/null; then
        info "Generating secure JWT secret key..."
        JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
        
        # Platform-independent sed (macOS compatibility)
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s/change-this-in-production/$JWT_SECRET/" .env
        else
            sed -i "s/change-this-in-production/$JWT_SECRET/" .env
        fi
        
        info "JWT secret key generated and saved to .env"
    fi
}

# Main setup flow
main() {
    check_requirements
    setup_venv
    install_dependencies
    setup_env
    generate_jwt_secret
    
    echo ""
    echo "================================================"
    info "Setup complete!"
    echo "================================================"
    echo ""
    echo "Next steps:"
    echo "  1. Edit .env and add your LLM_API_KEY"
    echo "  2. Run 'make dev' to start development server"
    echo "  3. Open http://localhost:8000 (backend API)"
    echo "  4. Run 'make dev-frontend' in another terminal for frontend"
    echo ""
    echo "Or use Docker:"
    echo "  docker compose up --build"
    echo ""
    echo "For all available commands: make help"
}

main "$@"
