#!/usr/bin/env python3
"""Central Hub MCP Server - manages widget data sources."""

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

import requests
from mcp.server.fastmcp import FastMCP

# CoreLocationCLI (OPTIONAL: installed via: brew install corelocationcli)
# If not available, falls back to IP-based geolocation
CORELOCATION_CMD = "CoreLocationCLI"
CORELOCATION_AVAILABLE = None  # Lazy-checked on first use

mcp = FastMCP("central-hub")

# Output paths for widget consumption
WEATHER_FILE = Path("/tmp/central-hub-weather.json")
TIME_FILE = Path("/tmp/central-hub-time.json")
STATUS_FILE = Path("/tmp/claude-status.json")
LOCATION_FILE = Path("/tmp/central-hub-location.json")

# Cache duration in seconds
CACHE_DURATION = 60  # 1 minute


def _is_corelocation_available() -> bool:
    """Check if CoreLocationCLI is available on the system."""
    global CORELOCATION_AVAILABLE
    if CORELOCATION_AVAILABLE is not None:
        return CORELOCATION_AVAILABLE

    try:
        result = subprocess.run(
            ["which", CORELOCATION_CMD],
            capture_output=True,
            timeout=2,
        )
        CORELOCATION_AVAILABLE = result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        CORELOCATION_AVAILABLE = False

    return CORELOCATION_AVAILABLE


