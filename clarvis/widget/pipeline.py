"""
Layered rendering pipeline with vectorized compositing.

Each layer tracks its bounding box as content is rendered.
During compositing, the entire bounding box region overwrites lower layers,
making layers fully opaque within their rendered area.
"""

from __future__ import annotations
import numpy as np
from typing import Callable, Optional

# Space character code - background fill
SPACE = ord(' ')


def str_to_matrix(template: str) -> np.ndarray:
    """
    Convert a multi-line string template to a 2D char matrix.

    Example:
        template = '''
        ╭===╮
        │ o │
        ╰===╯
        '''
        matrix = str_to_matrix(template)  # shape (3, 5)
    """
    lines = template.strip('\n').split('\n')
    if not lines:
        return np.array([[]], dtype=np.uint32)

    # Pad all lines to same width
    max_width = max(len(line) for line in lines)
    padded = [line.ljust(max_width) for line in lines]

    # Convert to char codes
    matrix = np.array([[ord(c) for c in line] for line in padded], dtype=np.uint32)
    return matrix


class Layer:
    """A single rendering layer with char and color arrays and bounding box tracking."""

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

        # Bounding box of rendered content (None = empty layer)
        self._bbox: tuple[int, int, int, int] | None = None  # (x1, y1, x2, y2)

    def _expand_bbox(self, x: int, y: int) -> None:
        """Expand bounding box to include point (x, y)."""
        if self._bbox is None:
            self._bbox = (x, y, x + 1, y + 1)
        else:
            x1, y1, x2, y2 = self._bbox
            self._bbox = (min(x1, x), min(y1, y), max(x2, x + 1), max(y2, y + 1))

    def _expand_bbox_rect(self, x: int, y: int, w: int, h: int) -> None:
        """Expand bounding box to include rectangle."""
        if w <= 0 or h <= 0:
            return
        if self._bbox is None:
            self._bbox = (x, y, x + w, y + h)
        else:
            x1, y1, x2, y2 = self._bbox
            self._bbox = (min(x1, x), min(y1, y), max(x2, x + w), max(y2, y + h))

    @property
    def bbox(self) -> tuple[int, int, int, int] | None:
        """Get bounding box (x1, y1, x2, y2) or None if empty."""
        return self._bbox

    def clear(self):
        """Clear layer and reset bounding box."""
        self.chars.fill(SPACE)
        self.colors.fill(0)
        self._bbox = None

    def put(self, x: int, y: int, char: str, color: int = 7):
        """Put a single character at position."""
        if 0 <= x < self.width and 0 <= y < self.height:
            self.chars[y, x] = ord(char)
            self.colors[y, x] = color
            self._expand_bbox(x, y)

    def put_text(self, x: int, y: int, text: str, color: int = 7):
        """Put a string horizontally (convenience method)."""
        if not text or y < 0 or y >= self.height:
            return
        # Convert to 1-row matrix and blit
        x1 = max(0, x)
        x2 = min(self.width, x + len(text))
        if x1 >= x2:
            return
        start = x1 - x
        end = x2 - x
        row = np.array([[ord(c) for c in text[start:end]]], dtype=np.uint32)
        self.blit(x1, y, row, color)

    def blit(self, x: int, y: int, char_matrix: np.ndarray, color: int | np.ndarray = 7):
        """
        Blit a 2D character matrix to the layer at position.

        Args:
            x, y: Top-left position
            char_matrix: 2D numpy array of uint32 char codes (shape: height, width)
            color: Single color int or 2D array matching char_matrix shape
        """
        src_h, src_w = char_matrix.shape

        # Calculate clipped regions
        src_x1 = max(0, -x)
        src_y1 = max(0, -y)
        src_x2 = min(src_w, self.width - x)
        src_y2 = min(src_h, self.height - y)

        dst_x1 = max(0, x)
        dst_y1 = max(0, y)
        dst_x2 = dst_x1 + (src_x2 - src_x1)
        dst_y2 = dst_y1 + (src_y2 - src_y1)

        if dst_x1 >= dst_x2 or dst_y1 >= dst_y2:
            return  # Completely off-screen

        # Blit characters
        self.chars[dst_y1:dst_y2, dst_x1:dst_x2] = char_matrix[src_y1:src_y2, src_x1:src_x2]

        # Blit colors
        if isinstance(color, np.ndarray):
            self.colors[dst_y1:dst_y2, dst_x1:dst_x2] = color[src_y1:src_y2, src_x1:src_x2]
        else:
            self.colors[dst_y1:dst_y2, dst_x1:dst_x2] = color

        # Update bbox
        self._expand_bbox_rect(dst_x1, dst_y1, dst_x2 - dst_x1, dst_y2 - dst_y1)

    def fill(self, x: int, y: int, w: int, h: int, char: str = ' ', color: int = 7):
        """Fill a rectangle."""
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(self.width, x + w), min(self.height, y + h)
        if x1 < x2 and y1 < y2:
            self.chars[y1:y2, x1:x2] = ord(char)
            self.colors[y1:y2, x1:x2] = color
            self._expand_bbox_rect(x1, y1, x2 - x1, y2 - y1)


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
        3. Each layer's bounding box region fully overwrites lower layers
        4. Return (chars, colors) arrays
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

            # Composite: entire bounding box overwrites (layer is opaque in its bbox)
            bbox = layer.bbox
            if bbox is not None:
                x1, y1, x2, y2 = bbox
                self.out_chars[y1:y2, x1:x2] = layer.chars[y1:y2, x1:x2]
                self.out_colors[y1:y2, x1:x2] = layer.colors[y1:y2, x1:x2]

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
