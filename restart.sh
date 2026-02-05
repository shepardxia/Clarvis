#!/bin/bash
# Restart Clarvis daemon and widget.

cd "$(dirname "$0")"

# Kill existing
pkill -f 'clarvis\.daemon' 2>/dev/null
pkill -f 'ClarvisWidget' 2>/dev/null
sleep 0.5

mkdir -p logs

# Start
.venv/bin/python -m clarvis.daemon >>logs/daemon.out.log 2>>logs/daemon.err.log &
./ClarvisWidget/ClarvisWidget >>logs/widget.out.log 2>>logs/widget.err.log &

sleep 1
DPID=$(pgrep -f 'clarvis\.daemon' | head -1)
WPID=$(pgrep -f 'ClarvisWidget' | head -1)

echo "daemon: ${DPID:-FAILED}"
echo "widget: ${WPID:-FAILED}"
