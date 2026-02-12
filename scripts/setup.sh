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

    # Required sibling repos
    if [ ! -d "$MONOREPO_DIR/clautify" ]; then
        print_error "clautify not found at $MONOREPO_DIR/clautify"
        echo "  git clone git@github.com:shepardxia/clautify.git $MONOREPO_DIR/clautify"
        missing=true
    else
        print_success "clautify found"
    fi

    if [ "$missing" = true ]; then
        print_error "Missing required sibling repos. Clone them and re-run."
        exit 1
    fi

    # Optional sibling repos (voice features)
    if [ ! -d "$MONOREPO_DIR/nanobuddy" ]; then
        echo ""
        read -rp "  Clone nanobuddy for wake word/voice features? [Y/n]: " clone_nano
        if [ -z "$clone_nano" ] || [[ "$clone_nano" =~ ^[Yy] ]]; then
            git clone https://github.com/shepardxia/nanobuddy.git "$MONOREPO_DIR/nanobuddy"
            print_success "nanobuddy cloned"
        else
            print_warning "Skipped — wake word/voice features won't be available"
        fi
    else
        print_success "nanobuddy found"
    fi
}

setup_venv() {
    print_header "Setting up Python environment..."

    cd "$REPO_DIR"
    uv sync --extra all
    print_success "All dependencies installed"
}

configure_mcp() {
    print_header "Configuring MCP server..."

    if command -v cmcp &> /dev/null; then
        # cmcp writes correct HTTP .mcp.json
        cd "$MONOREPO_DIR" && cmcp add clarvis
        print_success "MCP server configured via cmcp"
    elif command -v claude &> /dev/null; then
        # Fallback: write .mcp.json directly
        cat > "$MONOREPO_DIR/.mcp.json" << MCPEOF
{
  "mcpServers": {
    "clarvis": {
      "type": "http",
      "url": "http://127.0.0.1:7777/mcp"
    }
  }
}
MCPEOF
        print_success "MCP server configured (.mcp.json)"
    else
        print_warning "Neither cmcp nor claude CLI found — skipping MCP config"
        echo "  Install Claude Code: npm install -g @anthropic-ai/claude-code"
    fi
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

setup_home() {
    print_header "Setting up home directory..."

    mkdir -p "$MONOREPO_DIR/home"
    if [ ! -f "$MONOREPO_DIR/home/.mcp.json" ]; then
        cat > "$MONOREPO_DIR/home/.mcp.json" << MCPEOF
{
  "mcpServers": {
    "clarvis": {
      "type": "http",
      "url": "http://127.0.0.1:7778/mcp"
    }
  }
}
MCPEOF
    fi
    print_success "Home directory ready (memory tools on port 7778)"
}

check_env() {
    print_header "Checking environment..."

    local env_file="$REPO_DIR/.env"
    if [ -f "$env_file" ] && grep -q "ANTHROPIC_API_KEY" "$env_file"; then
        print_success "ANTHROPIC_API_KEY found in .env"
    elif [ -n "$ANTHROPIC_API_KEY" ]; then
        print_success "ANTHROPIC_API_KEY set in environment"
    else
        print_warning "ANTHROPIC_API_KEY not set (needed for whimsy verbs + token usage)"
        echo "  Create $REPO_DIR/.env with:"
        echo "    ANTHROPIC_API_KEY=sk-ant-..."
        echo "  Or export it in your shell profile."
    fi
}

setup_spotify() {
    print_header "Spotify setup (optional)..."

    if [ -f "$HOME/.config/clautify/session.json" ]; then
        print_success "Spotify session already configured"
        return
    fi

    echo "  Clautify controls Spotify playback. To set it up:"
    echo "  1. Open open.spotify.com in browser, log in"
    echo "  2. DevTools (F12) -> Application -> Cookies -> sp_dc"
    echo "  3. Copy the sp_dc cookie value"
    echo ""
    read -rp "  Paste sp_dc cookie (or press Enter to skip): " sp_dc
    if [ -n "$sp_dc" ]; then
        "$REPO_DIR/.venv/bin/python" -c "from clautify.dsl import SpotifySession; SpotifySession.setup('$sp_dc')"
        print_success "Spotify session saved to ~/.config/clautify/session.json"
    else
        print_warning "Skipped — run SpotifySession.setup('cookie') later to enable music"
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
    setup_spotify
    configure_mcp
    install_cli
    setup_home

    print_success "Setup complete!"
    print_next_steps
}

main
