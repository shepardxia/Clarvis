"""
Base class for archetypes.
"""

from abc import ABC, abstractmethod

from ..elements.registry import ElementRegistry
from ..widget.pipeline import Layer


class Archetype(ABC):
    """
    Base class for complex visual behaviors.

    Archetypes load configuration and element definitions from the registry,
    then provide runtime behavior (animation, physics, state machines).

    Subclasses must implement:
    - render(): Draw to a layer
    - _on_element_change(): Handle hot-reload notifications
    """

    def __init__(self, registry: ElementRegistry, config_name: str):
        """
        Initialize archetype with registry and config name.

        Args:
            registry: Element registry for loading definitions
            config_name: Name of archetype config in elements/archetypes/
        """
        self.registry = registry
        self.config_name = config_name
        self._load_config()
        registry.on_change(self._handle_change)

    def _load_config(self) -> None:
        """Load archetype configuration from registry."""
        self.config = self.registry.get("archetypes", self.config_name) or {}

    def _handle_change(self, kind: str, name: str) -> None:
        """Handle element change notification."""
        if kind == "archetypes" and name == self.config_name:
            self._load_config()
        self._on_element_change(kind, name)

    @abstractmethod
    def _on_element_change(self, kind: str, name: str) -> None:
        """
        Handle element change notification.

        Called when any element in the registry changes.
        Subclasses should check if the change is relevant and rebuild caches.
        """
        ...

    @abstractmethod
    def render(self, layer: Layer, **kwargs) -> None:
        """Render this archetype to a layer."""
        ...

    def tick(self) -> None:
        """Advance animation/simulation state. Override if needed."""
        pass
