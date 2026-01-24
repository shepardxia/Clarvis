"""Widget rendering - avatar, sprites, and display service."""

from .renderer import FrameRenderer
from .pipeline import RenderPipeline, Layer
from .display_service import DisplayService, main as run_display_service
from .socket_server import get_socket_server, reset_socket_server
from .canvas import (
    Color,
    Cell,
    Canvas,
    Brush,
    Sprite,
    SPRITES,
    FaceBuilder,
)

# Status colors are now centralized in core.colors
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
    # Canvas system (modular drawing)
    "Color",
    "STATUS_COLORS",  # Re-exported from core.colors
    "Cell",
    "Canvas",
    "Brush",
    "Sprite",
    "SPRITES",
    "FaceBuilder",
]
