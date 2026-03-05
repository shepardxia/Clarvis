"""System sprites: current visual elements expressed through sprite patterns.

FaceCel, WeatherSandbox, CelestialCel, BarSprite, and build_default_scene()
produce the standard Clarvis visual output using the sprite/pattern system.
"""

from datetime import datetime

import numpy as np

from ..archetypes import WeatherArchetype
from ..archetypes.weather import BoundingBox
from ..colors import StatusColors
from ..elements.registry import ElementRegistry
from ..pipeline import Layer
from .cel import Cel
from .control import Control
from .core import SPACE, BBox, Sprite
from .reel import Reel, ReelMode
from .scenes import SceneManager

# Priority constants for sprite compositing order
WEATHER = 0
CELESTIAL = 1
AVATAR = 50
BAR = 80
MIC = 92
TEXT = 95


class FaceCel(Cel):
    """Face animation sprite. Computes frame matrices from ElementRegistry directly."""

    WIDTH = 11
    HEIGHT = 5
    DEFAULT_CORNERS = ("╭", "╮", "╰", "╯")
    CORNER_PRESETS = {
        "round": ("╭", "╮", "╰", "╯"),
        "light": ("┌", "┐", "└", "┘"),
        "heavy": ("┏", "┓", "┗", "┛"),
        "double": ("╔", "╗", "╚", "╝"),
    }
    EDGE_V = ord("│")

    def __init__(self, registry: ElementRegistry, x: int, y: int, priority: int = AVATAR):
        self._registry = registry
        self._eyes = registry.get_all("eyes")
        self._mouths = registry.get_all("mouths")
        self._borders = registry.get_all("borders")
        self._substrates = registry.get_all("substrates")

        animations = self._prewarm_all(registry)
        super().__init__(
            animations=animations,
            default_animation="idle",
            x=x,
            y=y,
            width=self.WIDTH,
            height=self.HEIGHT,
            priority=priority,
            transparent=False,
        )

    def _prewarm_all(self, registry: ElementRegistry) -> dict[str, list[np.ndarray]]:
        """Pre-compute frame matrices for all animation statuses."""
        cache: dict[str, list[np.ndarray]] = {}
        for name in registry.list_names("animations"):
            if name.startswith("_"):
                continue
            anim = registry.get("animations", name)
            frames = anim.get("frames", []) if anim else [{"eyes": "normal", "mouth": "neutral"}]
            cache[name] = [self._compute_frame(f, name) for f in frames]
        return cache

    def _elem(self, registry: dict, name: str, field: str, fallback):
        return registry.get(name, {}).get(field, fallback)

    def _resolve_char(self, value: str, registry: dict, field: str, fallback: str) -> str:
        if not value:
            return fallback
        if len(value) == 1:
            return value
        result = self._elem(registry, value, field, fallback)
        return result if result else fallback

    def _get_corners(self, frame: dict) -> tuple[int, ...]:
        corners_spec = frame.get("corners")
        if corners_spec is None:
            corners = self.DEFAULT_CORNERS
        elif isinstance(corners_spec, str):
            corners = self.CORNER_PRESETS.get(corners_spec, self.DEFAULT_CORNERS)
        elif isinstance(corners_spec, (list, tuple)) and len(corners_spec) == 4:
            corners = tuple(corners_spec)
        else:
            corners = self.DEFAULT_CORNERS
        return tuple(ord(c) for c in corners)

    def _compute_frame(self, frame: dict, status: str) -> np.ndarray:
        """Build an 11×5 uint32 matrix from a frame dict."""
        m = np.full((self.HEIGHT, self.WIDTH), SPACE, dtype=np.uint32)

        # Eyes
        eyes_name = frame.get("eyes", "normal")
        if eyes_name == "looking_l":
            eyes_name = "looking_left"
        elif eyes_name == "looking_r":
            eyes_name = "looking_right"
        eye_char = self._resolve_char(eyes_name, self._eyes, "char", "o")
        eye_code = ord(eye_char)
        if len(eyes_name) == 1:
            left, gap, right = 3, 1, 3
        else:
            left, gap, right = tuple(self._elem(self._eyes, eyes_name, "position", [3, 1, 3]))

        # Mouth
        mouth_name = frame.get("mouth", "neutral")
        mouth_code = ord(self._resolve_char(mouth_name, self._mouths, "char", "~"))

        # Border
        border_spec = frame.get("border", status)
        border_code = ord(self._resolve_char(border_spec, self._borders, "char", "-"))

        # Corners
        corner_tl, corner_tr, corner_bl, corner_br = self._get_corners(frame)

        # Substrate
        substrate = self._elem(self._substrates, status, "pattern", " .  .  . ")

        # Row 0: top border
        m[0, 0] = corner_tl
        m[0, 1:10] = border_code
        m[0, 10] = corner_tr
        # Row 1: eyes
        m[1, 0] = self.EDGE_V
        m[1, 1:10] = SPACE
        m[1, 1 + left] = eye_code
        m[1, 1 + left + 1 + gap] = eye_code
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

    def set_status(self, status: str) -> None:
        """Switch face animation to match status."""
        if status == self._current_animation:
            return
        # Lazily compute frames for unknown statuses
        if status not in self._animations:
            anim = self._registry.get("animations", status)
            frames = anim.get("frames", []) if anim else [{"eyes": "normal", "mouth": "neutral"}]
            self._animations[status] = [self._compute_frame(f, status) for f in frames]
        if status in self._animations:
            self.set_animation(status)

    def tick(self, **ctx) -> None:
        status = ctx.get("status")
        if status:
            self.set_status(status)
        super().tick(**ctx)


