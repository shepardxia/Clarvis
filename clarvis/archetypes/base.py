"""
Base protocols and classes for archetypes.
"""

from abc import ABC, abstractmethod
from typing import Protocol

from ..elements.registry import ElementRegistry
from ..widget.pipeline import Layer


class Renderable(Protocol):
    """Protocol for anything that can render to a layer."""

    def render(self, layer: Layer, x: int, y: int, color: int) -> None:
        """Render this element to a layer at position."""
        ...


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


class SimpleElement:
    """
    A simple renderable element loaded from YAML.

    Renders a single character or pattern at a position.
    """

    def __init__(self, definition: dict):
        """
        Initialize from element definition dict.

        Expected keys:
        - char: Single character to render
        - pattern: Multi-line pattern string (alternative to char)
        - position: Optional [l, g, r] for eye positioning
        """
        self.char = definition.get("char", " ")
        self.pattern = definition.get("pattern")
        self.position = definition.get("position", [0, 0, 0])

        # Parse multi-line pattern if present
        if self.pattern and "\n" in str(self.pattern):
            self.lines = [line for line in str(self.pattern).split("\n") if line]
        else:
            self.lines = [self.pattern] if self.pattern else [self.char]

    @property
    def width(self) -> int:
        return max(len(line) for line in self.lines) if self.lines else 1

    @property
    def height(self) -> int:
        return len(self.lines)

    def render(self, layer: Layer, x: int, y: int, color: int) -> None:
        """Render element to layer."""
        for dy, line in enumerate(self.lines):
            for dx, char in enumerate(line):
                if char != " ":
                    layer.put(x + dx, y + dy, char, color)


class Composite:
    """
    A composite element that renders multiple children.

    Children are positioned relative to the composite's origin.
    """

    def __init__(self, definition: dict, registry: ElementRegistry):
        """
        Initialize from composite definition dict.

        Expected keys:
        - children: Dict mapping names to {element: "kind/name", position: [x, y]}
        - width: Optional composite width
        - height: Optional composite height
        """
        self.registry = registry
        self.width = definition.get("width", 0)
        self.height = definition.get("height", 0)
        self.children: dict[str, dict] = {}

        for name, child_def in definition.get("children", {}).items():
            element_path = child_def.get("element", "")
            if "/" in element_path:
                kind, elem_name = element_path.split("/", 1)
                elem_def = registry.get(kind, elem_name)
                if elem_def:
                    self.children[name] = {
                        "element": SimpleElement(elem_def),
                        "position": child_def.get("position", [0, 0]),
                    }

    def render(self, layer: Layer, x: int, y: int, color: int) -> None:
        """Render all children to layer."""
        for name, child in self.children.items():
            cx, cy = child["position"]
            child["element"].render(layer, x + cx, y + cy, color)
