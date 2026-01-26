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

    Animation frames can specify per-frame overrides:
      - eyes: eye element name OR direct character
      - mouth: mouth element name OR direct character
      - border: border element name OR direct character
      - corners: [TL, TR, BL, BR] characters
    """

    WIDTH = 11
    HEIGHT = 5

    # Default corner characters (can be overridden per-frame)
    DEFAULT_CORNERS = ('╭', '╮', '╰', '╯')

    # Corner presets for easy reference
    CORNER_PRESETS = {
        'round': ('╭', '╮', '╰', '╯'),
        'light': ('┌', '┐', '└', '┘'),
        'heavy': ('┏', '┓', '┗', '┛'),
        'double': ('╔', '╗', '╚', '╝'),
    }

    EDGE_V = ord('│')

    def __init__(self, registry: ElementRegistry):
        super().__init__(registry, 'face')
        self.status = 'idle'
        self.frame_index = 0

        # Pre-allocated face matrix (for fallback/on-the-fly computation)
        self._matrix = np.full((self.HEIGHT, self.WIDTH), SPACE, dtype=np.uint32)
        
        # State-based cache: status -> list of pre-computed frame matrices
        self._state_cache: dict[str, list[np.ndarray]] = {}
        
        # Current animation frames (reference to cached data)
        self._frames: list[dict] = []
        self._precomputed: list[np.ndarray] = []

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
        """Cache current animation frames and pre-compute matrices.
        
        Uses state-based caching: matrices are computed once per status
        and reused on subsequent status switches.
        """
        # Check if already cached for this status
        if self.status in self._state_cache:
            anim = self.registry.get('animations', self.status)
            self._frames = anim.get('frames', []) if anim else [{'eyes': 'normal', 'mouth': 'neutral'}]
            self._precomputed = self._state_cache[self.status]
            return
        
        # Not cached - compute and store
        anim = self.registry.get('animations', self.status)
        if anim:
            self._frames = anim.get('frames', [])
        else:
            self._frames = [{'eyes': 'normal', 'mouth': 'neutral'}]
        
        # Pre-compute all frame matrices for fast rendering
        self._precomputed = []
        for frame in self._frames:
            matrix = self._compute_frame_matrix(frame)
            self._precomputed.append(matrix)
        
        # Store in state cache
        self._state_cache[self.status] = self._precomputed

    def prewarm_cache(self) -> dict[str, int]:
        """Pre-compute and cache all animation states.
        
        Call at startup to avoid computation during runtime.
        Returns dict of status -> frame count.
        """
        original_status = self.status
        stats = {}
        
        # Get all animation names
        anim_names = self.registry.list_names('animations')
        
        for name in anim_names:
            if name.startswith('_'):
                continue  # Skip shorthands file
            self.status = name
            self._cache_animation()
            stats[name] = len(self._precomputed)
        
        # Restore original status
        self.status = original_status
        self._cache_animation()
        
        return stats

    def cache_stats(self) -> dict:
        """Return cache statistics for debugging."""
        total_frames = sum(len(frames) for frames in self._state_cache.values())
        total_bytes = sum(
            sum(m.nbytes for m in frames) 
            for frames in self._state_cache.values()
        )
        return {
            'cached_states': len(self._state_cache),
            'total_frames': total_frames,
            'memory_bytes': total_bytes,
            'memory_kb': total_bytes / 1024,
            'states': {k: len(v) for k, v in self._state_cache.items()}
        }

    def _on_element_change(self, kind: str, name: str) -> None:
        """Rebuild caches when relevant elements change."""
        if kind in ('eyes', 'mouths', 'borders', 'substrates'):
            self._cache_elements()
            # Element changes affect all cached states
            self._state_cache.clear()
            self._cache_animation()
        elif kind == 'animations':
            # Invalidate specific animation cache
            if name in self._state_cache:
                del self._state_cache[name]
            # Rebuild current animation if affected
            if name == self.status:
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

    def _resolve_char(self, value: str, getter_fn, fallback: str) -> str:
        """Resolve a value to a character.

        If value is a single character, use it directly.
        If value is a name, look it up via getter_fn.
        If lookup fails, use fallback.
        """
        if not value:
            return fallback
        # Single character = direct use
        if len(value) == 1:
            return value
        # Otherwise treat as element name
        result = getter_fn(value)
        return result if result else fallback

    def _get_corners(self, frame: dict) -> tuple[int, int, int, int]:
        """Get corner characters for current frame.

        Supports:
        - corners: [TL, TR, BL, BR] list of characters
        - corners: "preset_name" (e.g., "round", "heavy", "double")
        - Falls back to DEFAULT_CORNERS if not specified
        """
        corners_spec = frame.get('corners')
        if corners_spec is None:
            corners = self.DEFAULT_CORNERS
        elif isinstance(corners_spec, str):
            # Preset name
            corners = self.CORNER_PRESETS.get(corners_spec, self.DEFAULT_CORNERS)
        elif isinstance(corners_spec, (list, tuple)) and len(corners_spec) == 4:
            corners = tuple(corners_spec)
        else:
            corners = self.DEFAULT_CORNERS

        return tuple(ord(c) for c in corners)


    def _compute_frame_matrix(self, frame: dict) -> np.ndarray:
        """Pre-compute a frame as a numpy matrix of character ordinals."""
        m = np.full((self.HEIGHT, self.WIDTH), SPACE, dtype=np.uint32)
        
        # === Eyes ===
        eyes_name = frame.get('eyes', 'normal')
        if eyes_name == 'looking_l':
            eyes_name = 'looking_left'
        elif eyes_name == 'looking_r':
            eyes_name = 'looking_right'
        
        eye_char = self._resolve_char(eyes_name, self._get_eye_char, 'o')
        eye_code = ord(eye_char)
        if len(eyes_name) == 1:
            l, g, r = 3, 1, 3
        else:
            l, g, r = self._get_eye_position(eyes_name)
        
        # === Mouth ===
        mouth_name = frame.get('mouth', 'neutral')
        mouth_char = self._resolve_char(mouth_name, self._get_mouth_char, '~')
        mouth_code = ord(mouth_char)
        
        # === Border ===
        border_spec = frame.get('border', self.status)
        border_char = self._resolve_char(border_spec, self._get_border_char, '-')
        border_code = ord(border_char)
        
        # === Corners ===
        corner_tl, corner_tr, corner_bl, corner_br = self._get_corners(frame)
        
        # === Substrate ===
        substrate = self._get_substrate_pattern(self.status)
        
        # Row 0: top border
        m[0, 0] = corner_tl
        m[0, 1:10] = border_code
        m[0, 10] = corner_tr
        
        # Row 1: eyes
        m[1, 0] = self.EDGE_V
        m[1, 1:10] = SPACE
        m[1, 1 + l] = eye_code
        m[1, 1 + l + 1 + g] = eye_code
        m[1, 10] = self.EDGE_V
        
        # Row 2: mouth
        m[2, 0] = self.EDGE_V
        m[2, 1:10] = SPACE
        m[2, 5] = mouth_code
        m[2, 10] = self.EDGE_V
        
        # Row 3: substrate
        m[3, 0] = self.EDGE_V
        for i, c in enumerate(substrate[:9]):
            m[3, 1 + i] = ord(c)
        m[3, 10] = self.EDGE_V
        
        # Row 4: bottom border
        m[4, 0] = corner_bl
        m[4, 1:10] = border_code
        m[4, 10] = corner_br
        
        return m

    def render(self, layer: Layer, x: int = 0, y: int = 0, color: int = 0) -> None:
        """
        Render face to layer at position using pre-computed matrix.
        
        Uses pre-computed frame matrices for efficiency.
        Animation frames support per-frame overrides (resolved at cache time):
        - eyes: element name OR direct character (e.g., "normal" or "◕")
        - mouth: element name OR direct character (e.g., "smile" or "◡")
        - border: element name OR direct character (e.g., "thinking" or "━")
        - corners: preset name, [TL,TR,BL,BR] list, or omit for default
        """
        # Use pre-computed matrix if available
        if self._precomputed:
            idx = self.frame_index % len(self._precomputed)
            layer.blit(x, y, self._precomputed[idx], color)
        else:
            # Fallback: compute on the fly (shouldn't happen normally)
            if self._frames:
                frame = self._frames[self.frame_index % len(self._frames)]
            else:
                frame = {'eyes': 'normal', 'mouth': 'neutral'}
            m = self._compute_frame_matrix(frame)
            layer.blit(x, y, m, color)
