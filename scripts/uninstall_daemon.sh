#!/bin/bash
# Uninstall LaunchAgent for central-hub daemon

set -e

LAUNCH_AGENT_FILE="$HOME/Library/LaunchAgents/com.centralhub.daemon.plist"

if [ -f "$LAUNCH_AGENT_FILE" ]; then
    echo "Unloading daemon LaunchAgent..."
    launchctl unload "$LAUNCH_AGENT_FILE" 2>/dev/null || true
    
    echo "Removing LaunchAgent file..."
    rm "$LAUNCH_AGENT_FILE"
    
    echo "✓ Daemon LaunchAgent uninstalled!"
else
    echo "LaunchAgent not found at $LAUNCH_AGENT_FILE"
fi
