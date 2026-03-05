"""System sprites: current visual elements expressed through sprite patterns.

FaceCel, WeatherSandbox, CelestialCel, BarSprite, and build_default_scene()
replicate FrameRenderer's visual output using the sprite/pattern system.
"""

from datetime import datetime

import numpy as np

from ..archetypes import FaceArchetype, ProgressArchetype, WeatherArchetype
from ..archetypes.weather import BoundingBox
from ..colors import StatusColors
from ..elements.registry import ElementRegistry
from ..pipeline import SPACE, Layer
from .cel import Cel
from .control import Control
from .core import BBox, Sprite
from .reel import Reel, ReelMode
from .scenes import SceneManager

# Priority constants matching old LayerPriority
WEATHER = 0
CELESTIAL = 1
AVATAR = 50
BAR = 80
MIC = 92
TEXT = 95


class FaceCel(Cel):
    """Face expressed as a Cel. FaceArchetype produces frames; Cel cycles them."""

    def __init__(self, registry: ElementRegistry, x: int, y: int, priority: int = AVATAR):
        archetype = FaceArchetype(registry)
        archetype.prewarm_cache()
        # _state_cache: {status: [np.ndarray]} — IS the animations dict
        super().__init__(
            animations=archetype._state_cache,
            default_animation="idle",
            x=x,
            y=y,
            width=FaceArchetype.WIDTH,
            height=FaceArchetype.HEIGHT,
            priority=priority,
            transparent=False,
        )
        self._archetype = archetype

    def set_status(self, status: str) -> None:
        """Switch face animation to match status."""
        if status == self._current_animation:
            return
        # If status not cached yet, tell archetype to cache it
        if status not in self._animations:
            self._archetype.set_status(status)
            self._animations[status] = self._archetype._state_cache.get(status, [])
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
        super().__init__(priority=priority, transparent=True)
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
    MOON_ART = [" _ ", "(') ", " ~ "]
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
    """Progress bar. Simple Sprite wrapping ProgressArchetype."""

    def __init__(
        self,
        registry: ElementRegistry,
        x: int,
        y: int,
        width: int,
        priority: int = BAR,
    ):
        super().__init__(priority=priority, transparent=True)
        self._x = x
        self._y = y
        self._bar_width = width
        self._archetype = ProgressArchetype(registry, width)
        self._archetype.prewarm_cache()
        self._layer = Layer("bar_scratch", 0, width + x + 1, y + 2, transparent=True)
        self._percent = 0.0

    @property
    def bbox(self) -> BBox:
        return BBox(self._x, self._y, self._bar_width, 1)

    def tick(self, **ctx) -> None:
        pct = ctx.get("context_percent")
        if pct is not None:
            self._percent = pct

    def render(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None:
        self._layer.clear()
        self._archetype.render(
            self._layer,
            x=self._x,
            y=self._y,
            percent=self._percent,
            color=StatusColors.get("idle").ansi,
        )
        # Copy the bar row to output
        b = self.bbox
        out_chars[b.y, b.x : b.x2] = self._layer.chars[b.y, b.x : b.x2]
        out_colors[b.y, b.x : b.x2] = self._layer.colors[b.y, b.x : b.x2]


def _build_voice_reel(width: int, height: int) -> Reel:
    """Voice text overlay as a Reel in REVEAL mode."""
    text_x_margin = 2
    text_y_start = 1
    text_max_rows = 8
    text_width = width - 2 * text_x_margin
    return Reel(
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
) -> Control:
    """Mic toggle as a Control sprite."""
    icons = {
        "bracket": {"enabled": "[M]", "disabled": "[\u00b7]"},
        "dot": {"enabled": "\u25c9", "disabled": "\u25cb"},
    }
    style_icons = icons.get(style, icons["bracket"])
    icon_w = max(len(v) for v in style_icons.values())
    row = bar_y + 2 + mic_y_offset
    col = grid_width - icon_w + mic_x_offset
    return Control(
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
    """Factory that replicates FrameRenderer layout, returning a populated SceneManager."""
    scene = SceneManager(width, height)

    registry = ElementRegistry()
    registry.load_all()

    # Layout math from FrameRenderer.__init__
    avatar_w = FaceArchetype.WIDTH  # 11
    avatar_h = FaceArchetype.HEIGHT  # 5
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
    bar = BarSprite(registry, bar_x, bar_y, bar_width, priority=BAR)
    scene.add(bar)

    # Mic
    mic = _build_mic_control(bar_y, width, mic_x_offset, mic_y_offset, mic_style)
    scene.add(mic)

    # Voice text
    voice = _build_voice_reel(width, height)
    scene.add(voice)

    return scene
