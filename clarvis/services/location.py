"""Location detection via CoreLocation (macOS) or IP geolocation fallback."""

from __future__ import annotations

import json
import subprocess
import time as _time

import requests

# CoreLocationCLI (OPTIONAL: installed via: brew install corelocationcli)
CORELOCATION_CMD = "CoreLocationCLI"
_corelocation_available: bool | None = None  # Lazy-checked on first use

# In-memory location cache
_cache: dict | None = None
_cache_time: float = 0.0

# Default location (San Francisco)
DEFAULT_LOCATION = {
    "latitude": 37.7749,
    "longitude": -122.4194,
    "city": "San Francisco",
    "timezone": "",
    "source": "default",
}


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


def get_location_full(cache_max_age: int = 60) -> dict:
    """Get full location dict with automatic fallback.

    Tries in order:
    1. Cache from CoreLocation (if fresh) - trusted GPS source
    2. CoreLocationCLI (if available) - always prefer real GPS
    3. Cache from IP (if fresh) - only if no GPS available
    4. IP geolocation API
    5. Default (San Francisco)

    Returns:
        Dict with latitude, longitude, city, timezone, source, etc.
    """
    global _cache, _cache_time

    cached = _cache if _cache and (_time.time() - _cache_time) < cache_max_age else None

    # If cache is from CoreLocation (GPS), trust it
    if cached and cached.get("source") == "corelocation":
        return cached

    # Always try CoreLocation if available - GPS beats IP geolocation
    location_data = _get_location_corelocation()
    if location_data:
        _cache = location_data
        _cache_time = _time.time()
        return location_data

    # No GPS available - use IP cache if fresh
    if cached:
        return cached

    # Fall back to IP geolocation
    location_data = _get_location_ip()
    if location_data:
        _cache = location_data
        _cache_time = _time.time()
        return location_data

    return DEFAULT_LOCATION


def get_location(cache_max_age: int = 60) -> tuple[float, float, str]:
    """Get current location as (latitude, longitude, city) tuple.

    Convenience wrapper around get_location_full().
    """
    loc = get_location_full(cache_max_age)
    return loc["latitude"], loc["longitude"], loc["city"]
