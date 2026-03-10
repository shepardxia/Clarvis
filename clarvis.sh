#!/bin/bash
# Clarvis process manager.
# Usage: ./clarvis.sh [start|stop|restart|logs|chat|help]

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

do_logs() {
    tail -f logs/daemon.log
}

case "${1:-help}" in
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
    logs)    do_logs ;;
    chat)
        shift
        _chat_new=false
        _chat_agent=""
        while [ $# -gt 0 ]; do
            case "$1" in
                -c|--channel)
                    case "$2" in
                        discord|factoria) _chat_agent="factoria" ;;
                        *) _chat_agent="$2" ;;
                    esac
                    shift 2 ;;
                --new) _chat_new=true; shift ;;
                *) echo "Unknown chat option: $1"; exit 1 ;;
            esac
        done
        if $_chat_new; then
            echo '{"method":"reset_clarvis_session","params":{}}' | nc -U /tmp/clarvis-daemon.sock 2>/dev/null || true
        fi
        if [ -n "$_chat_agent" ]; then
            exec node chat-tui/dist/main.js --agent "$_chat_agent"
        else
            exec node chat-tui/dist/main.js
        fi
        ;;
    add)
        case "$2" in
            org)
                shift 2
                [ -z "$1" ] && echo "Usage: clarvis add org <name>" && exit 1
                .venv/bin/python -c "
import sys
from clarvis.channels.registry import UserRegistry
name = ' '.join(sys.argv[1:])
r = UserRegistry()
if r.add_org(name):
    print(f'Added org: {name}')
else:
    print(f'Org already exists: {name}')
" "$@"
                ;;
            *)  echo "Unknown add target: $2 (try: org)" ;;
        esac
        ;;
    remove)
        case "$2" in
            org)
                shift 2
                [ -z "$1" ] && echo "Usage: clarvis remove org <name>" && exit 1
                .venv/bin/python -c "
import sys
from clarvis.channels.registry import UserRegistry
name = ' '.join(sys.argv[1:])
r = UserRegistry()
if r.remove_org(name):
    print(f'Removed org: {name}')
else:
    print(f'Org not found: {name}')
" "$@"
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
    reflect)
        # Nudge Clarvis agent to run /reflect (consolidate memories)
        result=$(echo '{"method":"nudge","params":{"reason":"reflect"}}' | nc -U /tmp/clarvis-daemon.sock 2>/dev/null)
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
        print('Reflect nudge sent.')
except Exception as e:
    print(f'Error: {e}')
"
        fi
        ;;
    checkin)
        # Interactive memory check-in session
        # Step 1: Tell daemon to seed goals + prepare checkin
        result=$(echo '{"method":"checkin","params":{}}' | nc -U /tmp/clarvis-daemon.sock 2>/dev/null)
        if [ -z "$result" ]; then
            echo "Error: daemon not running (start with 'clarvis start')"
            exit 1
        fi
        echo "$result" | .venv/bin/python -c "
import sys, json
try:
    raw = json.load(sys.stdin)
    r = raw.get('result', raw)
    if 'error' in r:
        print(f'Error: {r[\"error\"]}')
        sys.exit(1)
    seeded = r.get('goals_seeded', 0)
    staged = r.get('staged_count', 0)
    if seeded:
        print(f'Seeded {seeded} goal(s).')
    if staged:
        print(f'{staged} staged change(s) pending review.')
    else:
        print('No staged changes pending.')
    warn = r.get('memory_warning')
    if warn:
        print(f'Warning: {warn}')
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)
" || exit 1
        # Step 2: Launch interactive Claude session at ~/.clarvis/clarvis/
        # Uses the checkin skill — Claude reads skills/ from the project dir
        _checkin_dir="$HOME/.clarvis/clarvis"
        if [ ! -d "$_checkin_dir" ]; then
            echo "Error: home directory not found: $_checkin_dir"
            echo "Has the daemon started at least once?"
            exit 1
        fi
        echo ""
        echo "Starting check-in session..."
        echo "Tip: Ask Clarvis to run the checkin skill, or say 'let's do a check-in'"
        echo ""
        cd "$_checkin_dir" || exit 1
        exec pi --model "$(python3 -c "
