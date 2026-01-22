# Central Hub

A complete personal information hub with integrated MCP server and desktop widget for Claude Code.

**Location:** `/Users/shepardxia/Desktop/directory/central-hub/`

## What This Is

This project has two main components:

1. **MCP Server** - Provides tools to Claude Code for weather, time, and status reading
2. **Desktop Widget** - A floating overlay showing Claude's status with animated ASCII avatar and weather effects

## Quick Start

**First time setup:**
```bash
cd ~/Desktop/directory/central-hub
./setup.sh
# Then restart Claude Code
# (Optional) ./ClaudeStatusOverlay &
```

The `setup.sh` script handles everything:
- Python 3.10+ detection
- MCP server installation
- Dependency management (uv/pip)
- Automatic `.mcp.json` configuration
- Swift widget compilation
- Verification and testing

**Optional: Enable GPS Location**
```bash
brew install corelocationcli
CoreLocationCLI -j  # Approve the dialog
# Weather now uses GPS instead of IP geolocation
```

See README.md for detailed documentation.

## Architecture

**Project Location:** `~/Desktop/directory/central-hub/`

All components live in this directory:
- MCP server files: `mcp-server/` (server.py, thinking_feed.py)
- Widget files: `Display.swift`, `ClaudeStatusOverlay.swift`, compiled binary
- Control panel: `control-panel.html`, `control-server.py`
- Git repo with remote configured

**No copying needed** - `claude mcp add` references files in place:
- MCP changes: Restart Claude Code
- Widget changes: `./restart.sh` or use control panel
- Config changes: Hot-reload via DispatchSource watcher

**Process efficiency:**
- Direct MCP server execution (no wrapper overhead)
- Config hot-reload (no restart for position changes)
- Widget auto-hides after 10min idle

**Installation:**
```bash
# From this directory
cd ~/Desktop/directory/central-hub/mcp-server
uv venv
uv pip install -e .
claude mcp add central-hub

# Or use setup script from parent directory
cd ~/Desktop/directory/central-hub
./setup.sh
```

## MCP Server Component

**Location:** `mcp-server/` subdirectory
**Source:** `mcp-server/server.py`

### Tools

| Tool | Description | Output File |
|------|-------------|-------------|
| `ping()` | Test server connectivity | - |
| `get_weather(lat?, lon?)` | Current weather with auto-location | `/tmp/central-hub-weather.json` |
| `get_time(timezone?)` | Current time in any timezone | `/tmp/central-hub-time.json` |
| `get_claude_status()` | Read Claude's current status | - |

### Location Detection

**Primary (if available):** CoreLocationCLI
- GPS-based, accurate location
- Optional: `brew install corelocationcli`
- One-time permission: `CoreLocationCLI -j`

**Fallback (always available):** IP Geolocation
- Uses ip-api.com (free, no auth)
- Automatic if CoreLocationCLI not installed

System gracefully falls back to IP geolocation if GPS unavailable.

### Data Sources

- **Weather:** Open-Meteo API (free, no API key)
- **Time:** Python stdlib zoneinfo
- **Location:** CoreLocation or ip-api.com

## Desktop Widget (Status Overlay)

Shows Claude's current status (idle/thinking/running/waiting) with animated ASCII avatar.

### Status Flow

Via Claude Code hooks:

| Hook Event | Status | Color | Text |
|------------|--------|-------|------|
| UserPromptSubmit | thinking | yellow | "Thinking..." |
| PreToolUse | running | green | [tool name] |
| PostToolUse | thinking | yellow | "Thinking..." |
| Stop | idle | gray | "Idle" |
| Notification[*] | awaiting | blue | "Waiting for..." |

**Note:** Awaiting status auto-transitions to idle after 5 minutes of inactivity.

### Avatar Design

Composable system with separate components (eyes, mouth, border, substrate):

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

**Font width fix:** Some Unicode chars render narrower than monospace width in AppKit. Replaced with correctly-sized alternatives (˘, ·, •, ◦, ●).

### Widget Features

