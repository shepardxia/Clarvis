# Central MCP Daemon Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a central MCP server that manages multiple data sources (starting with weather) and writes to JSON files for the widget to consume.

**Architecture:** A Python MCP server using FastMCP that exposes tools for weather data. The server writes data to `/tmp/` JSON files that the Swift widget reads. Uses stdio transport - Claude Code spawns it as needed.

**Tech Stack:** Python 3.9+, FastMCP (mcp package), requests (for weather API)

---

### Task 1: Create Project Structure

**Files:**
- Create: `/Users/shepardxia/.claude/mcp-servers/central-hub/server.py`
- Create: `/Users/shepardxia/.claude/mcp-servers/central-hub/pyproject.toml`

**Step 1: Create the directory**

```bash
mkdir -p /Users/shepardxia/.claude/mcp-servers/central-hub
```

**Step 2: Create pyproject.toml**

Create `/Users/shepardxia/.claude/mcp-servers/central-hub/pyproject.toml`:

```toml
[project]
name = "central-hub"
version = "0.1.0"
description = "Central MCP server for widget data (weather, status, etc.)"
requires-python = ">=3.9"
dependencies = [
    "mcp>=1.0.0",
    "requests>=2.28.0",
]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
```

**Step 3: Create minimal server.py**

Create `/Users/shepardxia/.claude/mcp-servers/central-hub/server.py`:

```python
#!/usr/bin/env python3
"""Central Hub MCP Server - manages widget data sources."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("central-hub")


@mcp.tool()
async def ping() -> str:
    """Test that the server is running."""
    return "pong"


if __name__ == "__main__":
    mcp.run()
```

**Step 4: Verify structure**

```bash
ls -la /Users/shepardxia/.claude/mcp-servers/central-hub/
```

Expected: `server.py` and `pyproject.toml` present

---

### Task 2: Register MCP Server with Claude

**Files:**
- Modify: `/Users/shepardxia/.claude/.mcp.json`

**Step 1: Update .mcp.json to add central-hub**

Edit `/Users/shepardxia/.claude/.mcp.json` to add the new server:

```json
{
  "mcpServers": {
    "sonos": {
      "command": "uv",
      "args": ["run", "python", "server.py"],
      "cwd": "/Users/shepardxia/.claude/mcp-servers/sonos-mcp-server"
    },
    "central-hub": {
      "command": "uv",
      "args": ["run", "python", "server.py"],
      "cwd": "/Users/shepardxia/.claude/mcp-servers/central-hub"
    }
  }
}
```

**Step 2: Restart Claude Code session**

User must restart Claude Code for MCP changes to take effect.

**Step 3: Verify server appears**

Run `/mcp` command in Claude Code.

Expected: `central-hub` server listed with `ping` tool available.

---

### Task 3: Add Weather Tool

**Files:**
- Modify: `/Users/shepardxia/.claude/mcp-servers/central-hub/server.py`

**Step 1: Add weather fetching with Open-Meteo API (no API key needed)**

Update `/Users/shepardxia/.claude/mcp-servers/central-hub/server.py`:

```python
#!/usr/bin/env python3
"""Central Hub MCP Server - manages widget data sources."""

import json
import sys
from pathlib import Path
from datetime import datetime

import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("central-hub")

# Output paths for widget consumption
WEATHER_FILE = Path("/tmp/central-hub-weather.json")

# Default location (San Francisco) - can be changed via tool
DEFAULT_LAT = 37.7749
DEFAULT_LON = -122.4194


@mcp.tool()
async def ping() -> str:
    """Test that the server is running."""
    return "pong"


@mcp.tool()
async def get_weather(latitude: float = DEFAULT_LAT, longitude: float = DEFAULT_LON) -> str:
    """
    Fetch current weather for a location and write to widget file.

    Args:
        latitude: Latitude (default: San Francisco)
        longitude: Longitude (default: San Francisco)

    Returns:
        Weather summary string
    """
    try:
        # Open-Meteo API - free, no API key required
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={latitude}&longitude={longitude}"
            f"&current=temperature_2m,weather_code,wind_speed_10m"
            f"&temperature_unit=fahrenheit"
        )

        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        current = data.get("current", {})
        temp = current.get("temperature_2m", "?")
        weather_code = current.get("weather_code", 0)
        wind = current.get("wind_speed_10m", 0)

        # Map weather codes to descriptions
        weather_desc = _weather_code_to_desc(weather_code)

        # Build widget data
        widget_data = {
            "temperature": temp,
            "description": weather_desc,
            "wind_speed": wind,
            "latitude": latitude,
            "longitude": longitude,
            "timestamp": datetime.now().isoformat(),
        }

        # Write to file for widget
        WEATHER_FILE.write_text(json.dumps(widget_data, indent=2))

        return f"{temp}°F, {weather_desc}, Wind: {wind} mph"

    except requests.RequestException as e:
        return f"Error fetching weather: {e}"


def _weather_code_to_desc(code: int) -> str:
    """Convert WMO weather code to description."""
    codes = {
        0: "Clear",
        1: "Mostly Clear",
        2: "Partly Cloudy",
        3: "Overcast",
        45: "Foggy",
        48: "Icy Fog",
        51: "Light Drizzle",
        53: "Drizzle",
        55: "Heavy Drizzle",
        61: "Light Rain",
        63: "Rain",
        65: "Heavy Rain",
        71: "Light Snow",
        73: "Snow",
        75: "Heavy Snow",
        80: "Light Showers",
        81: "Showers",
        82: "Heavy Showers",
        95: "Thunderstorm",
    }
    return codes.get(code, "Unknown")


if __name__ == "__main__":
    mcp.run()
```

