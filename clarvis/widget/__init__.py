"""Widget rendering - pipeline, archetypes, and socket server."""

from .renderer import FrameRenderer
from .pipeline import RenderPipeline, Layer
from .socket_server import get_socket_server, reset_socket_server

# Status colors are centralized in core.colors
from ..core.colors import STATUS_MAP as STATUS_COLORS

__all__ = [
    # Renderer
    "FrameRenderer",
    # Pipeline
    "RenderPipeline",
    "Layer",
    # Socket server
    "get_socket_server",
    "reset_socket_server",
    # Colors
    "STATUS_COLORS",
]