- **Instant status updates** via Claude Code hooks
- Auto-hide after 10 min idle
- Reappear at default position when active
- Draggable window
- Single instance lock
- Border pulse animation (fast for running, gentle for thinking)
- Substrate animation (4-frame smooth oscillation)
- Context bar (progress indicator)
- Weather effects (snow, rain, clouds, fog)

## Key Files

**MCP Server:**
- `mcp-server/server.py` - Tool implementations
- `mcp-server/pyproject.toml` - Dependencies
- `mcp-server/README.md` - MCP documentation

**Setup & Installation:**
- `setup.sh` - One-command installation (copies server, builds widget, configures MCP)
- `README.md` - Comprehensive documentation
- `CLAUDE.md` - This file (project context)

**Widget:**
- `Display.swift` - Display logic: status model, avatar components, rendering
- `ClaudeStatusOverlay.swift` - App lifecycle: window management, file watcher
- `ClaudeStatusOverlay` - Compiled binary (auto-updates on rebuild)
- `restart.sh` - Build and restart script

**Hook Integration:**
- `~/.claude/hooks/status-hook.sh` - Maps hook events to status JSON
- `~/.claude/settings.json` - Hook configuration

**Documentation:**
- `docs/plans/` - Design and implementation plans

## Build & Run

**Manual rebuild:**
```bash
cd ~/Desktop/directory/central-hub
swiftc -o ClaudeStatusOverlay Display.swift ClaudeStatusOverlay.swift -framework Cocoa
./ClaudeStatusOverlay &
```

**Or use restart script:**
```bash
./restart.sh
```

## Hook Configuration

Configured in `~/.claude/settings.json` by setup.sh (auto-generated):

```json
{
  "hooks": {
    "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "/Users/shepardxia/.claude/hooks/status-hook.sh"}]}],
    "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "/Users/shepardxia/.claude/hooks/status-hook.sh"}]}],
    "UserPromptSubmit": [{"matcher": "*", "hooks": [{"type": "command", "command": "/Users/shepardxia/.claude/hooks/status-hook.sh"}]}],
    "Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "/Users/shepardxia/.claude/hooks/status-hook.sh"}]}],
    "Notification": [
      {"matcher": "permission_prompt", "hooks": [{"type": "command", "command": "/Users/shepardxia/.claude/hooks/status-hook.sh"}]},
      {"matcher": "idle_prompt", "hooks": [{"type": "command", "command": "/Users/shepardxia/.claude/hooks/status-hook.sh"}]}
    ]
  }
}
```

**Note:** Hooks require Claude Code session restart to take effect.

## Testing

**Test hook script manually:**
```bash
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash"}' | ~/.claude/hooks/status-hook.sh
cat /tmp/claude-status.json
# Expected: {"status":"running","tool":"Bash","color":"green","text":"Bash","timestamp":...}
```

**Test MCP server:**
```bash
~/.claude/mcp-servers/central-hub/venv/bin/python3 ~/.claude/mcp-servers/central-hub/server.py --refresh
cat /tmp/central-hub-weather.json
```

## Code Quality Enhancements

**Display.swift improvements:**
- SpriteSpawner precondition validation (sprite variants, spawn rate, ranges)
- Safe force unwrap removal (nil coalescing operator)
- CharacterGrid bounds checking
- Sprite dimension validation
- Enhanced render() method documentation

**Composable Sprite System:**
- Multi-frame ASCII animation
- Procedural weather generation
- Anchor-based positioning
- Layer composition with MINUS operator

## Completed Features

- **File watching** - DispatchSource for instant updates
- **Awaiting avatar** - `?` eyes with blue ellipsis border for notifications
- **Context bar** - High-contrast █/░ progress bar below avatar
- **5-min timeout** - Awaiting auto-transitions to idle
- **Weather effects** - Snow, rain, clouds, fog with procedural generation
- **Optional CoreLocation** - GPS location with IP geolocation fallback
- **One-command setup** - setup.sh automates entire installation
- **Dependency management** - uv/pip fallback for speed
- **Auto-configuration** - setup.sh configures .mcp.json automatically

## Pending Enhancements

1. **LaunchAgent** - Auto-start widget on login (`~/Library/LaunchAgents/com.claude.status-overlay.plist`)
