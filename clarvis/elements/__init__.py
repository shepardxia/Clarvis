"""
Modular visual elements system.

Provides data-driven definitions for avatar, weather, and UI elements.
Elements are loaded from YAML files and can be hot-reloaded without restart.
"""

from .registry import ElementRegistry

__all__ = ["ElementRegistry"]
