#!/bin/bash
# Clarvis process manager.
# Usage: ./clarvis.sh [start|stop|restart|status|logs]

cd "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0")")"

pid_daemon() { pgrep -f 'clarvis\.daemon' | head -1; }
pid_widget() { pgrep -f 'ClarvisWidget' | head -1; }

do_stop() {
    pkill -f 'clarvis\.daemon' 2>/dev/null
    pkill -f 'ClarvisWidget' 2>/dev/null
    sleep 0.5
    # Force-kill stragglers
    pkill -9 -f 'clarvis\.daemon' 2>/dev/null
    pkill -9 -f 'ClarvisWidget' 2>/dev/null
    rm -f /tmp/clarvis-widget.lock /tmp/clarvis-daemon.sock /tmp/clarvis-widget.sock
    echo "stopped"
}

build_widget() {
    local src=ClarvisWidget/main.swift
    local bin=ClarvisWidget/ClarvisWidget
    if [ "$src" -nt "$bin" ]; then
        echo "widget: rebuilding..."
        swiftc -O -o "$bin" "$src" \
            -framework Cocoa -framework Foundation \
            -framework Speech -framework AVFoundation 2>>logs/widget.err.log
        if [ $? -ne 0 ]; then
            echo "widget: BUILD FAILED (see logs/widget.err.log)"
            return 1
        fi
    fi
    return 0
}

do_start() {
    mkdir -p logs
    uv sync --quiet 2>/dev/null || true
    if [ -n "$(pid_daemon)" ]; then
        echo "daemon: already running ($(pid_daemon))"
    else
        .venv/bin/python -m clarvis.daemon >>logs/daemon.out.log 2>>logs/daemon.err.log &
        sleep 1
        local d=$(pid_daemon)
        echo "daemon: ${d:-FAILED}"
    fi
    if [ -n "$(pid_widget)" ]; then
        echo "widget: already running ($(pid_widget))"
    else
        build_widget || return 1
        ./ClarvisWidget/ClarvisWidget >>logs/widget.out.log 2>>logs/widget.err.log &
        sleep 0.5
        local w=$(pid_widget)
        echo "widget: ${w:-FAILED}"
    fi
}

do_status() {
    local d=$(pid_daemon) w=$(pid_widget)
    echo "daemon: ${d:-not running}"
    echo "widget: ${w:-not running}"
}

do_logs() {
    tail -f logs/daemon.out.log logs/daemon.err.log
}

case "${1:-status}" in
    start)
        [ "$2" = "--new" ] && export CLARVIS_NEW_CONVERSATION=1
        do_start
        ;;
    stop)    do_stop ;;
    restart)
        do_stop; pkill -f 'clarvis\.server' 2>/dev/null
        [ "$2" = "--new" ] && export CLARVIS_NEW_CONVERSATION=1
        do_start
        ;;
    status)  do_status ;;
    logs)    do_logs ;;
    debug)
        cd "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0")")/.."
        if [ "$2" = "--new" ]; then
            echo "Starting new voice agent session..."
            exec claude
        else
            echo "Attaching to voice agent session..."
            exec claude --continue
        fi
        ;;
    help|-h|--help)
        echo "Usage: clarvis <command>"
        echo ""
        echo "Commands:"
        echo "  start     Start daemon and widget (--new for fresh voice session)"
        echo "  stop      Stop all processes"
        echo "  restart   Stop then start (--new for fresh voice session)"
        echo "  status    Show running processes (default)"
        echo "  logs      Tail daemon logs"
        echo "  debug     Attach to voice agent's Claude session (--new for fresh)"
        ;;
    *)  echo "Unknown command: $1 (try 'clarvis help')" ;;
esac
