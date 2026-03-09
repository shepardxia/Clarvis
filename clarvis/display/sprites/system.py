"""System sprites: visual element classes for the Clarvis display.

FaceCel, WeatherSandbox, CelestialCel, BarSprite, VoiceReel, and MicControl
are constructed by SceneBuilder from .cv specs.
"""

import random
from datetime import datetime

import numpy as np

from ..colors import StatusColors
from ..elements.registry import ElementRegistry
from .cel import Cel
from .control import Control
from .core import SPACE, BBox, Sprite
from .reel import Reel
from .weather_physics import (
    Particle,
    Shape,
    compute_render_cells,
    spawn_particles,
    tick_physics_batch,
)

# Priority constants for sprite compositing order
WEATHER = 0
CELESTIAL = 1
AVATAR = 50
BAR = 80
MIC = 92
TEXT = 95


class FaceCel(Cel):
    """Face animation sprite built from CV spec dataclasses."""

    WIDTH = 11
    HEIGHT = 5

    @classmethod
    def from_specs(
        cls,
        template,
        palette,
        sequences: dict,
        x: int,
        y: int,
        width: int = 11,
        height: int = 5,
        priority: int = AVATAR,
    ) -> "FaceCel":
        """Construct a FaceCel from CV spec dataclasses."""
        instance = object.__new__(cls)

        # Build layout from template ratios
        iw = width - 2  # interior width (minus left/right edges)
        ih = height - 2  # interior height (minus top/bottom borders)
        layout = {
            "edge_v": ord(template.edge),
            "eyes_row": 1 + round(template.eyes_row * max(ih - 1, 0)),
            "eyes_cols": [1 + round(c * max(iw - 1, 0)) for c in template.eyes_cols],
            "mouth_row": 1 + round(template.mouth_row * max(ih - 1, 0)),
            "mouth_col": 1 + round(template.mouth_col * max(iw - 1, 0)),
            "substrate_row": 1 + round(template.substrate_row * max(ih - 1, 0)),
        }

        # Resolve corners
        corner_names = palette.corners.get(
            template.default_corners, list(palette.corners.values())[0] if palette.corners else ["╭", "╮", "╰", "╯"]
        )

        # Resolve default substrate
        if template.default_substrate:
            default_sub = palette.substrates.get(template.default_substrate, " " * iw)
        else:
            default_sub = " " * iw

        def _resolve_preset(preset):
            """Resolve a PresetSpec to a frame dict with char codes."""
            eyes_name = preset.eyes or "open"
            mouth_name = preset.mouth or "neutral"
            border_name = preset.border or "thin"

            eye_char = palette.eyes.get(eyes_name, eyes_name if len(eyes_name) == 1 else "o")
            mouth_char = palette.mouths.get(mouth_name, mouth_name if len(mouth_name) == 1 else "~")
            border_char = palette.borders.get(border_name, border_name if len(border_name) == 1 else "-")

            # Corners override
            if preset.corners and preset.corners in palette.corners:
                cn = palette.corners[preset.corners]
            else:
                cn = corner_names

            # Substrate
            sub_name = preset.substrate
            substrate = palette.substrates.get(sub_name, " " * iw) if sub_name else default_sub

            return eye_char, mouth_char, border_char, cn, substrate

        def _build_frame(eye_char, mouth_char, border_char, corners, substrate):
            """Build a width×height uint32 matrix from resolved chars."""
            m = np.full((height, width), SPACE, dtype=np.uint32)
            bc = ord(border_char)
            tl, tr, bl, br = (ord(c) for c in corners)
            ev = layout["edge_v"]

            # Top border
            m[0, 0] = tl
            m[0, 1 : width - 1] = bc
            m[0, width - 1] = tr
            # Bottom border
            m[height - 1, 0] = bl
            m[height - 1, 1 : width - 1] = bc
            m[height - 1, width - 1] = br
            # Side edges for interior rows
            for r in range(1, height - 1):
                m[r, 0] = ev
                m[r, width - 1] = ev

            # Eyes
            er = layout["eyes_row"]
            if 0 < er < height - 1:
                ec = ord(eye_char)
                for col in layout["eyes_cols"]:
                    if 0 < col < width - 1:
                        m[er, col] = ec

            # Mouth
            mr = layout["mouth_row"]
            if 0 < mr < height - 1:
                mc_col = layout["mouth_col"]
                if 0 < mc_col < width - 1:
                    m[mr, mc_col] = ord(mouth_char)

            # Substrate
            sr = layout["substrate_row"]
            if 0 < sr < height - 1:
                for i, c in enumerate(substrate[:iw]):
                    if 1 + i < width - 1:
                        m[sr, 1 + i] = ord(c)

            return m

        def _resolve_frame_ref(ref):
            """Resolve a FrameRef to (eye_char, mouth_char, border_char, corners, substrate)."""
            if ref.preset:
                preset = palette.presets.get(ref.preset)
                if preset:
                    return _resolve_preset(preset)
            if ref.inline:
                return _resolve_preset(ref.inline)
            # Fallback
            return "o", "~", "-", corner_names, " " * iw

        # Build animations dict
        animations: dict[str, list[np.ndarray]] = {}
        for seq_name, seq in sequences.items():
            frames = []
            for fref in seq.frames:
                if fref.define_ref and fref.define_ref in seq.defines:
                    for sub_ref in seq.defines[fref.define_ref]:
                        parts = _resolve_frame_ref(sub_ref)
                        frames.append(_build_frame(*parts))
                else:
                    parts = _resolve_frame_ref(fref)
                    frames.append(_build_frame(*parts))
            if not frames:
                frames = [_build_frame("o", "~", "-", corner_names, " " * iw)]
            animations[seq_name] = frames

        # Initialize Cel base
        Cel.__init__(
            instance,
            animations=animations,
            default_animation=next(iter(animations)),
            x=x,
            y=y,
            width=width,
            height=height,
            priority=priority,
            transparent=False,
        )
        instance._palette = palette
        instance._template_layout = layout
        return instance

    def set_status(self, status: str) -> None:
        """Switch face animation to match status."""
        if status == self._current_animation:
            return
        if status in self._animations:
            self.set_animation(status)

    def tick(self, **ctx) -> None:
        status = ctx.get("status")
        if status:
            self.set_status(status)
        super().tick(**ctx)


