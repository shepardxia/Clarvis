# Central Hub

Your little window into what I'm up to. I sit in the corner of your screen showing you what I'm thinking, what I'm working on, and what the weather's like. Simple as that.

**What's inside:**
1. **MCP Server** - I keep weather, time, and status info ready for you
2. **Desktop Widget** - The little me floating on your screen with animations and feelings

## Hey there! Say hello to me.

```
IDLE            THINKING         RUNNING          AWAITING         OFFLINE
╭─────────╮     ╭~~~~~~~~~╮     ╭═════════╮     ╭⋯⋯⋯⋯⋯⋯⋯⋯⋯╮     ╭·········╮
│  ·   ·  │     │  ˘   ˘  │     │  ●   ●  │     │  ?   ?  │     │  ·   ·  │
│    ◡    │     │    ~    │     │    ◡    │     │    ·    │     │    ─    │
│         │     │         │     │         │     │         │     │         │
│ ·  ·  · │     │ • ◦ • ◦ │     │ • ● • ● │     │ · · · · │     │  · · ·  │
╰─────────╯     ╰~~~~~~~~~╯     ╰═════════╯     ╰⋯⋯⋯⋯⋯⋯⋯⋯⋯╯     ╰·········╯
 █████░░░░       ████░░░░░       ███████░░       ██░░░░░░░       ░░░░░░░░░
```

That's me in the corner. I'll be floating on your screen, reacting to everything I'm thinking about, the tools I'm running, and what I'm waiting for. Sometimes you'll see me with weather effects—snow, rain, clouds, all that good stuff.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Claude Code                             │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  MCP Tools: get_weather, get_time, list_sessions, etc   │ │
│  └──────────────────┬──────────────────────────────────────┘ │
└─────────────────────┼───────────────────────────────────────┘
                      │ stdio
                      ▼
┌─────────────────────────────────────────────────────────────┐
│         MCP Server (Python package)                          │
│         ~/Desktop/directory/central-hub/                     │
│         ├── src/central_hub/server.py (MCP tools)            │
│         ├── src/central_hub/thinking_feed.py (sessions)      │
│         ├── widget/Display.swift (rendering)                 │
│         └── widget/ClaudeStatusOverlay.swift (app)           │
│                          │                                   │
│                          │ writes JSON                       │
│                          ▼                                   │
│              /tmp/central-hub-*.json                         │
│              /tmp/claude-overlay-config.json                 │
└─────────────────────────┼───────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│ weather.json  │ │  time.json    │ │ status.json   │
└───────┬───────┘ └───────┬───────┘ └───────┬───────┘
        │                 │                 │
        │     config.json (hot-reload) ◄────┤
        │                 │                 │
        └─────────────────┼─────────────────┘
                          │ reads + watches
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Desktop Widget (Swift)                          │
│              ClaudeStatusOverlay                             │
│              (Config hot-reload via DispatchSource)          │
└─────────────────────────────────────────────────────────────┘
```

**Project Structure:**
- MCP server as Python package in `src/central_hub/`
- Widget components in `widget/`
- Single source of truth in `~/Desktop/directory/central-hub/`
- Changes take effect immediately (widget hot-reloads config)

## Quick Start (First Time)

```bash
cd ~/Desktop/directory/central-hub

# One-time setup (installs MCP server, builds widget)
./scripts/setup.sh

# Restart Claude Code to load MCP server
# (Close completely and reopen)

# Start the widget (optional)
./ClaudeStatusOverlay &
```

## Quick Start (Already Set Up)

```bash
cd ~/Desktop/directory/central-hub

# Start just the widget
cd widget
./restart.sh

# Or run the binary directly
./ClaudeStatusOverlay &
```

## Using the MCP Tools

After setup and restarting Claude Code:

```
Ask me:
  • "What's the weather?"
  • "What time is it in Tokyo?"
  • "What's my current status?"
```

Check MCP is connected: Run `/mcp` in Claude Code - `central-hub` should appear.

---

## Component 1: My MCP Server

**Location**: `~/Desktop/directory/central-hub/src/central_hub/`
**Config**: `~/.claude/.mcp.json` and `~/.claude.json` (user-scope, available globally)

### Tools I Provide

| Tool | Description | Dependencies |
|------|-------------|--------------|
| `ping()` | Test server connectivity | None |
| `get_weather(lat?, lon?)` | Current weather with auto-location | `requests` (included) |
| `get_time(timezone?)` | Current time in any timezone | None (stdlib zoneinfo) |
| `get_claude_status()` | Read my current status | None |
| `list_active_sessions()` | List all active Claude Code sessions | `watchdog` (included) |
| `get_session_thoughts(id, limit?)` | Get thinking blocks from a session | `watchdog` (included) |
| `get_latest_thought()` | Get most recent thought globally | `watchdog` (included) |

### Location Detection (Automatic)

Weather automatically detects your location using two methods (in order):

1. **CoreLocation (GPS)** - OPTIONAL
   - More accurate, GPS-based location
   - Requires: `CoreLocationCLI` (install: `brew install corelocationcli`)
   - If not installed, automatically falls back to IP geolocation

2. **IP Geolocation** - ALWAYS AVAILABLE
   - Approximate location from your IP address
   - Requires: Internet connection
   - No additional setup needed

**Enable GPS location (optional):**
```bash
# Install CoreLocationCLI
brew install corelocationcli

# Grant permission (run once, approve the dialog)
CoreLocationCLI -j

