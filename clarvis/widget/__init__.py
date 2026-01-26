"""Widget rendering - pipeline, archetypes, and display service."""

from .renderer import FrameRenderer
from .pipeline import RenderPipeline, Layer
from .display_service import DisplayService, main as run_display_service
from .socket_server import get_socket_server, reset_socket_server

# Status colors are centralized in core.colors
from ..core.colors import STATUS_MAP as STATUS_COLORS

__all__ = [
    # Renderer
    "FrameRenderer",
    # Pipeline
    "RenderPipeline",
    "Layer",
    # Display service
    "DisplayService",
    "run_display_service",
    # Socket server
    "get_socket_server",
    "reset_socket_server",
    # Colors
    "STATUS_COLORS",
]
