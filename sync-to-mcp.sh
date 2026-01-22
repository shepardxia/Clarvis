#!/bin/bash
# Sync central-hub changes from desktop directory to MCP server location
# Usage: ./sync-to-mcp.sh

set -e

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_DIR="$HOME/.claude/mcp-servers/central-hub"

echo "📦 Syncing central-hub to MCP server..."

if [ ! -d "$MCP_DIR" ]; then
    echo "❌ MCP server directory not found: $MCP_DIR"
    exit 1
fi

# Create mcp-server subdirectory if needed
mkdir -p "$MCP_DIR/mcp-server"

# Sync MCP server files (highest priority - code changes)
echo "  📝 Syncing server.py..."
cp "$SOURCE_DIR/mcp-server/server.py" "$MCP_DIR/server.py"

if [ -f "$SOURCE_DIR/mcp-server/usage_monitor.py" ]; then
    echo "  📝 Syncing usage_monitor.py..."
    cp "$SOURCE_DIR/mcp-server/usage_monitor.py" "$MCP_DIR/usage_monitor.py"
fi

if [ -f "$SOURCE_DIR/mcp-server/pyproject.toml" ]; then
    echo "  📝 Syncing pyproject.toml..."
    cp "$SOURCE_DIR/mcp-server/pyproject.toml" "$MCP_DIR/pyproject.toml"
fi

# Sync HTML control panel (UI changes)
if [ -f "$SOURCE_DIR/control-panel.html" ]; then
    echo "  🎨 Syncing control-panel.html..."
    cp "$SOURCE_DIR/control-panel.html" "$MCP_DIR/control-panel.html"
fi

# Sync control server
if [ -f "$SOURCE_DIR/control-server.py" ]; then
    echo "  🖥️  Syncing control-server.py..."
    cp "$SOURCE_DIR/control-server.py" "$MCP_DIR/control-server.py"
fi

echo "✓ Sync complete!"
echo ""
echo "Next steps:"
echo "  1. Restart Claude Code: Command+R"
echo "  2. Or: killall 'Claude Code' (if running)"
echo ""
