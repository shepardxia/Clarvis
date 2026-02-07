"""Widget rendering - pipeline, archetypes, and socket server."""

# Status colors are centralized in core.colors
from ..core.colors import STATUS_MAP as STATUS_COLORS
from .pipeline import Layer, RenderPipeline
from .renderer import FrameRenderer
from .socket_server import get_socket_server

__all__ = [
    # Renderer
    "FrameRenderer",
    # Pipeline
    "RenderPipeline",
    "Layer",
    # Socket server
    "get_socket_server",
    # Colors
    "STATUS_COLORS",
]