**Step 2: Test the server manually**

```bash
cd /Users/shepardxia/.claude/mcp-servers/central-hub
uv run python -c "import requests; print('requests OK')"
```

Expected: "requests OK" (confirms dependency works)

**Step 3: Restart Claude Code and test tool**

Restart Claude Code, then ask Claude to use the `get_weather` tool.

Expected: Weather data returned and `/tmp/central-hub-weather.json` created.

---

### Task 4: Add Time Tool

**Files:**
- Modify: `/Users/shepardxia/.claude/mcp-servers/central-hub/server.py`

**Step 1: Add time tool**

Add to `server.py` after the weather tool:

```python
TIME_FILE = Path("/tmp/central-hub-time.json")


@mcp.tool()
async def get_time(timezone: str = "America/Los_Angeles") -> str:
    """
    Get current time and write to widget file.

    Args:
        timezone: Timezone name (default: America/Los_Angeles)

    Returns:
        Current time string
    """
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(timezone)
        now = datetime.now(tz)

        widget_data = {
            "time": now.strftime("%H:%M"),
            "date": now.strftime("%Y-%m-%d"),
            "day": now.strftime("%A"),
            "timezone": timezone,
            "timestamp": now.isoformat(),
        }

        TIME_FILE.write_text(json.dumps(widget_data, indent=2))

        return f"{now.strftime('%A, %B %d, %Y %H:%M')} ({timezone})"

    except Exception as e:
        return f"Error getting time: {e}"
```

**Step 2: Add TIME_FILE to imports section**

Update the file paths section near the top:

```python
WEATHER_FILE = Path("/tmp/central-hub-weather.json")
TIME_FILE = Path("/tmp/central-hub-time.json")
```

**Step 3: Restart Claude Code and test**

Restart Claude Code, then ask Claude to use the `get_time` tool.

Expected: Time returned and `/tmp/central-hub-time.json` created.

---

### Task 5: Add Claude Status Tool (Read Current Status)

**Files:**
- Modify: `/Users/shepardxia/.claude/mcp-servers/central-hub/server.py`

**Step 1: Add status reading tool**

Add to `server.py`:

```python
STATUS_FILE = Path("/tmp/claude-status.json")


@mcp.tool()
async def get_claude_status() -> str:
    """
    Read current Claude status from the status file.

    Returns:
        Current status information
    """
    try:
        if not STATUS_FILE.exists():
            return "No status file found"

        data = json.loads(STATUS_FILE.read_text())
        status = data.get("status", "unknown")
        text = data.get("text", "")
        color = data.get("color", "gray")

        return f"Status: {status}, Text: {text}, Color: {color}"

    except Exception as e:
        return f"Error reading status: {e}"
```

**Step 2: Update file paths section**

```python
WEATHER_FILE = Path("/tmp/central-hub-weather.json")
TIME_FILE = Path("/tmp/central-hub-time.json")
STATUS_FILE = Path("/tmp/claude-status.json")
```

**Step 3: Restart Claude Code and test**

Restart Claude Code, then ask Claude to use the `get_claude_status` tool.

Expected: Current status from `/tmp/claude-status.json` returned.

---

### Task 6: Documentation

**Files:**
- Create: `/Users/shepardxia/.claude/mcp-servers/central-hub/README.md`

**Step 1: Create README**

Create `/Users/shepardxia/.claude/mcp-servers/central-hub/README.md`:

```markdown
# Central Hub MCP Server

A central MCP server that manages multiple data sources for the Claude status widget.

## Tools

| Tool | Description | Output File |
|------|-------------|-------------|
| `ping` | Test server is running | - |
| `get_weather` | Fetch current weather | `/tmp/central-hub-weather.json` |
| `get_time` | Get current time | `/tmp/central-hub-time.json` |
| `get_claude_status` | Read Claude status | - (reads existing file) |

## Setup

Already configured in `~/.claude/.mcp.json`. Restart Claude Code to activate.

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

## Adding New Data Sources

1. Add a new tool function with `@mcp.tool()` decorator
2. Write output to `/tmp/central-hub-<source>.json`
3. Restart Claude Code
4. Update widget to read the new file
```

**Step 2: Verify all files exist**

```bash
ls -la /Users/shepardxia/.claude/mcp-servers/central-hub/
```

Expected: `server.py`, `pyproject.toml`, `README.md`

---

## Summary

After completing all tasks:

1. **MCP Server** at `~/.claude/mcp-servers/central-hub/`
2. **Tools available:**
   - `ping` - test connectivity
   - `get_weather` - fetch weather, write to `/tmp/central-hub-weather.json`
   - `get_time` - get time, write to `/tmp/central-hub-time.json`
   - `get_claude_status` - read existing status file
3. **Widget integration** - Widget can read the JSON files (future task)

## Next Steps (Future)

- Update Swift widget to read weather/time JSON files
- Add more data sources (calendar, system stats, etc.)
- Add periodic refresh (widget polls or uses file watching)