# Weather will now use GPS instead of IP geolocation
```

### Dependencies

Installed automatically by `setup.sh`:
- `mcp>=1.0.0` - MCP framework
- `requests>=2.28.0` - Weather API requests
- Python 3.10+ (checked by `setup.sh`)

### Data Sources

- **Weather**: Open-Meteo API (free, no API key required)
- **Time**: Python stdlib (zoneinfo)
- **Location**: CoreLocation CLI or ip-api.com

---

## Component 2: My Desktop Widget

**Location**: `./ClaudeStatusOverlay` (built by `setup.sh`)
**Source**: `Display.swift`, `ClaudeStatusOverlay.swift`

### Features

- **Always-on-top floating window** - Shows what I'm up to
- **Animated avatar** - Different faces for idle/thinking/running/awaiting/offline states
- **Composable sprite system** - Multi-frame ASCII art sprites
- **Weather effects** - Animated snow, rain, clouds, fog using procedural sprite generation
- **Status indicator** - Color-coded border pulse (idle/thinking/running/waiting)
- **Context bar** - Progress bar showing token usage (█/░ format)
- **Draggable** - Move window by dragging
- **Auto-hide** - Disappears after 10 min idle, reappears when active

### Avatar States

```
IDLE:           THINKING:       RUNNING:        AWAITING:       OFFLINE:
╭─────────╮     ╭~~~~~~~~~╮     ╭═════════╮     ╭⋯⋯⋯⋯⋯⋯⋯⋯⋯╮     ╭·········╮
│  ·   ·  │     │  ˘   ˘  │     │  ●   ●  │     │  ?   ?  │     │  ·   ·  │
│    ◡    │     │    ~    │     │    ◡    │     │    ·    │     │    ─    │
│         │     │         │     │         │     │         │     │         │
│ ·  ·  · │     │ • ◦ • ◦ │     │ • ● • ● │     │ · · · · │     │  · · ·  │
╰─────────╯     ╰~~~~~~~~~╯     ╰═════════╯     ╰⋯⋯⋯⋯⋯⋯⋯⋯⋯╯     ╰·········╯
 █████░░░░       ████░░░░░       ███████░░       ██░░░░░░░       ░░░░░░░░░
```

### Configuration

Widget settings are in `/tmp/claude-overlay-config.json`:
```json
{
  "gridWidth": 28,
  "gridHeight": 14,
  "fontSize": 19,
  "avatarX": 9,
  "avatarY": 4,
  "barX": 9,
  "barY": 10,
  "snowCount": 14,
  "rainCount": 24,
  "cloudyCount": 50,
  "fogCount": 70
}
```

### Control Panel

Web UI for runtime configuration:
```bash
cd ./repo
python3 control-server.py
# Opens at http://localhost:8765
```

Adjust widget settings and restart overlay from the control panel.

---

## Installation Details

### Automatic Setup (First Time)

`setup.sh` does the following:

1. ✓ Checks Python 3.10+ is available
2. ✓ Creates Python virtual environment at project root
3. ✓ Installs MCP server as package (`uv pip install -e .`)
4. ✓ Configures `~/.claude.json` to point to this directory
5. ✓ Builds Swift widget binary
6. ✓ Tests MCP server startup
7. ✓ Prints next steps

### Manual MCP Server Setup

If you prefer manual installation:

```bash
cd ~/Desktop/directory/central-hub

# Setup Python environment
uv venv

# Install as editable package
uv pip install -e .

# Configure MCP (add to ~/.claude.json)
# See "MCP Configuration" section below
```

### Widget Build

```bash
cd ~/Desktop/directory/central-hub/widget
swiftc -o ClaudeStatusOverlay Display.swift ClaudeStatusOverlay.swift -framework Cocoa
./ClaudeStatusOverlay &
```

---

## File Structure

```
central-hub/
├── .venv/                        # Virtual environment (created by setup)
├── src/central_hub/              # MCP Server (Python package)
│   ├── __init__.py
│   ├── server.py                 # MCP tool implementations
│   └── thinking_feed.py          # Session monitoring
├── widget/                       # Desktop Widget
│   ├── Display.swift             # Widget display logic
│   ├── ClaudeStatusOverlay.swift # Widget app lifecycle
│   ├── ClaudeStatusOverlay       # Compiled binary
│   └── restart.sh                # Build + restart script
├── scripts/                      # Installation and utility scripts
│   ├── setup.sh                  # One-command installation
│   └── start-control-panel.sh    # Launch control panel server
├── pyproject.toml                # Package configuration
├── control-server.py             # Web UI for widget settings
├── control-panel.html            # Web interface
└── README.md                     # This file
```

---

## Troubleshooting

**MCP server not connected:**
- Run `setup.sh` to install/configure
- Restart Claude Code completely (close + reopen)
- Check: `/mcp` in your Claude Code should list `central-hub`

**Weather not working:**
- Check: `cat /tmp/central-hub-weather.json` (should exist)
- No internet? MCP server needs internet for weather API
- Run manually: `cd ~/Desktop/directory/central-hub && uv run python -m central_hub.server --refresh`

**Widget won't build:**
- Install Xcode command line tools: `xcode-select --install`
- Verify Swift: `swiftc --version`
- Run: `./scripts/setup.sh` to rebuild

**Python version mismatch:**
- Install Python 3.10+: `brew install python3`
- Run: `./scripts/setup.sh` (auto-detects correct version)

**Config changes not applying:**
- Check: Widget console shows "🔄 Config reloaded - updating positions"
- If dimension changes (gridWidth/Height/fontSize): Restart required
- For position changes (avatarX/Y, barX/Y): Should hot-reload
- Debug: `tail -f /tmp/claude-overlay-config.json`

---

## Credits

- **Thinking Feed** - Adapted from [watch-claude-think](https://github.com/bporterfield/watch-claude-think) by [@bporterfield](https://github.com/bporterfield) (MIT License). Ported from TypeScript to Python for MCP integration.

---


