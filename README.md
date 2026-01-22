# Central Hub

A personal information hub with two components:
1. **MCP Server** - Exposes tools to Claude Code (weather, time, status)
2. **Desktop Widget** - Floating overlay showing Claude's status

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
│              ~/Desktop/directory/central-hub/                │
│              ClaudeStatusOverlay                             │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### Start the widget
```bash
cd ~/Desktop/directory/central-hub
./restart.sh
```

### Verify MCP server
Run `/mcp` in Claude Code - `central-hub` should be listed.

### Test MCP tools
Ask Claude: "What's the weather?" or "What time is it?"

---

## Component 1: MCP Server

**Location:** `~/.claude/mcp-servers/central-hub/`

### Tools

| Tool | Description | Output File |
|------|-------------|-------------|
| `ping` | Test connectivity | - |
| `get_weather(lat, lon)` | Fetch weather (Open-Meteo API, free) | `/tmp/central-hub-weather.json` |
| `get_time(timezone)` | Get current time | `/tmp/central-hub-time.json` |
| `get_claude_status` | Read Claude's current status | - |

### Location Detection

Location is detected automatically using two methods (in order of preference):

1. **CoreLocation** via [CoreLocationCLI](https://github.com/fulldecent/corelocationcli) - GPS-based location
2. **IP Geolocation** (ip-api.com) - Fallback, approximate location

**Setup CoreLocation:**
```bash
# Install (one time)
brew install corelocationcli

# Grant permission (run once, approve the dialog)
CoreLocationCLI -j
```

### Background Refresh Daemon

Data is refreshed automatically every 60 seconds via LaunchAgent:

```
~/Library/LaunchAgents/com.central-hub.refresh.plist
```

**Manual control:**
```bash
# Stop daemon
launchctl unload ~/Library/LaunchAgents/com.central-hub.refresh.plist

# Start daemon
launchctl load ~/Library/LaunchAgents/com.central-hub.refresh.plist

# Check logs
tail -f /tmp/central-hub-refresh.log
```

### Configuration

Located in `~/.claude.json`:

```json
{
  "mcpServers": {
    "central-hub": {
      "type": "stdio",
      "command": "uv",
      "args": ["--directory", "/Users/shepardxia/.claude/mcp-servers/central-hub", "run", "python", "server.py"],
      "env": {}
    }
  }
}
```

### JSON Output

**Weather** (`/tmp/central-hub-weather.json`):
```json
{
  "temperature": 49.7,
  "description": "Overcast",
  "wind_speed": 9.7,
  "latitude": 37.7749,
  "longitude": -122.4194,
  "timestamp": "2026-01-22T00:09:47"
}
```

**Time** (`/tmp/central-hub-time.json`):
```json
{
  "time": "21:09",
  "date": "2026-01-21",
  "day": "Wednesday",
  "timezone": "America/Los_Angeles",
  "timestamp": "2026-01-21T21:09:47-08:00"
}
```

### Add New Tools

Edit `~/.claude/mcp-servers/central-hub/server.py`:

```python
@mcp.tool()
async def get_new_data() -> str:
    """Fetch new data and write to widget file."""
    data = {"key": "value"}
    Path("/tmp/central-hub-newdata.json").write_text(json.dumps(data))
    return "summary"
```

Then restart Claude Code.

---

## Component 2: Desktop Widget

**Location:** `~/Desktop/directory/central-hub/`

### Files

```
central-hub/
├── README.md                      # This file
├── CLAUDE.md                      # Technical reference
├── Display.swift                  # Avatar, status model, context bar, view rendering
├── ClaudeStatusOverlay.swift      # App lifecycle, window management, file watcher
├── ClaudeStatusOverlay            # Compiled binary
├── restart.sh                     # Build and restart script
└── docs/plans/                    # Design documentation
```

### Status States

| State | Trigger | Color | Avatar |
|-------|---------|-------|--------|
| **thinking** | User submits prompt | Yellow | Eyes closed |
| **running** | Tool starts | Green | Eyes open |
| **awaiting** | Stop event | Blue | Question marks |
| **resting** | 5 min after awaiting | Gray | Neutral |
| **idle** | 10 min after resting | Gray | Hidden |

### Avatar Design

```
IDLE:           THINKING:       WORKING:        AWAITING:
╭─────────╮     ╭~~~~~~~~~╮     ╭═════════╮     ╭⋯⋯⋯⋯⋯⋯⋯⋯⋯╮
│  ·   ·  │     │  ˘   ˘  │     │  ●   ●  │     │  ?   ?  │
│    ◡    │     │    ~    │     │    ◡    │     │    ·    │
│         │     │         │     │         │     │         │
│ ·  ·  · │     │ • ◦ • ◦ │     │ • ● • ● │     │ · · · · │
╰─────────╯     ╰~~~~~~~~~╯     ╰═════════╯     ╰⋯⋯⋯⋯⋯⋯⋯⋯⋯╯
 █████░░░░       ████░░░░░       ███████░░       ██░░░░░░░
```

### Modify Widget

**Timeout logic** (in `ClaudeStatusOverlay.swift`):
```swift
let restingTimeout: TimeInterval = 5 * 60   // 5 min: awaiting → resting
let idleTimeout: TimeInterval = 10 * 60     // 10 min: resting → idle
```

After changes: `./restart.sh`

---

## File Locations Summary

| Component | Location |
|-----------|----------|
| MCP Server | `~/.claude/mcp-servers/central-hub/` |
| MCP Config | `~/.claude.json` → `mcpServers` section |
| Widget | `~/Desktop/directory/central-hub/` |
| Hook Script | `~/.claude/hooks/status-hook.sh` |
| LaunchAgent | `~/Library/LaunchAgents/com.central-hub.refresh.plist` |
| Weather JSON | `/tmp/central-hub-weather.json` |
| Time JSON | `/tmp/central-hub-time.json` |
| Location JSON | `/tmp/central-hub-location.json` |
| Status JSON | `/tmp/claude-status.json` |

---

## Troubleshooting

### MCP server not in /mcp
1. Check `~/.claude.json` has `central-hub` in `mcpServers`
2. Restart Claude Code
3. Run `/mcp`

### Widget not showing
```bash
pgrep -f ClaudeStatusOverlay  # Check if running
rm -f /tmp/claude-status-overlay.lock
./restart.sh
```

### Weather tool fails
```bash
# Test API directly
curl "https://api.open-meteo.com/v1/forecast?latitude=37.7749&longitude=-122.4194&current=temperature_2m"
```

### Location detection not working
```bash
# Test CoreLocationCLI directly
CoreLocationCLI -j

# If it hangs or fails, check System Settings > Privacy & Security > Location Services
# Make sure CoreLocationCLI.app is listed and enabled

# Check cached location
cat /tmp/central-hub-location.json
# "source" should be "corelocation", not "ip"
```

---

## Future Enhancements

- [ ] Display weather/time in widget
- [x] LaunchAgent for background refresh
- [x] Location detection (CoreLocation + IP fallback)
- [ ] Calendar integration
- [ ] System stats (CPU, memory)
- [ ] Notifications
