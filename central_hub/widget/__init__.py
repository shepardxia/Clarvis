"""Widget rendering - avatar, sprites, and display service."""

from .avatar import build_frame, get_frames, get_avatar_data
from .renderer import FrameRenderer
from .pipeline import RenderPipeline, Layer
from .display_service import DisplayService, main as run_display_service
from .canvas import (
    Color,
    STATUS_COLORS,
    Cell,
    Canvas,
    Brush,
    Sprite,
    SPRITES,
    FaceBuilder,
)

__all__ = [
    # Legacy avatar
    "build_frame",
    "get_frames",
    "get_avatar_data",
    # Renderer
    "FrameRenderer",
    # Pipeline
    "RenderPipeline",
    "Layer",
    # Display service
    "DisplayService",
    "run_display_service",
    # Canvas system (modular drawing)
    "Color",
    "STATUS_COLORS",
    "Cell",
    "Canvas",
    "Brush",
    "Sprite",
    "SPRITES",
    "FaceBuilder",
]
