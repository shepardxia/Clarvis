"""IPC command handlers for daemon commands and state queries.

Splits handlers into domain modules (memory, knowledge, media, agent, state).
Each module defines standalone functions that take ``self`` as a CommandHandlers
instance. ``register_all`` binds them directly to the IPC server.
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
from . import web as _web

_DOMAIN_MODULES = [_memory, _knowledge, _media, _agent, _state, _web]


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

    def register_all(self) -> None:
        """Register all command handlers with the IPC server."""
        reg = self.command_server.register

        # Register refresh shortcuts directly
        reg("refresh_weather", self.refresh.refresh_weather)
        reg("refresh_time", self.refresh.refresh_time)

        # Register all domain commands
        for mod in _DOMAIN_MODULES:
            for name in mod.COMMANDS:
                fn = getattr(mod, name)

                def _make_handler(_fn=fn):
                    def handler(**kw):
                        return _fn(self, **kw)

                    return handler

                reg(name, _make_handler())

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
