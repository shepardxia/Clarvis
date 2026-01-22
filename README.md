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
│         MCP Server (single environment development)          │
│         ~/.claude/mcp-servers/central-hub/                   │
│         ├── server.py (MCP tools)                            │
│         ├── thinking_feed.py (session monitoring)            │
│         ├── Display.swift (widget rendering)                 │
│         └── ClaudeStatusOverlay.swift (app lifecycle)        │
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

**Single Environment Development:**
- Edit directly in `~/.claude/mcp-servers/central-hub/`
- Git repo initialized by setup.sh
- No sync scripts needed
- Changes take effect immediately (widget hot-reloads config)

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
Ask me:
  • "What's the weather?"
  • "What time is it in Tokyo?"
  • "What's my current status?"
```

Check MCP is connected: Run `/mcp` in Claude Code - `central-hub` should appear.

---

## Component 1: My MCP Server

**Location**: `~/.claude/mcp-servers/central-hub/` (auto-installed by `setup.sh`)
**Source**: `./mcp-server/` directory in this repo

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
- Check: `/mcp` in your Claude Code should list `central-hub`

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

**Config changes not applying:**
- Check: Widget console shows "🔄 Config reloaded - updating positions"
- If dimension changes (gridWidth/Height/fontSize): Restart required
- For position changes (avatarX/Y, barX/Y): Should hot-reload
- Debug: `tail -f /tmp/claude-overlay-config.json`

**Git workflow after consolidation:**
- Development location: `~/.claude/mcp-servers/central-hub/`
- Commit and push from MCP server location
- Original folder (`~/Desktop/directory/central-hub`) is template only

---

## Development

**Active development location:** `~/.claude/mcp-servers/central-hub/`

This is where the live MCP server runs. Edit files here directly:
- `server.py` - MCP tools
- `thinking_feed.py` - Session monitoring
- `Display.swift` - Widget rendering
- `ClaudeStatusOverlay.swift` - App lifecycle

**Original template:** `~/Desktop/directory/central-hub/`
- Kept as reference and for git commits
- Push changes from MCP server location
- No sync script needed anymore

### Development Workflow

1. **Edit files in MCP server location:**
   ```bash
   cd ~/.claude/mcp-servers/central-hub
   # Edit server.py, Display.swift, etc.
   ```

2. **Test changes:**
   ```bash
   # For MCP server: Restart Claude Code (Command+R)
   # For widget: ./restart.sh (rebuilds + restarts)
   ```

3. **Commit from MCP server location:**
   ```bash
   cd ~/.claude/mcp-servers/central-hub
   git add .
   git commit -m "feat: description"
   git push
   ```

**Note:** The `~/.claude/mcp-servers/central-hub` directory is a git repo initialized by setup.sh, pointing to the same remote as the template folder.

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

## Credits

- **Thinking Feed** - Adapted from [watch-claude-think](https://github.com/bporterfield/watch-claude-think) by [@bporterfield](https://github.com/bporterfield) (MIT License). Ported from TypeScript to Python for MCP integration.

---

## See Also

- `mcp-server/README.md` - MCP server documentation
- `CLAUDE.md` - Project memory and context
- `docs/plans/` - Implementation plans and designs

