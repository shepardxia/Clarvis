"""File-based caching utilities with TTL support."""

import json
from datetime import datetime
from pathlib import Path

# Default cache duration in seconds
DEFAULT_CACHE_DURATION = 60

# Central hub data file - single structured JSON for all widget data
HUB_DATA_FILE = Path("/tmp/central-hub-data.json")


def read_hub_data() -> dict:
    """Read the central hub data file."""
    if HUB_DATA_FILE.exists():
        try:
            return json.loads(HUB_DATA_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def write_hub_section(section: str, data: dict) -> None:
    """
    Update a section of the hub data file.

    Args:
        section: Key name (e.g., "weather", "time", "location")
        data: Data dict to store under that section
    """
    hub_data = read_hub_data()
    hub_data[section] = {
        **data,
        "updated_at": datetime.now().isoformat(),
    }
    hub_data["last_updated"] = datetime.now().isoformat()

    # Write atomically
    temp_file = HUB_DATA_FILE.with_suffix('.tmp')
    temp_file.write_text(json.dumps(hub_data, indent=2))
    temp_file.rename(HUB_DATA_FILE)


def get_hub_section(section: str, max_age: int = DEFAULT_CACHE_DURATION):
    """
    Get a section from hub data if fresh enough.

    Args:
        section: Key name to retrieve
        max_age: Maximum age in seconds

    Returns:
        Section data if valid and fresh, None otherwise
    """
    hub_data = read_hub_data()
    section_data = hub_data.get(section)
    if not section_data:
        return None

    try:
        timestamp = datetime.fromisoformat(section_data.get("updated_at", ""))
        age = (datetime.now() - timestamp.replace(tzinfo=None)).total_seconds()
        if age < max_age:
            return section_data
    except (ValueError, TypeError):
        pass
    return None
