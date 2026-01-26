"""
Face archetype - renders animated avatar faces.

Loads eye, mouth, border, substrate elements and animations from YAML.
Manages animation state and renders the composite face as a matrix.
"""

import numpy as np

from ..widget.pipeline import Layer, SPACE
from ..elements.registry import ElementRegistry
from .base import Archetype


class FaceArchetype(Archetype):
    """
    Renders animated avatar faces using elements from registry.

    Face structure (11 chars wide, 5 chars tall):
      Row 0:  ╭---------╮   (top border)
      Row 1:  │   o o   │   (eyes row)
      Row 2:  │    ~    │   (mouth row)
      Row 3:  │ . . . . │   (substrate)
      Row 4:  ╰---------╯   (bottom border)

    Renders as a 2D matrix, blitted to layer.
    """

    WIDTH = 11
    HEIGHT = 5

    # Character codes for box drawing
    CORNER_TL = ord('╭')
    CORNER_TR = ord('╮')
    CORNER_BL = ord('╰')
    CORNER_BR = ord('╯')
    EDGE_V = ord('│')

    def __init__(self, registry: ElementRegistry):
        super().__init__(registry, 'face')
        self.status = 'idle'
        self.frame_index = 0

        # Pre-allocate face matrix
        self._matrix = np.full((self.HEIGHT, self.WIDTH), SPACE, dtype=np.uint32)

        self._cache_elements()
        self._cache_animation()

    def _cache_elements(self) -> None:
        """Cache all element definitions for fast lookup."""
        self._eyes = {}
        self._mouths = {}
        self._borders = {}
        self._substrates = {}

        for name in self.registry.list_names('eyes'):
            elem = self.registry.get('eyes', name)
            if elem:
                self._eyes[name] = elem

        for name in self.registry.list_names('mouths'):
            elem = self.registry.get('mouths', name)
            if elem:
                self._mouths[name] = elem

        for name in self.registry.list_names('borders'):
            elem = self.registry.get('borders', name)
            if elem:
                self._borders[name] = elem

        for name in self.registry.list_names('substrates'):
            elem = self.registry.get('substrates', name)
            if elem:
                self._substrates[name] = elem

    def _cache_animation(self) -> None:
        """Cache current animation frames."""
        anim = self.registry.get('animations', self.status)
        if anim:
            self._frames = anim.get('frames', [])
        else:
            self._frames = [{'eyes': 'normal', 'mouth': 'neutral'}]

    def _on_element_change(self, kind: str, name: str) -> None:
        """Rebuild caches when relevant elements change."""
        if kind in ('eyes', 'mouths', 'borders', 'substrates'):
            self._cache_elements()
        elif kind == 'animations' and name == self.status:
            self._cache_animation()

    def set_status(self, status: str) -> None:
        """Set current status (triggers animation change)."""
        if status != self.status:
            self.status = status
            self.frame_index = 0
            self._cache_animation()

    def tick(self) -> None:
        """Advance to next animation frame."""
        if self._frames:
            self.frame_index = (self.frame_index + 1) % len(self._frames)

    def _get_eye_char(self, name: str) -> str:
        """Get eye character for given name."""
        elem = self._eyes.get(name, {})
        return elem.get('char', 'o')

    def _get_eye_position(self, name: str) -> tuple[int, int, int]:
        """Get eye position (left_pad, gap, right_pad) for given name."""
        elem = self._eyes.get(name, {})
        pos = elem.get('position', [3, 1, 3])
        return tuple(pos)

    def _get_mouth_char(self, name: str) -> str:
        """Get mouth character for given name."""
        elem = self._mouths.get(name, {})
        return elem.get('char', '~')

    def _get_border_char(self, status: str) -> str:
        """Get border character for given status."""
        elem = self._borders.get(status, {})
        return elem.get('char', '-')

    def _get_substrate_pattern(self, status: str) -> str:
        """Get substrate pattern for given status."""
        elem = self._substrates.get(status, {})
        return elem.get('pattern', ' .  .  . ')

    def render(self, layer: Layer, x: int = 0, y: int = 0, color: int = 0) -> None:
        """
        Render face to layer at position using matrix blit.
        """
        # Get current frame
        if self._frames:
            frame = self._frames[self.frame_index % len(self._frames)]
        else:
            frame = {'eyes': 'normal', 'mouth': 'neutral'}

        eyes_name = frame.get('eyes', 'normal')
        mouth_name = frame.get('mouth', 'neutral')

        # Map looking_l/looking_r to looking_left/looking_right
        if eyes_name == 'looking_l':
            eyes_name = 'looking_left'
        elif eyes_name == 'looking_r':
            eyes_name = 'looking_right'

        eye_code = ord(self._get_eye_char(eyes_name))
        l, g, r = self._get_eye_position(eyes_name)
        mouth_code = ord(self._get_mouth_char(mouth_name))
        border_code = ord(self._get_border_char(self.status))
        substrate = self._get_substrate_pattern(self.status)

        m = self._matrix

        # Row 0: top border ╭---------╮
        m[0, 0] = self.CORNER_TL
        m[0, 1:10] = border_code
        m[0, 10] = self.CORNER_TR

        # Row 1: eyes │   o o   │
        m[1, 0] = self.EDGE_V
        m[1, 1:10] = SPACE
        m[1, 1 + l] = eye_code
        m[1, 1 + l + 1 + g] = eye_code
        m[1, 10] = self.EDGE_V

        # Row 2: mouth │    ~    │
        m[2, 0] = self.EDGE_V
        m[2, 1:10] = SPACE
        m[2, 5] = mouth_code  # Center position
        m[2, 10] = self.EDGE_V

        # Row 3: substrate │ . . . . │
        m[3, 0] = self.EDGE_V
        for i, c in enumerate(substrate[:9]):
            m[3, 1 + i] = ord(c)
        m[3, 10] = self.EDGE_V

        # Row 4: bottom border ╰---------╯
        m[4, 0] = self.CORNER_BL
        m[4, 1:10] = border_code
        m[4, 10] = self.CORNER_BR

        # Blit to layer
        layer.blit(x, y, m, color)
