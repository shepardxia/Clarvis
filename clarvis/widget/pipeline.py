"""
Layered rendering pipeline with vectorized compositing.

Simple model: one character per cell, higher priority layers win.
Space character = transparent (doesn't overwrite lower layers).
"""

from __future__ import annotations
import numpy as np
from typing import Callable, Optional

# Space character code - used as transparency
SPACE = ord(' ')


class Layer:
    """A single rendering layer with char and color arrays."""

    def __init__(self, name: str, priority: int, width: int, height: int,
                 render_func: Callable[['Layer'], None] | None = None):
        self.name = name
        self.priority = priority
        self.width = width
        self.height = height
        self.render_func = render_func

        # NumPy arrays for vectorized operations
        self.chars = np.full((height, width), SPACE, dtype=np.uint32)
        self.colors = np.zeros((height, width), dtype=np.uint8)

    def clear(self):
        """Clear layer to transparent (spaces)."""
        self.chars.fill(SPACE)
        self.colors.fill(0)

    def put(self, x: int, y: int, char: str, color: int = 7):
        """Put a single character at position."""
        if 0 <= x < self.width and 0 <= y < self.height:
            self.chars[y, x] = ord(char)
            self.colors[y, x] = color

    def put_text(self, x: int, y: int, text: str, color: int = 7):
        """Put a string horizontally."""
        for i, char in enumerate(text):
            self.put(x + i, y, char, color)

    def fill(self, x: int, y: int, w: int, h: int, char: str = ' ', color: int = 7):
        """Fill a rectangle."""
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(self.width, x + w), min(self.height, y + h)
        self.chars[y1:y2, x1:x2] = ord(char)
        self.colors[y1:y2, x1:x2] = color


class RenderPipeline:
    """Manages layers and composites them with vectorized operations."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.layers: dict[str, Layer] = {}

        # Output buffers
        self.out_chars = np.full((height, width), SPACE, dtype=np.uint32)
        self.out_colors = np.zeros((height, width), dtype=np.uint8)

    def add_layer(self, name: str, priority: int,
                  render_func: Callable[[Layer], None] | None = None) -> Layer:
        """Create and register a new layer."""
        layer = Layer(name, priority, self.width, self.height, render_func)
        self.layers[name] = layer
        return layer

    def get_layer(self, name: str) -> Layer | None:
        """Get a layer by name."""
        return self.layers.get(name)

    def remove_layer(self, name: str):
        """Remove a layer."""
        self.layers.pop(name, None)

    def render(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Render all layers and flatten.

        1. Call each layer's render_func (if set)
        2. Composite layers by priority (low to high)
        3. Return (chars, colors) arrays
        """
        # Clear output
        self.out_chars.fill(SPACE)
        self.out_colors.fill(0)

        # Sort layers by priority
        sorted_layers = sorted(self.layers.values(), key=lambda l: l.priority)

        # Render and composite each layer
        for layer in sorted_layers:
            # Call render function if set
            if layer.render_func:
                layer.clear()
                layer.render_func(layer)

            # Vectorized composite: non-space chars overwrite
            mask = layer.chars != SPACE
            np.copyto(self.out_chars, layer.chars, where=mask)
            np.copyto(self.out_colors, layer.colors, where=mask)

        return self.out_chars, self.out_colors

    def to_string(self) -> str:
        """Render and return plain text."""
        self.render()
        return '\n'.join(''.join(chr(c) for c in row) for row in self.out_chars)

    def to_ansi(self) -> str:
        """Render and return ANSI-colored text.

        Color code 0 is treated as "default/theme color" and emits reset code.
        This allows Swift to use its theme color for those characters.
        """
        self.render()
        lines = []
        for y in range(self.height):
            parts = []
            current_color = -1
            for x in range(self.width):
                color = self.out_colors[y, x]
                char = chr(self.out_chars[y, x])
                if color != current_color:
                    if color == 0:
                        # Color 0 = use default/theme color
                        parts.append("\033[0m")
                    else:
                        parts.append(f"\033[38;5;{color}m")
                    current_color = color
                parts.append(char)
            parts.append("\033[0m")
            lines.append(''.join(parts))
        return '\n'.join(lines)


# =============================================================================
# Demo
# =============================================================================

if __name__ == "__main__":
    import time

    # Create pipeline
    p = RenderPipeline(20, 10)

    # Layer 0: Background particles
    def render_particles(layer: Layer):
        import random
        for _ in range(15):
            x, y = random.randint(0, 19), random.randint(0, 9)
            layer.put(x, y, random.choice(['*', '+', '.']), color=8)

    particles = p.add_layer("particles", priority=0, render_func=render_particles)

    # Layer 50: Avatar (higher priority, will cover particles)
    def render_avatar(layer: Layer):
        face = [
            "+=========+",
            "|   o o   |",
            "|    u    |",
            "| * o * o |",
            "+=========+",
        ]
        for dy, line in enumerate(face):
            layer.put_text(4, 2 + dy, line, color=10)

    avatar = p.add_layer("avatar", priority=50, render_func=render_avatar)

    # Layer 80: Progress bar
    def render_bar(layer: Layer):
        for i in range(12):
            char = '#' if i < 7 else '-'
            color = 10 if i < 7 else 8
            layer.put(4 + i, 8, char, color)

    bar = p.add_layer("bar", priority=80, render_func=render_bar)

    # Animate
    print("\033[2J\033[H")  # Clear screen
    print("Pipeline Demo (Ctrl+C to stop)\n")

    try:
        for _ in range(30):
            print("\033[3;0H")  # Move cursor
            print(p.to_ansi())
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass

    print("\nDone!")
