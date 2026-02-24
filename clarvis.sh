#!/bin/bash
# Clarvis process manager.
# Usage: ./clarvis.sh [start|stop|restart|status|logs]

cd "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0")")"

pid_daemon() { pgrep -f 'clarvis\.daemon' | head -1; }
pid_widget() { pgrep -f 'ClarvisWidget' | head -1; }

do_stop() {
    pkill -f 'clarvis\.daemon' 2>/dev/null
    pkill -f 'ClarvisWidget' 2>/dev/null
    sleep 3
    # Force-kill stragglers
    pkill -9 -f 'clarvis\.daemon' 2>/dev/null
    pkill -9 -f 'ClarvisWidget' 2>/dev/null
    # Kill orphaned bundled CLI processes (safety net for unclean shutdown)
    pkill -9 -f '_bundled/claude' 2>/dev/null
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
    uv sync --extra all --extra channels --quiet 2>/dev/null || true
    if [ -n "$(pid_daemon)" ]; then
        echo "daemon: already running ($(pid_daemon))"
    else
        .venv/bin/python -m clarvis.daemon 2>>logs/daemon.log &
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
    tail -f logs/daemon.log
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
    chat)
        shift
        _chat_channel=""
        _chat_new=false
        while [ $# -gt 0 ]; do
            case "$1" in
                -c|--channel) _chat_channel="$2"; shift 2 ;;
                --new) _chat_new=true; shift ;;
                *) echo "Unknown chat option: $1"; exit 1 ;;
            esac
        done
        if [ -n "$_chat_channel" ]; then
            _chat_dir="$HOME/.clarvis/channels/$_chat_channel"
        else
            _chat_dir="$HOME/.clarvis/home"
        fi
        if [ ! -d "$_chat_dir" ]; then
            echo "Channel directory not found: $_chat_dir"
            echo "Is the '$_chat_channel' channel configured and has the daemon started?"
            exit 1
        fi
        # Detect backend from config.json
        _backend=$(python3 -c "
import json
try:
    c = json.load(open('config.json'))
    print(c.get('channels', {}).get('agent_backend', 'claude-code'))
except Exception:
    print('claude-code')
" 2>/dev/null)
        if [ "$_backend" = "pi" ]; then
            _session_file="$_chat_dir/pi-session.jsonl"
            _model=$(python3 -c "
import json
try:
    c = json.load(open('config.json'))
    print(c.get('channels', {}).get('model', '') or 'claude-sonnet-4-5')
except Exception:
    print('claude-sonnet-4-5')
" 2>/dev/null)
            if $_chat_new; then
                rm -f "$_session_file"
            fi
            cd "$_chat_dir" || exit 1
            exec pi --model "$_model" --session "$_session_file"
        else
            cd "$_chat_dir" || exit 1
            if $_chat_new; then
                exec claude
            else
                sid_file="$_chat_dir/session_id"
                if [ -f "$sid_file" ]; then
                    exec claude --resume "$(cat "$sid_file")"
                else
                    exec claude --continue
                fi
            fi
        fi
        ;;
    add)
        case "$2" in
            org)
                shift 2
                [ -z "$1" ] && echo "Usage: clarvis add org <name>" && exit 1
                name="$*"
                .venv/bin/python -c "
from clarvis.channels.registry import UserRegistry
r = UserRegistry()
if r.add_org('$name'):
    print(f'Added org: $name')
else:
    print(f'Org already exists: $name')
"
                ;;
            *)  echo "Unknown add target: $2 (try: org)" ;;
        esac
        ;;
    remove)
        case "$2" in
            org)
                shift 2
                [ -z "$1" ] && echo "Usage: clarvis remove org <name>" && exit 1
                name="$*"
                .venv/bin/python -c "
from clarvis.channels.registry import UserRegistry
r = UserRegistry()
if r.remove_org('$name'):
    print(f'Removed org: $name')
else:
    print(f'Org not found: $name')
"
                ;;
            *)  echo "Unknown remove target: $2 (try: org)" ;;
        esac
        ;;
    list)
        case "$2" in
            org|orgs)
                .venv/bin/python -c "
from clarvis.channels.registry import UserRegistry
r = UserRegistry()
orgs = r.orgs
if orgs:
    for o in orgs:
        print(f'  - {o}')
else:
    print('No orgs defined.')
"
                ;;
            *)  echo "Unknown list target: $2 (try: org)" ;;
        esac
        ;;
    rem)
        # Trigger memory ingestion (like REM sleep — consolidates memories)
        result=$(echo '{"method":"memory_ingest","params":{}}' | nc -U /tmp/clarvis-daemon.sock 2>/dev/null)
        if [ -z "$result" ]; then
            echo "Error: daemon not running (start with 'clarvis start')"
        else
            echo "$result" | .venv/bin/python -c "
import sys, json
try:
    r = json.load(sys.stdin)
    if 'error' in r:
        print(f'Error: {r[\"error\"]}')
    else:
        n = r.get('ingested', 0)
        print(f'Ingested {n} session(s) into memory.')
except Exception as e:
    print(f'Error: {e}')
"
        fi
        ;;
    new)
        rm -f "$HOME/.clarvis/home/session_id"
        rm -f "$HOME/.clarvis/home/pi-session.jsonl"
        # Tell daemon to disconnect voice agent (best-effort)
        echo '{"method":"reset_voice_session","params":{}}' | nc -U /tmp/clarvis-daemon.sock 2>/dev/null || true
        echo "Session reset — next voice/chat starts fresh"
        ;;
    reload)
        # Reload agent prompts (CLAUDE.md, AGENTS.md, skills, extensions)
        result=$(echo '{"method":"reload_agents","params":{}}' | nc -U /tmp/clarvis-daemon.sock 2>/dev/null)
        if [ -z "$result" ]; then
            echo "Error: daemon not running (start with 'clarvis start')"
        else
            echo "$result" | .venv/bin/python -c "
import sys, json
try:
    raw = json.load(sys.stdin)
    r = raw.get('result', raw)
    if 'error' in r:
        print(f'Error: {r[\"error\"]}')
    else:
        for line in r.get('reloaded', []):
            print(f'  {line}')
        for err in r.get('errors', []):
            print(f'  ERROR: {err}')
except Exception as e:
    print(f'Error: {e}')
"
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
        echo "  chat      Chat with Clarvis in terminal (--new for fresh session)"
        echo "            -c, --channel <name>  Use a channel (e.g. discord) instead of home"
        echo "  add org   Add an org (e.g. clarvis add org CS Lab)"
        echo "  remove org Remove an org"
        echo "  list org  List all orgs"
        echo "  rem       Consolidate memories (ingest active sessions into memory)"
        echo "  new       Reset session — next voice/chat starts a fresh conversation"
        echo "  reload    Reload agent prompts (CLAUDE.md, skills, extensions)"
        ;;
    *)  echo "Unknown command: $1 (try 'clarvis help')" ;;
esac
