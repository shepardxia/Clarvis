"""File-based state persistence for daemon restart recovery."""

import json
from pathlib import Path

# Clarvis data file - single structured JSON for all widget data
HUB_DATA_FILE = Path("/tmp/clarvis-data.json")


def read_hub_data() -> dict:
    """Read the Clarvis data file (used for initial state restore on daemon startup)."""
    if HUB_DATA_FILE.exists():
        try:
            return json.loads(HUB_DATA_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}
