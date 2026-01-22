# Central Hub MCP Server

MCP server providing weather, time, status, and thinking feed monitoring.

## Installation

### Option 1: Via claude mcp add (Recommended)

```bash
claude mcp add central-hub
```

### Option 2: Manual Installation

```bash
cd /path/to/central-hub
./setup.sh
```

## Tools

- `ping()` - Test connectivity
- `get_weather(lat?, lon?)` - Current weather with auto-location
- `get_time(timezone?)` - Current time in any timezone
- `get_claude_status()` - Read Claude's current status
- `list_active_sessions()` - List all Claude Code sessions
- `get_session_thoughts(session_id, limit?)` - Get thinking blocks
- `get_latest_thought()` - Most recent thought across all sessions

## Optional: GPS Location

```bash
brew install corelocationcli
CoreLocationCLI -j  # Approve dialog
```

Weather will use GPS instead of IP geolocation.

## Development

Edit files in `~/.claude/mcp-servers/central-hub/`:
- `server.py` - MCP tools
- `thinking_feed.py` - Session monitoring

Restart Claude Code to reload changes.