def _get_cached(file_path: Path, max_age: int = CACHE_DURATION) -> dict | None:
    """Get cached data if fresh enough."""
    if not file_path.exists():
        return None
    try:
        data = json.loads(file_path.read_text())
        timestamp = datetime.fromisoformat(data.get("timestamp", ""))
        age = (datetime.now() - timestamp.replace(tzinfo=None)).total_seconds()
        if age < max_age:
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _get_location_corelocation() -> dict | None:
    """Try to get location via macOS CoreLocation (more accurate, OPTIONAL)."""
    if not _is_corelocation_available():
        return None

    try:
        result = subprocess.run(
            [CORELOCATION_CMD, "-j"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            # Map CoreLocationCLI output to our format
            return {
                "latitude": float(data["latitude"]),
                "longitude": float(data["longitude"]),
                "city": data.get("locality", ""),
                "region": data.get("administrativeArea", ""),
                "country": data.get("country", ""),
                "timezone": data.get("timeZone", ""),
            }
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError, Exception):
        pass
    return None


def _get_location_ip() -> dict | None:
    """Get location via IP geolocation (fallback, no special dependencies)."""
    try:
        response = requests.get("http://ip-api.com/json/", timeout=5)
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "success":
            return {
                "latitude": data["lat"],
                "longitude": data["lon"],
                "city": data.get("city", "Unknown"),
                "region": data.get("regionName", ""),
                "country": data.get("country", ""),
                "timezone": data.get("timezone", ""),
            }
    except requests.RequestException:
        pass
    return None


def _get_location() -> tuple[float, float, str]:
    """Get current location (CoreLocation first if available, then IP fallback)."""
    # Check cache first (1 min for location data, considered fresh)
    cached = _get_cached(LOCATION_FILE, max_age=60)
    if cached:
        return cached["latitude"], cached["longitude"], cached["city"]

    location_data = None
    source = None

    # Try CoreLocation first if available (more accurate, GPS-based)
    location_data = _get_location_corelocation()
    if location_data:
        source = "corelocation"
    else:
        # Fall back to IP geolocation (always available)
        location_data = _get_location_ip()
        if location_data:
            source = "ip"

    if location_data:
        # Add metadata and cache
        location_data["source"] = source
        location_data["timestamp"] = datetime.now().isoformat()
        LOCATION_FILE.write_text(json.dumps(location_data, indent=2))
        return location_data["latitude"], location_data["longitude"], location_data["city"]

    # Fallback to San Francisco
    return 37.7749, -122.4194, "San Francisco"


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


def _fetch_weather(latitude: float, longitude: float) -> dict:
    """Fetch weather from Open-Meteo API (free, no API key required)."""
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
    return {
        "temperature": current.get("temperature_2m", "?"),
        "weather_code": current.get("weather_code", 0),
        "wind_speed": current.get("wind_speed_10m", 0),
    }


@mcp.tool()
async def ping() -> str:
    """Test that the server is running."""
    return "pong"


@mcp.tool()
async def get_weather(latitude: float = None, longitude: float = None) -> str:
    """
    Fetch current weather for a location and write to widget file.

    Args:
        latitude: Latitude (default: auto-detect from IP)
        longitude: Longitude (default: auto-detect from IP)

    Returns:
        Weather summary string
    """
    try:
        # Check cache first
        cached = _get_cached(WEATHER_FILE)
        if cached and latitude is None and longitude is None:
            temp = cached["temperature"]
            desc = cached["description"]
            wind = cached["wind_speed"]
            city = cached.get("city", "")
            return f"{temp}°F, {desc}, Wind: {wind} mph ({city}) [cached]"

        # Get location
        if latitude is None or longitude is None:
            latitude, longitude, city = _get_location()
        else:
            city = "Custom"

        # Fetch weather
        weather = _fetch_weather(latitude, longitude)
        weather_desc = _weather_code_to_desc(weather["weather_code"])

        # Build widget data
        widget_data = {
            "temperature": weather["temperature"],
            "description": weather_desc,
            "wind_speed": weather["wind_speed"],
            "latitude": latitude,
            "longitude": longitude,
            "city": city,
            "timestamp": datetime.now().isoformat(),
        }

        # Write to file for widget
        WEATHER_FILE.write_text(json.dumps(widget_data, indent=2))

        return f"{weather['temperature']}°F, {weather_desc}, Wind: {weather['wind_speed']} mph ({city})"

    except requests.RequestException as e:
        return f"Error fetching weather: {e}"


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


# --- Background refresh function (called by cron/launchd) ---

def refresh_all():
    """Refresh all data sources. Called by background daemon."""
    import asyncio

    print(f"[{datetime.now().isoformat()}] Refreshing data...")

    # Get location first
    lat, lon, city = _get_location()
    print(f"  Location: {city} ({lat}, {lon})")

    # Fetch weather
    try:
        weather = _fetch_weather(lat, lon)
        weather_desc = _weather_code_to_desc(weather["weather_code"])

        widget_data = {
            "temperature": weather["temperature"],
            "description": weather_desc,
            "wind_speed": weather["wind_speed"],
            "latitude": lat,
            "longitude": lon,
            "city": city,
            "timestamp": datetime.now().isoformat(),
        }
        WEATHER_FILE.write_text(json.dumps(widget_data, indent=2))
        print(f"  Weather: {weather['temperature']}°F, {weather_desc}")
    except Exception as e:
        print(f"  Weather error: {e}")

    # Update time
    try:
        from zoneinfo import ZoneInfo
        # Use detected timezone if available
        cached_loc = _get_cached(LOCATION_FILE, max_age=3600)
        tz_name = cached_loc.get("timezone", "America/Los_Angeles") if cached_loc else "America/Los_Angeles"
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)

        time_data = {
            "time": now.strftime("%H:%M"),
            "date": now.strftime("%Y-%m-%d"),
            "day": now.strftime("%A"),
            "timezone": tz_name,
            "timestamp": now.isoformat(),
        }
        TIME_FILE.write_text(json.dumps(time_data, indent=2))
        print(f"  Time: {now.strftime('%H:%M')} ({tz_name})")
    except Exception as e:
        print(f"  Time error: {e}")


if __name__ == "__main__":
    # Check if called with --refresh flag for background updates
    if len(sys.argv) > 1 and sys.argv[1] == "--refresh":
        refresh_all()
    else:
        mcp.run()
