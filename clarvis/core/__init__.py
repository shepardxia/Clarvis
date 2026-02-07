"""Core utilities - state management, IPC, colors, scheduling, and managers."""

# isort: skip_file
# Import order matters: refresh_manager defines DEFAULT_TIMEZONE/TimeData/get_current_time,
# and must be imported before modules that depend on them via this package.

from .refresh_manager import DEFAULT_TIMEZONE, TimeData, get_current_time
from .state import StateStore, get_state_store
from .ipc import DaemonClient, DaemonServer, get_daemon_client
from .colors import (
    STATUS_MAP,
    ColorDef,
    StatusColors,
)
from .session_tracker import SessionTracker
from .display_manager import DisplayManager
from .refresh_manager import RefreshManager
from .scheduler import Scheduler
from .hook_processor import HookProcessor, classify_tool

__all__ = [
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
    # Managers
    "SessionTracker",
    "DisplayManager",
    "RefreshManager",
    "Scheduler",
    # Tool classification & processing
    "classify_tool",
    "HookProcessor",
]
