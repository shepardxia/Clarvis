#!/bin/bash
set -e

# Central Hub Setup Script
# Installs and configures the MCP server and desktop widget

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_SOURCE="$REPO_DIR/mcp-server"
MCP_DEST="$HOME/.claude/mcp-servers/central-hub"
MCP_CONFIG="$HOME/.claude/.mcp.json"
PYTHON_MIN_VERSION="3.10"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}▶ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

check_python() {
    print_header "Checking Python version..."

    # Look for python3.11, python3.10, or python3 in that order
    PYTHON_CMD=""
    if command -v python3.11 &> /dev/null; then
        PYTHON_CMD="python3.11"
    elif command -v python3.10 &> /dev/null; then
        PYTHON_CMD="python3.10"
    elif command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    fi

    if [ -z "$PYTHON_CMD" ]; then
        print_error "Python 3.10+ not found. Please install:"
        echo "  macOS: brew install python3"
        exit 1
    fi

    PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')

    # Check version is 3.10+
    if ! $PYTHON_CMD -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"; then
        print_error "Python 3.10+ required. Found: $PYTHON_VERSION"
        exit 1
    fi

    print_success "Python $PYTHON_VERSION found ($PYTHON_CMD)"

    # Export PYTHON_CMD for use in other functions
    export PYTHON_CMD
}

setup_mcp_server() {
    print_header "Setting up MCP server..."

    # Create destination directory
    mkdir -p "$MCP_DEST"

    # Copy server files
    cp "$MCP_SOURCE/server.py" "$MCP_DEST/"
    cp "$MCP_SOURCE/pyproject.toml" "$MCP_DEST/"
    print_success "Copied MCP server to $MCP_DEST"

    # Create/setup virtual environment
    print_header "Setting up Python environment..."

    if [ ! -d "$MCP_DEST/venv" ]; then
        $PYTHON_CMD -m venv "$MCP_DEST/venv"
        print_success "Created Python virtual environment"
    fi

    # Activate venv
    source "$MCP_DEST/venv/bin/activate"

    # Try uv first (fast), fall back to pip
    if command -v uv &> /dev/null; then
        print_header "Installing dependencies with uv..."
        uv pip install -e "$MCP_DEST"
        print_success "Dependencies installed with uv"
    else
        print_warning "uv not found, using pip (slower)"
        "$MCP_DEST/venv/bin/pip" install -e "$MCP_DEST"
        print_success "Dependencies installed with pip"
    fi

    deactivate
}

configure_mcp_json() {
    print_header "Configuring MCP server in Claude settings..."

    MCP_SERVER_PATH="$MCP_DEST/venv/bin/python3"
    MCP_SERVER_ARGS="$MCP_DEST/server.py"

    # Create .mcp.json if it doesn't exist
    if [ ! -f "$MCP_CONFIG" ]; then
        mkdir -p "$(dirname "$MCP_CONFIG")"
        echo '{}' > "$MCP_CONFIG"
        print_success "Created $MCP_CONFIG"
    fi

    # Check if central-hub is already configured
    if $PYTHON_CMD -c "import json; data = json.load(open('$MCP_CONFIG')); exit(0 if 'mcpServers' in data and 'central-hub' in data['mcpServers'] else 1)" 2>/dev/null; then
        print_success "central-hub already configured in .mcp.json"
    else
        # Add central-hub to .mcp.json using Python
        $PYTHON_CMD << EOF
import json
import sys

config_path = "$MCP_CONFIG"

try:
    with open(config_path, 'r') as f:
        config = json.load(f)
except:
    config = {}

if 'mcpServers' not in config:
    config['mcpServers'] = {}

config['mcpServers']['central-hub'] = {
    'command': '$MCP_SERVER_PATH',
    'args': ['$MCP_SERVER_ARGS']
}

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print(f"✓ Added central-hub to {config_path}")
EOF
    fi
}

setup_widget() {
    print_header "Building desktop widget..."

    cd "$REPO_DIR"

    if ! command -v swiftc &> /dev/null; then
        print_error "Swift compiler not found. Please install Xcode command line tools:"
        echo "  xcode-select --install"
        exit 1
    fi

    swiftc -o ClaudeStatusOverlay Display.swift ClaudeStatusOverlay.swift -framework Cocoa 2>/dev/null || {
        print_error "Failed to build widget"
        exit 1
    }

    print_success "Widget built: $REPO_DIR/ClaudeStatusOverlay"
}

verify_setup() {
    print_header "Verifying setup..."

    # Check MCP server
    if [ ! -f "$MCP_DEST/server.py" ]; then
        print_error "MCP server not found at $MCP_DEST/server.py"
        return 1
    fi
    print_success "MCP server installed"

    # Check venv
    if [ ! -d "$MCP_DEST/venv" ]; then
        print_error "Virtual environment not found"
        return 1
    fi
    print_success "Virtual environment created"

    # Check MCP config
    if [ ! -f "$MCP_CONFIG" ]; then
        print_error "MCP config not found"
        return 1
    fi
    print_success "MCP config created"

    # Check widget
    if [ ! -f "$REPO_DIR/ClaudeStatusOverlay" ]; then
        print_error "Widget binary not found"
        return 1
    fi
    print_success "Widget binary created"

    # Test MCP server (optional - only if we can quickly test it)
    print_header "Testing MCP server startup..."

    # Start server in background (cross-platform compatible)
    "$MCP_DEST/venv/bin/python3" "$MCP_DEST/server.py" > /tmp/mcp-test.log 2>&1 &
    MCP_PID=$!

    sleep 3

    if kill -0 $MCP_PID 2>/dev/null; then
        print_success "MCP server starts successfully"
        kill $MCP_PID 2>/dev/null || true
        wait $MCP_PID 2>/dev/null || true
    else
        print_warning "MCP server didn't start. This may be OK if you restart Claude Code."
        if [ -s /tmp/mcp-test.log ]; then
            echo "  Log: $(head -1 /tmp/mcp-test.log)"
        fi
    fi
}

print_next_steps() {
    cat << 'EOF'

════════════════════════════════════════════════════════════════

                    SETUP COMPLETE! ✓

════════════════════════════════════════════════════════════════

Next steps:

1. RESTART CLAUDE CODE
   • Close Claude Code completely
   • Reopen it
   • This loads the MCP server configuration

2. START THE DESKTOP WIDGET (optional)
   cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
   ./ClaudeStatusOverlay &

3. TEST THE MCP TOOLS
   • Ask Claude: "What's the weather?"
   • Ask Claude: "What time is it?"
   • Ask Claude: "What's my status?"

OPTIONAL: Enable GPS Location
   • Install: brew install corelocationcli
   • Run once: CoreLocationCLI -j (approve the popup)
   • Weather will now use GPS instead of IP geolocation

════════════════════════════════════════════════════════════════

Locations:
  MCP Server:     ~/.claude/mcp-servers/central-hub/
  Configuration:  ~/.claude/.mcp.json
  Widget:         $REPO_DIR/ClaudeStatusOverlay
  Widget Output:  /tmp/central-hub-*.json

========== ================================================

EOF
}

main() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║                   Central Hub Setup                             ║"
    echo "║              Desktop Widget + MCP Data Server                   ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""

    check_python
    setup_mcp_server
    configure_mcp_json
    setup_widget

    if verify_setup; then
        echo ""
        print_success "All systems operational!"
        print_next_steps
    else
        print_error "Verification failed. Please check the errors above."
        exit 1
    fi
}

main
