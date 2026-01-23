"""Location detection via CoreLocation (macOS) or IP geolocation fallback."""

import json
import subprocess

import requests

from ..core.cache import get_hub_section, write_hub_section

# CoreLocationCLI (OPTIONAL: installed via: brew install corelocationcli)
CORELOCATION_CMD = "CoreLocationCLI"
_corelocation_available: bool | None = None  # Lazy-checked on first use

# Default location (San Francisco)
DEFAULT_LOCATION = (37.7749, -122.4194, "San Francisco")


def _is_corelocation_available() -> bool:
    """Check if CoreLocationCLI is available on the system."""
    global _corelocation_available
    if _corelocation_available is not None:
        return _corelocation_available

    try:
        result = subprocess.run(
            ["which", CORELOCATION_CMD],
            capture_output=True,
            timeout=2,
        )
        _corelocation_available = result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        _corelocation_available = False

    return _corelocation_available


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
            return {
                "latitude": float(data["latitude"]),
                "longitude": float(data["longitude"]),
                "city": data.get("locality", ""),
                "region": data.get("administrativeArea", ""),
                "country": data.get("country", ""),
                "timezone": data.get("timeZone", ""),
                "source": "corelocation",
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
                "source": "ip",
            }
    except requests.RequestException:
        pass
    return None


def get_location(cache_max_age: int = 60) -> tuple[float, float, str]:
    """
    Get current location with automatic fallback.

    Tries in order:
    1. Cache (if fresh)
    2. CoreLocationCLI (if available, more accurate GPS-based)
    3. IP geolocation API
    4. Default (San Francisco)

    Args:
        cache_max_age: Maximum cache age in seconds

    Returns:
        Tuple of (latitude, longitude, city)
    """
    # Check cache first
    cached = get_hub_section("location", max_age=cache_max_age)
    if cached:
        return cached["latitude"], cached["longitude"], cached["city"]

    # Try CoreLocation first if available (more accurate, GPS-based)
    location_data = _get_location_corelocation()

    # Fall back to IP geolocation
    if location_data is None:
        location_data = _get_location_ip()

    if location_data:
        write_hub_section("location", location_data)
        return location_data["latitude"], location_data["longitude"], location_data["city"]

    # Final fallback
    return DEFAULT_LOCATION


def get_cached_timezone() -> str | None:
    """Get timezone from cached location data, if available."""
    cached = get_hub_section("location", max_age=3600)  # 1 hour for timezone
    if cached:
        return cached.get("timezone")
    return None
