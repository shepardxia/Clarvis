"""
Archetypes - Python classes for complex visual behaviors.

Archetypes consume element definitions from YAML but add runtime logic
like physics simulation, animation state machines, etc.
"""

from .base import Archetype
from .face import FaceArchetype
from .progress import ProgressArchetype
from .weather import WeatherArchetype

__all__ = [
    "Archetype",
    "FaceArchetype",
    "WeatherArchetype",
    "ProgressArchetype",
]
