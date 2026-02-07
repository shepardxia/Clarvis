"""Time and timezone utilities."""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "America/Los_Angeles"


@dataclass
class TimeData:
    """Current time data."""

    time: str  # HH:MM format
    date: str  # YYYY-MM-DD format
    day: str  # Full day name (e.g., "Wednesday")
    timezone: str  # Timezone name
    iso_timestamp: str  # Full ISO timestamp

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "time": self.time,
            "date": self.date,
            "day": self.day,
            "timezone": self.timezone,
            "timestamp": self.iso_timestamp,
        }


def get_current_time(timezone: str = DEFAULT_TIMEZONE) -> TimeData:
    """
    Get current time in the specified timezone.

    Args:
        timezone: Timezone name (e.g., "America/Los_Angeles", "Europe/London")

    Returns:
        TimeData with current time information

    Raises:
        ZoneInfoNotFoundError: If timezone is invalid
    """
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)

    return TimeData(
        time=now.strftime("%H:%M"),
        date=now.strftime("%Y-%m-%d"),
        day=now.strftime("%A"),
        timezone=timezone,
        iso_timestamp=now.isoformat(),
    )
