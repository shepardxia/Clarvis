# Central Hub MCP Server

An MCP server that manages multiple data sources (weather, time, status) for the Claude status widget.

## Installation

The server is automatically set up by the main `setup.sh` script. For manual installation:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

## Tools

| Tool | Description | Output File | Dependencies |
|------|-------------|-------------|--------------|
| `ping` | Test server is running | - | None |
| `get_weather(lat, lon)` | Fetch current weather | `/tmp/central-hub-weather.json` | requests (included) |
| `get_time(timezone)` | Get current time | `/tmp/central-hub-time.json` | None (stdlib) |
| `get_claude_status` | Read Claude status | - (reads existing file) | None |

## Data Sources

### Location Detection

1. **CoreLocation** (OPTIONAL) - GPS-based, accurate location
   - Requires: `CoreLocationCLI` (install via `brew install corelocationcli`)
   - If not installed, automatically falls back to IP geolocation

2. **IP Geolocation** (ALWAYS AVAILABLE) - Approximate location from IP address
   - Requires: Internet connection
   - Uses: ip-api.com (free tier, no auth required)

### Weather

- **Provider**: Open-Meteo API (free, no API key required)
- **Data**: Temperature, weather code, wind speed
- **Update frequency**: 1 minute cache
- **Location**: Auto-detected or specified manually

### Time

- **Provider**: System zoneinfo (stdlib)
- **Data**: Current time in any timezone
- **Update frequency**: Real-time (no cache)

## Usage

### From Claude Code

Ask Claude questions like:
- "What's the weather?"
- "What time is it in Tokyo?"
- "What's my current status?"

### Manual Testing

```bash
# Start the server
python3 server.py

# In another terminal, test tools:
curl http://localhost:5000/tools/ping
curl http://localhost:5000/tools/get_weather
```

### Background Refresh

The server can be called with `--refresh` flag for background updates:

```bash
python3 server.py --refresh
```

This fetches all data and writes to `/tmp/` files without starting the MCP server.

## Output Files

All data is written to `/tmp/` for the widget to read:

### Weather (`/tmp/central-hub-weather.json`)
```json
{
  "temperature": 65,
  "description": "Partly Cloudy",
  "wind_speed": 10,
  "latitude": 37.7749,
  "longitude": -122.4194,
  "city": "San Francisco",
  "timestamp": "2026-01-22T10:30:00"
}
```

### Time (`/tmp/central-hub-time.json`)
```json
{
  "time": "10:30",
  "date": "2026-01-22",
  "day": "Wednesday",
  "timezone": "America/Los_Angeles",
  "timestamp": "2026-01-22T10:30:00-08:00"
}
```

## Adding New Data Sources

1. Add a new tool function with `@mcp.tool()` decorator
2. Write output to `/tmp/central-hub-<source>.json`
3. Restart Claude Code (hook reconnection)
4. Update widget to read the new file

## Optional: Enable GPS Location

For more accurate location-based weather:

```bash
# Install CoreLocationCLI (macOS only)
brew install corelocationcli

# Grant permission (run once, approve dialog)
CoreLocationCLI -j
```

The server will automatically use GPS if available, otherwise falls back to IP geolocation.

## Troubleshooting

**Weather not updating:**
- Check `/tmp/central-hub-weather.json` exists
- Test: `python3 server.py --refresh`
- Verify internet connection

**Location showing San Francisco:**
- IP geolocation fallback (normal if CoreLocationCLI not installed)
- Install CoreLocationCLI for GPS accuracy

**MCP server not connected:**
- Restart Claude Code
- Run `setup.sh` again to verify `.mcp.json` configuration

## Dependencies

- **Python 3.10+** (required)
- **mcp** (installed by setup)
- **requests** (installed by setup)
- **CoreLocationCLI** (optional, for GPS location)
