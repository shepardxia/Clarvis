"""Core utilities - caching, time services, state management, IPC, colors, and managers."""

from .cache import read_hub_data, write_hub_section, get_hub_section
from .time_service import get_current_time, TimeData, DEFAULT_TIMEZONE
from .state import StateStore, get_state_store, reset_state_store
from .ipc import DaemonServer, DaemonClient, get_daemon_client
from .colors import (
    ColorDef,
    Palette,
    StatusColors,
    STATUS_MAP,
    ANSI_COLORS,
    STATUS_ANSI,
    get_status_colors_for_config,
)
from .session_tracker import SessionTracker
from .display_manager import DisplayManager
from .refresh_manager import RefreshManager

__all__ = [
    # Cache
    "read_hub_data",
    "write_hub_section",
    "get_hub_section",
    # Time
    "get_current_time",
    "TimeData",
    "DEFAULT_TIMEZONE",
    # State
    "StateStore",
    "get_state_store",
    "reset_state_store",
    # IPC
    "DaemonServer",
    "DaemonClient",
    "get_daemon_client",
    # Colors
    "ColorDef",
    "Palette",
    "StatusColors",
    "STATUS_MAP",
    "ANSI_COLORS",
    "STATUS_ANSI",
    "get_status_colors_for_config",
    # Managers
    "SessionTracker",
    "DisplayManager",
    "RefreshManager",
]