class WeatherSandbox(Sprite):
    """Weather as a Sprite. WeatherArchetype provides the particle engine.

    Delegates to the archetype for tick/render but bridges between
    the Layer-based archetype API and the sprite's numpy arrays.
    """

    def __init__(
        self,
        registry: ElementRegistry,
        width: int,
        height: int,
        priority: int = WEATHER,
    ):
        super().__init__(priority=priority, transparent=False)
        self._width = width
        self._height = height
        self._archetype = WeatherArchetype(registry, width, height)
        self._archetype.prewarm_shapes()
        # Scratch layer for bridging archetype render → numpy
        self._layer = Layer("weather_scratch", 0, width, height, transparent=True)
        self._scene_registry = None  # Set by build_default_scene

    @property
    def bbox(self) -> BBox:
        return BBox(0, 0, self._width, self._height)

    def set_weather(self, weather_type: str, intensity: float = 0.6, wind_speed: float = 0.0):
        self._archetype.set_weather(weather_type, intensity, wind_speed)

    def tick(self, **ctx) -> None:
        weather_type = ctx.get("weather_type")
        if weather_type is not None:
            intensity = ctx.get("weather_intensity", 0.6)
            wind_speed = ctx.get("wind_speed", 0.0)
            self.set_weather(weather_type, intensity, wind_speed)
        self._archetype.tick()

    def render(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None:
        # Build exclusion zones from face sprites in the registry
        exclusion_zones = []
        if self._scene_registry:
            for s in self._scene_registry.alive():
                if isinstance(s, FaceCel):
                    b = s.bbox
                    exclusion_zones.append(BoundingBox(x=b.x, y=b.y, w=b.w, h=b.h))
        self._archetype.set_exclusion_zones(exclusion_zones)

        # Render into scratch layer, then copy to output
        self._layer.clear()
        self._archetype.render(self._layer, color=15)

        # Copy scratch layer content to output arrays
        bbox = self._layer.bbox
        if bbox is not None:
            x1, y1, x2, y2 = bbox
            region = self._layer.chars[y1:y2, x1:x2]
            mask = region != SPACE
            out_chars[y1:y2, x1:x2] = np.where(mask, region, out_chars[y1:y2, x1:x2])
            out_colors[y1:y2, x1:x2] = np.where(
                mask,
                self._layer.colors[y1:y2, x1:x2],
                out_colors[y1:y2, x1:x2],
            )


class CelestialCel(Sprite):
    """Sun/moon ASCII art positioned by hour. A simple sprite, not a full Cel."""

    SUN_ART = ["\\|/", "-o-", "/|\\"]
    MOON_ART = [" _ ", "(')", " ~ "]
    CELESTIAL_WIDTH = 3
    CELESTIAL_HEIGHT = 3
    CELESTIAL_MARGIN = 1
    DAY_START_HOUR = 6
    DAY_END_HOUR = 20
    SUN_COLOR = 220
    MOON_COLOR = 15

    def __init__(
        self,
        grid_width: int,
        grid_height: int,
        avatar_y: int,
        priority: int = CELESTIAL,
    ):
        super().__init__(priority=priority, transparent=True)
        self._grid_width = grid_width
        self._grid_height = grid_height
        self._avatar_y = avatar_y
        self._hour: int | None = None
        # Current computed position and art
        self._x = 0
        self._y = 0
        self._art: list[str] = []
        self._color = 0

    @property
    def bbox(self) -> BBox:
        return BBox(0, 0, self._grid_width, self.CELESTIAL_HEIGHT)

    def tick(self, **ctx) -> None:
        self._hour = ctx.get("hour")

    def render(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None:
        # Only render if there's room above avatar
        if self._avatar_y < self.CELESTIAL_HEIGHT + 1:
            return

        hour = self._hour if self._hour is not None else datetime.now().hour
        available_width = self._grid_width - 2 * self.CELESTIAL_MARGIN - self.CELESTIAL_WIDTH

        if self.DAY_START_HOUR <= hour < self.DAY_END_HOUR:
            art = self.SUN_ART
            day_hours = self.DAY_END_HOUR - self.DAY_START_HOUR
            progress = (hour - self.DAY_START_HOUR) / day_hours
            color = self.SUN_COLOR
        else:
            art = self.MOON_ART
            night_hours = 24 - (self.DAY_END_HOUR - self.DAY_START_HOUR)
            if hour >= self.DAY_END_HOUR:
                night_hour = hour - self.DAY_END_HOUR
            else:
                night_hour = hour + (24 - self.DAY_END_HOUR)
            progress = night_hour / night_hours
            color = self.MOON_COLOR

        x = self.CELESTIAL_MARGIN + int(progress * available_width)
        y = 0

        for i, line in enumerate(art):
            if y + i < self._grid_height:
                for j, ch in enumerate(line):
                    cx = x + j
                    if 0 <= cx < self._grid_width and ch != " ":
                        out_chars[y + i, cx] = ord(ch)
                        out_colors[y + i, cx] = color


class BarSprite(Sprite):
    """Progress bar. Renders directly to output arrays."""

    FILLED = ord("#")
    EMPTY = ord("-")
    EMPTY_COLOR = 8
    FILLED_COLOR = 15
    CACHE_SNAP_THRESHOLD = 0.5

    def __init__(
        self,
        x: int,
        y: int,
        width: int,
        priority: int = BAR,
    ):
        super().__init__(priority=priority, transparent=True)
        self._x = x
        self._y = y
        self._bar_width = width
        self._percent = 0.0
        # Percentage cache: int(percent) -> (chars_row, colors_row)
        self._cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self._prewarm()

    def _prewarm(self) -> None:
        for pct in range(101):
            self._cache_percent(pct)

    def _cache_percent(self, percent: int) -> tuple[np.ndarray, np.ndarray]:
        if percent in self._cache:
            return self._cache[percent]
        filled = int(percent / 100 * self._bar_width)
        chars = np.full(self._bar_width, self.EMPTY, dtype=np.uint32)
        chars[:filled] = self.FILLED
        colors = np.full(self._bar_width, self.EMPTY_COLOR, dtype=np.uint8)
        colors[:filled] = self.FILLED_COLOR
        self._cache[percent] = (chars, colors)
        return chars, colors

    @property
    def bbox(self) -> BBox:
        return BBox(self._x, self._y, self._bar_width, 1)

    def tick(self, **ctx) -> None:
        pct = ctx.get("context_percent")
        if pct is not None:
            self._percent = pct

    def render(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None:
        percent = max(0.0, min(100.0, float(self._percent)))
        int_pct = int(percent)
        empty_color = StatusColors.get("idle").ansi

        if int_pct == percent or abs(percent - int_pct) < self.CACHE_SNAP_THRESHOLD:
            chars, colors = self._cache_percent(int_pct)
            filled = int(int_pct / 100 * self._bar_width)
            out_chars[self._y, self._x : self._x + self._bar_width] = chars
            out_colors[self._y, self._x : self._x + self._bar_width] = colors
            # Override empty portion color with status color
            out_colors[self._y, self._x + filled : self._x + self._bar_width] = empty_color
        else:
            filled = int(percent / 100 * self._bar_width)
            out_chars[self._y, self._x : self._x + self._bar_width] = self.EMPTY
            out_chars[self._y, self._x : self._x + filled] = self.FILLED
            out_colors[self._y, self._x : self._x + self._bar_width] = empty_color
            out_colors[self._y, self._x : self._x + filled] = self.FILLED_COLOR


class VoiceReel(Reel):
    """Voice text overlay. Consumes voice_text/reveal_chars from tick context."""

    def tick(self, **ctx) -> None:
        voice_text = ctx.get("voice_text")
        if voice_text is not None:
            if voice_text != getattr(self, "_last_text", ""):
                self.set_content(voice_text)
                self._last_text = voice_text
            reveal = ctx.get("reveal_chars", len(voice_text))
            self.set_reveal_position(reveal)
        elif getattr(self, "_last_text", ""):
            self.set_content("")
            self._last_text = ""
        super().tick(**ctx)


class MicControl(Control):
    """Mic toggle. Consumes mic_visible/mic_enabled from tick context."""

    MIC_COLOR_OFF = 240

    def tick(self, **ctx) -> None:
        mic_visible = ctx.get("mic_visible")
        if mic_visible is not None:
            self.set_visible(mic_visible)
        mic_enabled = ctx.get("mic_enabled")
        if mic_enabled is not None:
            state = "enabled" if mic_enabled else "disabled"
            self.set_state(state)
            self.color = 0 if mic_enabled else self.MIC_COLOR_OFF
        super().tick(**ctx)


def _build_voice_reel(width: int, height: int) -> VoiceReel:
    """Voice text overlay as a VoiceReel in REVEAL mode."""
    text_x_margin = 2
    text_y_start = 1
    text_max_rows = 8
    text_width = width - 2 * text_x_margin
    return VoiceReel(
        x=text_x_margin,
        y=text_y_start,
        width=text_width,
        height=min(text_max_rows, height - text_y_start),
        priority=TEXT,
        mode=ReelMode.REVEAL,
        color=255,
        transparent=True,
    )


def _build_mic_control(
    bar_y: int,
    grid_width: int,
    mic_x_offset: int = 0,
    mic_y_offset: int = 0,
    style: str = "bracket",
) -> MicControl:
    """Mic toggle as a MicControl sprite."""
    icons = {
        "bracket": {"enabled": "[M]", "disabled": "[\u00b7]"},
        "dot": {"enabled": "\u25c9", "disabled": "\u25cb"},
    }
    style_icons = icons.get(style, icons["bracket"])
    icon_w = max(len(v) for v in style_icons.values())
    row = bar_y + 2 + mic_y_offset
    col = grid_width - icon_w + mic_x_offset
    return MicControl(
        x=col,
        y=row,
        priority=MIC,
        labels=style_icons,
        action_id="mic_toggle",
        state="disabled",
        visible=False,
        color=240,
        transparent=True,
    )


def build_default_scene(
    width: int = 18,
    height: int = 10,
    avatar_x_offset: int = 0,
    avatar_y_offset: int = 0,
    bar_x_offset: int = 0,
    bar_y_offset: int = 0,
    mic_x_offset: int = 0,
    mic_y_offset: int = 0,
    mic_style: str = "bracket",
) -> SceneManager:
    """Factory that builds the standard Clarvis scene, returning a populated SceneManager."""
    scene = SceneManager(width, height)

    registry = ElementRegistry()
    registry.load_all()

    # Standard layout math
    avatar_w = FaceCel.WIDTH  # 11
    avatar_h = FaceCel.HEIGHT  # 5
    bar_gap = 1
    bar_padding = 4
    bar_width_ratio = 0.65

    total_content_h = avatar_h + bar_gap + 1
    content_start_y = (height - total_content_h) // 2
    avatar_x = (width - avatar_w) // 2 + avatar_x_offset
    avatar_y = content_start_y + avatar_y_offset
    bar_width = max(avatar_w, min(int(width * bar_width_ratio), width - bar_padding))
    bar_x = (width - bar_width) // 2 + bar_x_offset
    bar_y = content_start_y + avatar_h + bar_gap + bar_y_offset

    # Weather (full-screen, lowest priority)
    weather = WeatherSandbox(registry, width, height, priority=WEATHER)
    weather._scene_registry = scene.registry
    scene.add(weather)

    # Celestial (top of screen, just above weather)
    celestial = CelestialCel(width, height, avatar_y, priority=CELESTIAL)
    scene.add(celestial)

    # Face
    face = FaceCel(registry, avatar_x, avatar_y, priority=AVATAR)
    scene.add(face)

    # Bar
    bar = BarSprite(bar_x, bar_y, bar_width, priority=BAR)
    scene.add(bar)

    # Mic
    mic = _build_mic_control(bar_y, width, mic_x_offset, mic_y_offset, mic_style)
    scene.add(mic)

    # Voice text
    voice = _build_voice_reel(width, height)
    scene.add(voice)

    return scene
