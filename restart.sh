#!/bin/bash
# Restart Clarvis daemon and widget

cd "$(dirname "$0")"

echo "Stopping services..."
pkill -f "clarvis" 2>/dev/null
pkill -f "ClarvisWidget" 2>/dev/null
sleep 1

echo "Starting daemon..."
uv run python -m clarvis.daemon &
sleep 0.5

echo "Starting widget..."
./ClarvisWidget/ClarvisWidget &>/dev/null &

echo "Done. PIDs:"
echo "  Daemon: $(pgrep -f 'clarvis')"
echo "  Widget: $(pgrep -f 'ClarvisWidget')"

