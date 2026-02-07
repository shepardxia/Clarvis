#!/bin/bash
set -e

# Clarvis Setup Script
# Installs dependencies, configures MCP server, and sets up CLI.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
MONOREPO_DIR="$(dirname "$REPO_DIR")"

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
    else
        print_error "uv is required. Install it:"
        echo "  brew install uv"
        echo "  # or: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
}

check_sibling_repos() {
    print_header "Checking sibling repositories..."

    local missing=false

    if [ ! -d "$MONOREPO_DIR/SpotAPI" ]; then
        print_error "SpotAPI not found at $MONOREPO_DIR/SpotAPI"
        echo "  git clone git@github.com:shepardxia/clautify.git $MONOREPO_DIR/SpotAPI"
        missing=true
    else
        print_success "SpotAPI found"
    fi

    if [ ! -d "$MONOREPO_DIR/hey-buddy" ]; then
        print_error "hey-buddy not found at $MONOREPO_DIR/hey-buddy"
        echo "  git clone git@github.com:shepardxia/hey-buddy.git $MONOREPO_DIR/hey-buddy"
        missing=true
    else
        print_success "hey-buddy found"
    fi

    if [ "$missing" = true ]; then
        print_error "Missing sibling repos. Clone them and re-run."
        exit 1
    fi
}

setup_venv() {
    print_header "Setting up Python environment..."

    cd "$REPO_DIR"
    uv sync
    print_success "Dependencies installed (including sibling editable deps)"
}

configure_mcp() {
    print_header "Configuring MCP server..."

    if ! command -v claude &> /dev/null; then
        print_warning "claude CLI not found — skipping MCP config"
        echo "  Install Claude Code first: npm install -g @anthropic-ai/claude-code"
        echo "  Then re-run this script or manually run:"
        echo "    claude mcp add -s user clarvis -- uv run --project $REPO_DIR clarvis"
        return
    fi

    # Remove existing entry if present, then add fresh
    claude mcp remove -s user clarvis 2>/dev/null || true
    claude mcp add -s user clarvis -- uv run --project "$REPO_DIR" clarvis

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

    # Voice agent uses monorepo root as its project dir — write MCP config there
    cat > "$MONOREPO_DIR/.mcp.json" << MCPEOF
{
  "mcpServers": {
    "clarvis": {
      "command": "uv",
      "args": ["run", "--project", "$REPO_DIR", "clarvis"],
      "cwd": "$REPO_DIR"
    }
  }
}
MCPEOF

    print_success "Voice agent MCP config written to $MONOREPO_DIR/.mcp.json"
}

check_env() {
    print_header "Checking environment..."

    local env_file="$REPO_DIR/.env"
    if [ -f "$env_file" ] && grep -q "ANTHROPIC_API_KEY" "$env_file"; then
        print_success "ANTHROPIC_API_KEY found in .env"
    elif [ -n "$ANTHROPIC_API_KEY" ]; then
        print_success "ANTHROPIC_API_KEY set in environment"
    else
        print_warning "ANTHROPIC_API_KEY not set"
        echo "  Create $REPO_DIR/.env with:"
        echo "    ANTHROPIC_API_KEY=sk-ant-..."
        echo "  Or export it in your shell profile."
    fi
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
    check_sibling_repos
    setup_venv
    check_env
    configure_mcp
    install_cli
    configure_voice

    print_success "Setup complete!"
    print_next_steps
}

main
