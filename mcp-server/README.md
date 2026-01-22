# Central Hub MCP Server

A central MCP server that manages multiple data sources for the Claude status widget.

## Setup

### Initial Installation

The server can live anywhere on your system. Navigate to this directory (or wherever you've cloned it):

```bash
# From this directory
uv venv
uv pip install -e .

# Add to Claude Code (works from any location)
claude mcp add central-hub
```

This adds the server to your `~/.claude/.mcp.json` automatically, pointing to the current directory. No copying needed—the server runs from wherever you put it.

### Manual Configuration (Alternative)

If `claude mcp add` doesn't work, manually edit `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "central-hub": {
      "command": "/absolute/path/to/central-hub/.venv/bin/python3",
      "args": ["server.py"],
      "cwd": "/absolute/path/to/central-hub"
    }
  }
}
```

Replace `/absolute/path/to/central-hub` with the full path to this directory, then restart Claude Code.

### Optional: Better Location Accuracy

By default, weather uses IP-based geolocation (no setup needed). For GPS-accurate location on macOS:

```bash
brew install corelocationcli
```

The server will automatically use CoreLocationCLI if available, otherwise falls back to IP geolocation.

## Tools

### Data Sources
| Tool | Description | Output File |
|------|-------------|-------------|
| `ping` | Test server is running | - |
| `get_weather` | Fetch current weather (auto-detects location) | `/tmp/central-hub-weather.json` |
| `get_time` | Get current time | `/tmp/central-hub-time.json` |
| `get_claude_status` | Read Claude status | - (reads `/tmp/claude-status.json`) |

### Thinking Feed (watch-claude-think integration)
| Tool | Description |
|------|-------------|
| `list_active_sessions` | List all active Claude Code sessions |
| `get_session_thoughts` | Get recent thinking blocks from a session |
| `get_latest_thought` | Get the most recent thought across all sessions |

## Usage

Ask Claude to use the tools:
- "What's the weather?"
- "What time is it?"
- "What's your current status?"

## Output Files

The server writes JSON files to `/tmp/` for the widget to read:

### Weather (`/tmp/central-hub-weather.json`)
```json
{
  "temperature": 65,
  "description": "Partly Cloudy",
  "wind_speed": 10,
  "timestamp": "2026-01-22T10:30:00"
}
```

### Time (`/tmp/central-hub-time.json`)
```json
{
  "time": "10:30",
  "date": "2026-01-22",
  "day": "Thursday",
  "timezone": "America/Los_Angeles"
}
```

## Widget Integration

The macOS status widget reads these JSON files and displays them in the menu bar:

- **Compiled Binary**: `ClaudeStatusOverlay` (Swift)
- **Control Panel**: `control-panel.html` (runtime configuration UI)
- **Config File**: `/tmp/claude-overlay-config.json`

To start the widget:
```bash
./ClaudeStatusOverlay
```

To access the control panel:
```bash
python3 -m http.server 8765 &
open http://localhost:8765/control-panel.html
```

## Adding New Data Sources

1. Add a new tool function with `@mcp.tool()` decorator in `server.py`
2. Write output to `/tmp/central-hub-<source>.json`
3. Restart Claude Code to register the new tool
4. Update `control-panel.html` to display the new data source
5. (Optional) Update widget Swift code to display in menu bar
