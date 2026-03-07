"""IPC command handlers for daemon commands and state queries.

Splits handlers into domain modules (memory, knowledge, media, agent, state).
Each module defines standalone functions that take ``self`` as a CommandHandlers
instance. This ``__init__`` binds them as methods and registers with the IPC server.
"""

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..context import AppContext

from ...display.refresh_manager import RefreshManager
from ...services.session_tracker import SessionTracker
from ..ipc import DaemonServer
from . import agent as _agent
from . import knowledge as _knowledge
from . import media as _media
from . import memory as _memory
from . import state as _state

_DOMAIN_MODULES = [_memory, _knowledge, _media, _agent, _state]


def _bind(fn, handlers):
    """Create a closure that binds a domain function to a CommandHandlers instance."""

    def wrapper(**kw):
        return fn(handlers, **kw)

    return wrapper


class CommandHandlers:
    """Registers and implements IPC command handlers for the daemon.

    All state access goes through the injected StateStore. Service
    delegation goes through the injected manager instances.
    """

    def __init__(
        self,
        ctx: "AppContext",
        session_tracker: SessionTracker,
        refresh: RefreshManager,
        command_server: DaemonServer,
        services: dict[str, Callable[[], Any | None]] | None = None,
    ):
        self.ctx = ctx
        self.session_tracker = session_tracker
        self.refresh = refresh
        self.command_server = command_server
        self._services = services or {}

        # Bind all domain functions as instance methods
        for mod in _DOMAIN_MODULES:
            for _ipc_name, fn_name in mod.COMMANDS.items():
                setattr(self, fn_name, _bind(getattr(mod, fn_name), self))

    def register_all(self) -> None:
        """Register all command handlers with the IPC server."""
        reg = self.command_server.register

        # Register refresh shortcuts directly
        reg("refresh_weather", self.refresh.refresh_weather)
        reg("refresh_time", self.refresh.refresh_time)

        # Register all domain commands
        for mod in _DOMAIN_MODULES:
            for ipc_name, fn_name in mod.COMMANDS.items():
                reg(ipc_name, getattr(self, fn_name))

    def _get_service(self, name: str):
        """Get a service by name from the services dict."""
        provider = self._services.get(name)
        return provider() if provider else None

    def _mem_op(self, fn, timeout=30):
        """Run an async MemoryStore operation. Returns result or error dict."""
        import asyncio

        store = self._get_service("memory")
        if store is None or not store.ready:
            return {"error": "Memory not available"}
        try:
            return asyncio.run_coroutine_threadsafe(fn(store), self.ctx.loop).result(timeout=timeout)
        except Exception as exc:
            return {"error": str(exc)}
