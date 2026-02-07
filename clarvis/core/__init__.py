"""Core utilities - caching, time services, state management, IPC, colors, and managers."""

# isort: skip_file
# Import order matters: refresh_manager imports DEFAULT_TIMEZONE from this package,
# so time_service must be imported first.

from .cache import read_hub_data
from .time_service import DEFAULT_TIMEZONE, TimeData, get_current_time
from .state import StateStore, get_state_store
from .ipc import DaemonClient, DaemonServer, get_daemon_client
from .colors import (
    STATUS_MAP,
    ColorDef,
    StatusColors,
    get_status_colors_for_config,
)
from .session_tracker import SessionTracker
from .display_manager import DisplayManager
from .refresh_manager import RefreshManager
from .scheduler import Scheduler
from .tool_classifier import classify_tool
from .hook_processor import HookProcessor

__all__ = [
    # Cache
    "read_hub_data",
    # Time
    "get_current_time",
    "TimeData",
    "DEFAULT_TIMEZONE",
    # State
    "StateStore",
    "get_state_store",
    # IPC
    "DaemonServer",
    "DaemonClient",
    "get_daemon_client",
    # Colors
    "ColorDef",
    "StatusColors",
    "STATUS_MAP",
    "get_status_colors_for_config",
    # Managers
    "SessionTracker",
    "DisplayManager",
    "RefreshManager",
    "Scheduler",
    # Tool classification & processing
    "classify_tool",
    "HookProcessor",
]
