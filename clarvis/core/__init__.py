"""Core utilities - caching, time services, state management, IPC, colors, and managers."""

from .cache import read_hub_data
from .time_service import get_current_time, TimeData, DEFAULT_TIMEZONE
from .state import StateStore, get_state_store, reset_state_store
from .ipc import DaemonServer, DaemonClient, get_daemon_client
from .colors import (
    ColorDef,
    StatusColors,
    STATUS_MAP,
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
    "reset_state_store",
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