class WeatherSandbox(Sprite):
    """Weather particle simulation sprite. Renders directly to output arrays."""

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
        self._registry = registry
        self._scene_registry = None  # Set by SceneBuilder

        # Load physics config from elements/archetypes/weather.yaml
        config = registry.get("archetypes", "weather") or {}
        physics = config.get("physics", {})
        self._death_prob = physics.get("death_prob", 0.08)
        self._max_particles_base = physics.get("max_particles_base", 40)
        self._speed_multiplier = physics.get("speed_multiplier", 2.0)
        self._batch_size = physics.get("batch_size", 128)

        ambient = config.get("ambient", {})
        self._ambient_shapes = ambient.get("shapes", ["cloud_small", "cloud_wisp", "cloud_puff"])
        self._ambient_max_clouds = ambient.get("max_clouds", 3)
        self._ambient_spawn_rate = ambient.get("spawn_rate", 0.03)
        self._ambient_spawn_zone = ambient.get("spawn_zone", 0.35)

        # Weather state
        self._weather_type: str | None = None
        self._intensity = 0.0
        self._wind_speed = 0.0

        # Particle SoA arrays
        n = self._batch_size
        self._p_x = np.zeros(n, dtype=np.float64)
        self._p_y = np.zeros(n, dtype=np.float64)
        self._p_vx = np.zeros(n, dtype=np.float64)
        self._p_vy = np.zeros(n, dtype=np.float64)
        self._p_age = np.zeros(n, dtype=np.int64)
        self._p_lifetime = np.zeros(n, dtype=np.int64)
        self._p_shape_idx = np.zeros(n, dtype=np.int64)
        self._p_count = 0

        # Ambient clouds
        self._ambient_clouds: list[Particle] = []

        # Cached blocked cells from face sprites (rebuilt when face bbox changes)
        self._blocked: set[tuple[int, int]] = set()
        self._blocked_bbox: tuple[int, int, int, int] | None = None

        # Shape cache
        self._shape_cache: list[Shape] = []
        self._shape_offsets: np.ndarray | None = None
        self._shape_cell_counts: np.ndarray | None = None
        self._shape_chars: list[list[str]] = []
        self._render_out_x: np.ndarray = np.zeros(0, dtype=np.int32)
        self._render_out_y: np.ndarray = np.zeros(0, dtype=np.int32)
        self._render_out_shape: np.ndarray = np.zeros(0, dtype=np.int32)
        self._render_out_cell: np.ndarray = np.zeros(0, dtype=np.int32)

    @property
    def bbox(self) -> BBox:
        return BBox(0, 0, self._width, self._height)

    def _get_shape(self, name: str) -> Shape | None:
        elem = self._registry.get("particles", name)
        if not elem:
            return None
        return Shape.parse(elem.get("pattern", ""))

    def _rebuild_shape_cache(self) -> None:
        self._shape_cache = []
        if not self._weather_type:
            self._shape_offsets = None
            return
        weather_def = self._registry.get("weather", self._weather_type)
        if not weather_def:
            self._shape_offsets = None
            return
        for name in weather_def.get("particles", []):
            shape = self._get_shape(name)
            if shape:
                self._shape_cache.append(shape)
        if not self._shape_cache:
            self._shape_offsets = None
            return
        self._build_shape_arrays()

    def _build_shape_arrays(self) -> None:
        num_shapes = len(self._shape_cache)
        max_cells = 0
        shape_cells = []
        for shape in self._shape_cache:
            cells = []
            for row_idx, row in enumerate(shape.pattern):
                for col_idx, char in enumerate(row):
                    if char != " ":
                        cells.append((col_idx, row_idx, char))
            shape_cells.append(cells)
            max_cells = max(max_cells, len(cells))

        self._shape_offsets = np.zeros((num_shapes, max_cells, 2), dtype=np.int32)
        self._shape_cell_counts = np.zeros(num_shapes, dtype=np.int32)
        self._shape_chars = []
        for i, cells in enumerate(shape_cells):
            self._shape_cell_counts[i] = len(cells)
            chars = []
            for j, (dx, dy, char) in enumerate(cells):
                self._shape_offsets[i, j, 0] = dx
                self._shape_offsets[i, j, 1] = dy
                chars.append(char)
            self._shape_chars.append(chars)

        max_output = self._batch_size * max_cells
        self._render_out_x = np.zeros(max_output, dtype=np.int32)
        self._render_out_y = np.zeros(max_output, dtype=np.int32)
        self._render_out_shape = np.zeros(max_output, dtype=np.int32)
        self._render_out_cell = np.zeros(max_output, dtype=np.int32)

    def _grow_arrays(self) -> None:
        old_size = len(self._p_x)
        new_size = old_size * 2
        for attr in ("_p_x", "_p_y", "_p_vx", "_p_vy"):
            old = getattr(self, attr)
            new = np.zeros(new_size, dtype=np.float64)
            new[:old_size] = old
            setattr(self, attr, new)
        for attr in ("_p_age", "_p_lifetime", "_p_shape_idx"):
            old = getattr(self, attr)
            new = np.zeros(new_size, dtype=np.int64)
            new[:old_size] = old
            setattr(self, attr, new)

    def set_weather(self, weather_type: str, intensity: float = 0.6, wind_speed: float = 0.0):
        if weather_type != self._weather_type:
            self._weather_type = weather_type
            self._p_count = 0
            self._rebuild_shape_cache()
        self._intensity = intensity
        self._wind_speed = wind_speed

    def tick(self, **ctx) -> None:
        weather_type = ctx.get("weather_type")
        if weather_type is not None:
            intensity = ctx.get("weather_intensity", 0.6)
            wind_speed = ctx.get("wind_speed", 0.0)
            self.set_weather(weather_type, intensity, wind_speed)

        self._tick_ambient_clouds()

        if not self._weather_type or not self._shape_cache:
            return

        if self._p_count > 0:
            self._p_count = tick_physics_batch(
                self._p_x,
                self._p_y,
                self._p_vx,
                self._p_vy,
                self._p_age,
                self._p_lifetime,
                self._p_shape_idx,
                self._p_count,
                1,
                float(self._width),
                float(self._height),
                self._death_prob,
            )

        max_particles = int(self._intensity * self._max_particles_base)
        spawn_rate = self._intensity * 2.0
        spawn_count = min(np.random.poisson(spawn_rate * 3), max_particles - self._p_count)
        if spawn_count > 0:
            self._spawn_batch(spawn_count)

    def _tick_ambient_clouds(self) -> None:
        alive = []
        for p in self._ambient_clouds:
            p.x += p.vx
            p.y += p.vy
            if (
                p.x < self._width + 1
                and p.x + p.shape.width > -1
                and p.y < self._height + 1
                and p.y + p.shape.height > -1
            ):
                alive.append(p)
        self._ambient_clouds = alive

        if self._weather_type and self._weather_type not in ("clear", None):
            return

        if len(self._ambient_clouds) < self._ambient_max_clouds and random.random() < self._ambient_spawn_rate:
            shape_name = random.choice(self._ambient_shapes)
            shape = self._get_shape(shape_name)
            if shape:
                s = self._speed_multiplier
                self._ambient_clouds.append(
                    Particle(
                        x=random.uniform(-shape.width * 2, -shape.width),
                        y=random.uniform(0, int(self._height * self._ambient_spawn_zone)),
                        vx=random.uniform(0.25, 0.45) * s,
                        vy=random.uniform(-0.08, 0.08) * s,
                        shape=shape,
                        lifetime=999999,
                    )
                )

    def _spawn_batch(self, count: int) -> None:
        while self._p_count + count > len(self._p_x):
            self._grow_arrays()

        s = self._speed_multiplier
        w, h = float(self._width), float(self._height)

        if self._weather_type == "snow":
            wf = min(self._wind_speed / 30.0, 1.0)
            vx_var = (0.02 + wf * 0.03) * s
            params = (0, w, -2, 2, wf * 0.15 * s - vx_var, 2 * vx_var, 0.15 * s, 0.2 * s, 40, 60)
        elif self._weather_type == "rain":
            params = (0, w, -2, 2, -0.03 * s, 0.06 * s, 0.5 * s, 0.4 * s, 20, 30)
        elif self._weather_type == "windy":
            params = (-2, 2, 0, h, 0.4 * s, 0.4 * s, -0.1 * s, 0.2 * s, 30, 30)
        else:  # cloudy, fog
            params = (0, w, 0, h, -0.05 * s, 0.1 * s, -0.03 * s, 0.06 * s, 60, 90)

        spawn_particles(
            self._p_x,
            self._p_y,
            self._p_vx,
            self._p_vy,
            self._p_age,
            self._p_lifetime,
            self._p_shape_idx,
            self._p_count,
            count,
            len(self._shape_cache),
            *params,
        )
        self._p_count += count

    def _update_blocked(self) -> None:
        """Rebuild blocked-cell set only when face bbox changes."""
        if not self._scene_registry:
            return
        for s in self._scene_registry.alive():
            if isinstance(s, FaceCel):
                b = s.bbox
                key = (b.x, b.y, b.w, b.h)
                if key != self._blocked_bbox:
                    self._blocked = {(x, y) for y in range(b.y, b.y2) for x in range(b.x, b.x2)}
                    self._blocked_bbox = key
                return
        # No face sprite found
        if self._blocked:
            self._blocked = set()
            self._blocked_bbox = None

    def render(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None:
        self._update_blocked()
        blocked = self._blocked
        color = 15
        w, h = self._width, self._height

        # Render ambient clouds
        for p in self._ambient_clouds:
            px, py = int(p.x), int(p.y)
            for row_idx, row in enumerate(p.shape.pattern):
                for col_idx, char in enumerate(row):
                    if char == " ":
                        continue
                    cx, cy = px + col_idx, py + row_idx
                    if (cx, cy) in blocked:
                        continue
                    if 0 <= cx < w and 0 <= cy < h:
                        out_chars[cy, cx] = ord(char)
                        out_colors[cy, cx] = color

        # Render JIT particles
        n = self._p_count
        if n == 0 or self._shape_offsets is None:
            return

        max_cells = self._shape_offsets.shape[1]
        needed_size = n * max_cells
        if len(self._render_out_x) < needed_size:
            new_size = needed_size * 2
            self._render_out_x = np.zeros(new_size, dtype=np.int32)
            self._render_out_y = np.zeros(new_size, dtype=np.int32)
            self._render_out_shape = np.zeros(new_size, dtype=np.int32)
            self._render_out_cell = np.zeros(new_size, dtype=np.int32)

        num_cells = compute_render_cells(
            self._p_x,
            self._p_y,
            self._p_shape_idx,
            n,
            self._shape_offsets,
            self._shape_cell_counts,
            self._render_out_x,
            self._render_out_y,
            self._render_out_shape,
            self._render_out_cell,
        )

        xs = self._render_out_x[:num_cells].tolist()
        ys = self._render_out_y[:num_cells].tolist()
        shapes = self._render_out_shape[:num_cells].tolist()
        cells = self._render_out_cell[:num_cells].tolist()

        for cx, cy, shape_idx, cell_idx in zip(xs, ys, shapes, cells):
            if (cx, cy) not in blocked and 0 <= cx < w and 0 <= cy < h:
                out_chars[cy, cx] = ord(self._shape_chars[shape_idx][cell_idx])
                out_colors[cy, cx] = color


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
            out_colors[self._y, self._x : self._x + filled] = colors[:filled]
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
