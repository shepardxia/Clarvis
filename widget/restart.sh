#!/bin/bash
# Restart the Claude Status Overlay widget

WIDGET_DIR="$(cd "$(dirname "$0")" && pwd)"

pkill -f ClaudeStatusOverlay
rm -f /tmp/claude-status-overlay.lock
rm -f /tmp/claude-status-cache.json

cd "$WIDGET_DIR"

# Rebuild Swift overlay (Display.swift + main app)
swiftc -o ClaudeStatusOverlay Display.swift ClaudeStatusOverlay.swift -framework Cocoa

# Start overlay (it watches /tmp/claude-status.json)
./ClaudeStatusOverlay &

echo "Widget restarted"
echo "Note: Status updates via ~/.claude/hooks/status-hook.sh"
