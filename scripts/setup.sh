#!/bin/bash
set -e

# Clarvis Setup Script
# Installs dependencies, configures MCP server, and sets up CLI.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

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

    if ! command -v claude &> /dev/null; then
        print_warning "claude CLI not found — skipping MCP config"
        echo "  Install Claude Code first: npm install -g @anthropic-ai/claude-code"
        echo "  Then re-run this script or manually run:"
        echo "    claude mcp add -s user clarvis -- $REPO_DIR/.venv/bin/python -m clarvis.server"
        return
    fi

    # Remove existing entry if present, then add fresh
    claude mcp remove -s user clarvis 2>/dev/null || true
    claude mcp add -s user clarvis -- "$REPO_DIR/.venv/bin/python" -m clarvis.server

    print_success "MCP server configured (user scope)"
}

install_cli() {
    print_header "Installing CLI..."

    chmod +x "$REPO_DIR/clarvis.sh"
    mkdir -p "$REPO_DIR/logs"

    # Find a writable bin directory on PATH
    local link_dir=""
    for dir in /opt/homebrew/bin /usr/local/bin; do
        if [ -d "$dir" ] && [ -w "$dir" ]; then
            link_dir="$dir"
            break
        fi
    done

    if [ -z "$link_dir" ]; then
        print_warning "No writable bin dir found on PATH"
        echo "  Manually add to PATH or symlink:"
        echo "    ln -sf $REPO_DIR/clarvis.sh /usr/local/bin/clarvis"
        return
    fi

    ln -sf "$REPO_DIR/clarvis.sh" "$link_dir/clarvis"
    print_success "CLI installed: clarvis (-> $link_dir/clarvis)"
}

configure_voice() {
    print_header "Configuring voice agent..."

    local voice_dir="$HOME/.clarvis/voice-project"
    mkdir -p "$voice_dir"

    # Voice project MCP config — points to this repo's server
    cat > "$voice_dir/.mcp.json" << MCPEOF
{
  "mcpServers": {
    "clarvis": {
      "command": "$REPO_DIR/.venv/bin/python",
      "args": ["-m", "clarvis.server"],
      "cwd": "$REPO_DIR"
    }
  }
}
MCPEOF

    print_success "Voice agent MCP config updated"
}

print_next_steps() {
    cat << EOF

════════════════════════════════════════════════════════════════

                    SETUP COMPLETE!

════════════════════════════════════════════════════════════════

Usage:
  clarvis start     Start daemon and widget
  clarvis stop      Stop all processes
  clarvis restart   Stop then start
  clarvis status    Show running processes
  clarvis logs      Tail daemon logs
  clarvis debug     Attach to voice agent session

Restart Claude Code to load the MCP server.

OPTIONAL: Enable GPS Location
  brew install corelocationcli
  CoreLocationCLI -j  # approve the popup once

════════════════════════════════════════════════════════════════

EOF
}

main() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║                      Clarvis Setup                           ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""

    check_dependencies
    setup_venv
    configure_mcp
    install_cli
    configure_voice

    print_success "Setup complete!"
    print_next_steps
}

main