import json
try:
    c = json.load(open('$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0")")/config.json'))
    print(c.get('clarvis', {}).get('model', '') or 'claude-sonnet-4-6')
except Exception:
    print('claude-sonnet-4-6')
" 2>/dev/null)" --prompt "Let's do a memory check-in. Start by reviewing any staged changes, then review active goals."
        ;;
    stage)
        shift
        _stage_cognee=false
        if [ "$1" = "--cognee" ]; then
            _stage_cognee=true
            shift
        fi
        if $_stage_cognee; then
            dest="$HOME/.clarvis/documents"
        else
            dest="$HOME/.clarvis/staging/inbox"
        fi
        mkdir -p "$dest"
        if [ -z "$1" ]; then
            echo "Usage: clarvis stage [--cognee] <file> [file...]"
            echo "       clarvis stage <text>"
            echo ""
            echo "Queue content for Clarvis's next reflect cycle."
            echo "  --cognee  Route files to DocumentWatcher for knowledge graph ingestion"
            inbox="$HOME/.clarvis/staging/inbox"
            docs="$HOME/.clarvis/documents"
            ic=$(find "$inbox" -type f 2>/dev/null | wc -l | tr -d ' ')
            dc=$(find "$docs" -type f 2>/dev/null | wc -l | tr -d ' ')
            echo ""
            echo "Inbox: $ic item(s) pending | Documents: $dc file(s)"
        elif [ -f "$1" ]; then
            for f in "$@"; do
                [ ! -f "$f" ] && echo "Not a file: $f" && continue
                cp "$f" "$dest/$(date +%s)_$(basename "$f")"
                echo "staged: $(basename "$f") -> $(basename "$dest")"
            done
        else
            if $_stage_cognee; then
                echo "Error: --cognee requires files, not text"
                exit 1
            fi
            epoch=$(date +%s)
            printf '%s\n' "$*" > "$dest/$epoch.md"
            echo "staged ($epoch)"
        fi
        ;;
    new)
        rm -f "$HOME/.clarvis/clarvis/session_id"
        # Tell daemon to reset Clarvis agent session
        _reset_result=$(echo '{"method":"reset_clarvis_session","params":{}}' | nc -U /tmp/clarvis-daemon.sock 2>/dev/null)
        if echo "$_reset_result" | grep -q '"result"'; then
            echo "Session reset — next voice/chat starts fresh"
        else
            echo "Warning: daemon did not confirm reset (is clarvis running?)"
            echo "Local session_id cleared — restart daemon to take effect"
        fi
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
        echo "  start     Start daemon and widget (--new for fresh session)"
        echo "  stop      Stop all processes"
        echo "  restart   Stop then start (--new for fresh session)"
        echo "  logs      Tail daemon logs"
        echo "  chat      Chat with Clarvis in terminal (--new for fresh session)"
        echo "            -c, --channel <name>  Use a channel (e.g. discord) instead of home"
        echo "  add org   Add an org (e.g. clarvis add org CS Lab)"
        echo "  remove org Remove an org"
        echo "  list org  List all orgs"
        echo "  stage     Queue text or files for next reflect (--cognee for knowledge graph)"
        echo "  reflect   Consolidate memories (ingest active sessions into memory)"
        echo "  checkin   Interactive memory check-in (review staged changes + goals)"
        echo "  new       Reset session — next voice/chat starts a fresh conversation"
        echo "  reload    Reload agent prompts (CLAUDE.md, skills, extensions)"
        ;;
    *)  echo "Unknown command: $1 (try 'clarvis help')" ;;
esac
