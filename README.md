# Central Hub

A complete personal information hub with integrated MCP server and desktop widget.

**Components:**
1. **MCP Server** - Exposes tools to Claude Code (weather, time, status)
2. **Desktop Widget** - Floating overlay showing Claude's status with animated avatar and weather effects

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Claude Code                             │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  MCP Tools: get_weather, get_time, get_claude_status    │ │
│  └──────────────────────┬──────────────────────────────────┘ │
└─────────────────────────┼───────────────────────────────────┘
                          │ stdio
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              MCP Server (central-hub)                        │
│              ~/.claude/mcp-servers/central-hub/              │
│  (Managed by setup.sh - auto-installed from repo)           │
│                          │                                   │
│                          │ writes JSON                       │
│                          ▼                                   │
│              /tmp/central-hub-*.json                         │
└─────────────────────────┼───────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│ weather.json  │ │  time.json    │ │ status.json   │
└───────┬───────┘ └───────┬───────┘ └───────┬───────┘
        │                 │                 │
        └─────────────────┼─────────────────┘
                          │ reads
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Desktop Widget (Swift)                          │
│              ./ClaudeStatusOverlay                           │
│              (Composable sprite system w/ weather effects)   │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start (First Time)

```bash
cd ~/Desktop/directory/central-hub

# One-time setup (installs MCP server, builds widget)
./setup.sh

# Restart Claude Code to load MCP server
# (Close completely and reopen)

# Start the widget (optional)
./ClaudeStatusOverlay &
```

## Quick Start (Already Set Up)

```bash
# Start just the widget
cd ~/Desktop/directory/central-hub
./ClaudeStatusOverlay &

# Or use the convenience script
./restart.sh
```

## Using the MCP Tools

After setup and restarting Claude Code:

```
Ask Claude:
  • "What's the weather?"
  • "What time is it in Tokyo?"
  • "What's my current status?"
```

Check MCP is connected: Run `/mcp` in Claude Code - `central-hub` should appear.

---

## Component 1: MCP Server

**Location**: `~/.claude/mcp-servers/central-hub/` (auto-installed by `setup.sh`)
**Source**: `./mcp-server/` directory in this repo

### Tools

| Tool | Description | Dependencies |
|------|-------------|--------------|
| `ping()` | Test server connectivity | None |
| `get_weather(lat?, lon?)` | Current weather with auto-location | `requests` (included) |
| `get_time(timezone?)` | Current time in any timezone | None (stdlib zoneinfo) |
| `get_claude_status()` | Read Claude's current status | None |

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

## Component 2: Desktop Widget

**Location**: `./ClaudeStatusOverlay` (built by `setup.sh`)
**Source**: `Display.swift`, `ClaudeStatusOverlay.swift`

### Features

- **Always-on-top floating window** - Shows Claude's current status
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
2. ✓ Copies MCP server to `~/.claude/mcp-servers/central-hub/`
3. ✓ Creates Python virtual environment
4. ✓ Installs dependencies (tries `uv` for speed, falls back to `pip`)
5. ✓ Configures `.mcp.json` for Claude Code
6. ✓ Builds Swift widget binary
7. ✓ Tests MCP server startup
8. ✓ Prints next steps

### Manual MCP Server Setup

If you prefer manual installation:

```bash
# Create directory
mkdir -p ~/.claude/mcp-servers/central-hub

# Copy files
cp mcp-server/* ~/.claude/mcp-servers/central-hub/

# Setup Python environment
python3.11 -m venv ~/.claude/mcp-servers/central-hub/venv
source ~/.claude/mcp-servers/central-hub/venv/bin/activate
pip install -e ~/.claude/mcp-servers/central-hub/

# Configure MCP JSON manually (see mcp-server/README.md)
```

### Widget Build

```bash
cd ./repo
swiftc -o ClaudeStatusOverlay Display.swift ClaudeStatusOverlay.swift -framework Cocoa
./ClaudeStatusOverlay &
```

---

## File Structure

```
central-hub/
├── setup.sh                      # One-command installation
├── restart.sh                    # Start widget + rebuild
├── control-server.py             # Web UI for widget settings
├── control-panel.html            # Web interface
├── Display.swift                 # Widget display logic + sprite system
├── ClaudeStatusOverlay.swift     # Widget app lifecycle
├── ClaudeStatusOverlay           # Compiled widget binary
├── README.md                     # This file
├── CLAUDE.md                     # Project context
├── mcp-server/                   # MCP Server (version-controlled)
│   ├── server.py                 # MCP tool implementations
│   ├── pyproject.toml            # Python dependencies
│   └── README.md                 # MCP server documentation
└── docs/
    └── plans/
        ├── 2026-01-22-composable-sprite-system.md  # Implementation plan
        └── ...
```

**Note**: MCP server is version-controlled in `mcp-server/`. It's installed to `~/.claude/mcp-servers/central-hub/` by `setup.sh` to keep user home directories clean.

---

## Troubleshooting

**MCP server not connected:**
- Run `setup.sh` to install/configure
- Restart Claude Code completely (close + reopen)
- Check: `/mcp` in Claude should list `central-hub`

**Weather not working:**
- Check: `cat /tmp/central-hub-weather.json` (should exist)
- No internet? MCP server needs internet for weather API
- Run manually: `~/.claude/mcp-servers/central-hub/venv/bin/python3 ~/.claude/mcp-servers/central-hub/server.py --refresh`

**Widget won't build:**
- Install Xcode command line tools: `xcode-select --install`
- Verify Swift: `swiftc --version`
- Run: `./setup.sh` to rebuild

**Python version mismatch:**
- Install Python 3.10+: `brew install python3`
- Run: `./setup.sh` (auto-detects correct version)

---

## Development

### Sprite System

New composable ASCII sprite system supports:
- Multi-frame animation
- Procedural generation with variation
- Anchor-based positioning
- Layer composition with MINUS operator (prevents sprites showing through avatar)

See `docs/plans/2026-01-22-composable-sprite-system.md` for details.

### MCP Server Extension

Add new data sources:
1. Add tool function to `mcp-server/server.py` with `@mcp.tool()` decorator
2. Write output to `/tmp/central-hub-<source>.json`
3. Run `setup.sh` again or restart Claude Code
4. Update widget to read new file

---

## See Also

- `mcp-server/README.md` - MCP server documentation
- `CLAUDE.md` - Project memory and context
- `docs/plans/` - Implementation plans and designs

