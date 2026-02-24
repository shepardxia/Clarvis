"""Shared MCP helpers — deduplicated daemon accessor and lifespan factory."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastmcp import Context, FastMCP

if TYPE_CHECKING:
    from ..daemon import CentralHubDaemon


def get_daemon(ctx: Context) -> "CentralHubDaemon":
    """Retrieve the daemon instance from a FastMCP lifespan context."""
    return ctx.fastmcp._lifespan_result["daemon"]


def make_lifespan(daemon, **extras):
    """Return a lifespan context manager that injects daemon (+ extras) into FastMCP."""

    @asynccontextmanager
    async def _lifespan(server):
        yield {"daemon": daemon, **extras}

    return _lifespan


def get_daemon_service(ctx: Context, attr: str, label: str):
    """Retrieve a daemon service, returning ``(service, None)`` or ``(None, error_str)``."""
    d = get_daemon(ctx)
    svc = getattr(d, attr, None)
    if svc is None:
        return None, f"Error: {label} not available"
    return svc, None


def create_tool_server(name: str, tools: list, daemon, **extras) -> FastMCP:
    """Create a FastMCP sub-server with the given tools and daemon lifespan."""
    srv = FastMCP(name, lifespan=make_lifespan(daemon, **extras))
    for fn in tools:
        srv.tool()(fn)
    return srv
