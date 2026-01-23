#!/bin/bash
set -e

# Clarvis Setup Script
# Installs MCP server and configures Claude Code

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
MCP_CONFIG="$HOME/.claude/.mcp.json"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() { echo -e "${BLUE}▶ $1${NC}"; }
print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_error() { echo -e "${RED}✗ $1${NC}"; }

check_dependencies() {
    print_header "Checking dependencies..."

    # Check for uv (preferred) or python3
    if command -v uv &> /dev/null; then
        print_success "uv found"
        USE_UV=true
    elif command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"; then
            print_success "Python $PYTHON_VERSION found"
            USE_UV=false
        else
            print_error "Python 3.10+ required. Found: $PYTHON_VERSION"
            exit 1
        fi
    else
        print_error "Neither uv nor python3 found. Install one:"
        echo "  brew install uv    # recommended"
        echo "  brew install python3"
        exit 1
    fi
}

setup_venv() {
    print_header "Setting up Python environment..."

    cd "$REPO_DIR"

    if [ "$USE_UV" = true ]; then
        uv sync
        print_success "Dependencies installed with uv"
    else
        if [ ! -d ".venv" ]; then
            python3 -m venv .venv
            print_success "Created virtual environment"
        fi
        .venv/bin/pip install -e .
        print_success "Dependencies installed with pip"
    fi
}

configure_mcp() {
    print_header "Configuring MCP server..."

    mkdir -p "$(dirname "$MCP_CONFIG")"

    # Build the command based on uv or venv
    if [ "$USE_UV" = true ]; then
        MCP_COMMAND="uv"
        MCP_ARGS='["run", "--directory", "'"$REPO_DIR"'", "python", "-m", "central_hub.server"]'
    else
        MCP_COMMAND="$REPO_DIR/.venv/bin/python"
        MCP_ARGS='["-m", "central_hub.server"]'
    fi

    # Create or update .mcp.json
    python3 << EOF
import json
import os

config_path = "$MCP_CONFIG"

try:
    with open(config_path, 'r') as f:
        config = json.load(f)
except:
    config = {}

if 'mcpServers' not in config:
    config['mcpServers'] = {}

config['mcpServers']['central-hub'] = {
    'command': '$MCP_COMMAND',
    'args': $MCP_ARGS
}

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print("Added central-hub to", config_path)
EOF

    print_success "MCP server configured"
}

setup_daemon() {
    print_header "Setting up background daemon (optional)..."

    PLIST_SRC="$SCRIPT_DIR/com.centralhub.daemon.plist"
    PLIST_DST="$HOME/Library/LaunchAgents/com.central-hub.refresh.plist"

    if [ -f "$PLIST_SRC" ]; then
        # Update paths in plist
        sed "s|/path/to/central-hub|$REPO_DIR|g" "$PLIST_SRC" > "$PLIST_DST"
        launchctl unload "$PLIST_DST" 2>/dev/null || true
        launchctl load "$PLIST_DST"
        print_success "Daemon installed and started"
    else
        print_warning "Daemon plist not found, skipping"
    fi
}

print_next_steps() {
    cat << EOF

════════════════════════════════════════════════════════════════

                    SETUP COMPLETE! ✓

════════════════════════════════════════════════════════════════

Next steps:

1. RESTART CLAUDE CODE
   Close and reopen Claude Code to load the MCP server

2. START THE WIDGET (optional)
   $REPO_DIR/ClarvisWidget/ClarvisWidget &

3. TEST MCP TOOLS
   Ask Claude: "What's the weather?"
   Ask Claude: "What time is it?"

OPTIONAL: Enable GPS Location
   brew install corelocationcli
   CoreLocationCLI -j  # approve the popup once

════════════════════════════════════════════════════════════════

Locations:
  Repository:     $REPO_DIR
  MCP Config:     $MCP_CONFIG
  Widget:         $REPO_DIR/ClarvisWidget/ClarvisWidget

════════════════════════════════════════════════════════════════

EOF
}

main() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║                      Clarvis Setup                             ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""

    check_dependencies
    setup_venv
    configure_mcp
    setup_daemon

    print_success "Setup complete!"
    print_next_steps
}

main
