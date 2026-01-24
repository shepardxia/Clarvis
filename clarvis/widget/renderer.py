"""
Widget frame renderer - generates complete ASCII frames for display.

Uses the layered RenderPipeline for compositing:
- Layer 0: Weather particles (transparent)
- Layer 50: Avatar face (overwrites)
- Layer 80: Progress bar (transparent)
"""

import random
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import numpy as np
from numba import njit, prange

from .pipeline import RenderPipeline, Layer
from ..core.colors import ANSI_COLORS as COLORS, get_status_ansi


# =============================================================================
# Animation Keyframes - Maps status to (eyes, mouth) sequences
# =============================================================================

ANIMATION_KEYFRAMES = {
    "idle": [
        ("dots", "neutral"),
        ("dots", "neutral"),
        ("normal", "neutral"),
        ("dots", "neutral"),
    ],
    "resting": [
        ("sleepy", "flat"),
        ("closed", "flat"),
        ("sleepy", "flat"),
        ("closed", "flat"),
    ],
    "thinking": [
        ("looking_l", "think"),
        ("normal", "think"),
        ("looking_r", "think"),
        ("normal", "think"),
    ],
    "running": [
        ("wide", "smile"),
        ("normal", "smile"),
        ("wide", "open"),
        ("normal", "smile"),
    ],
    "executing": [
        ("wide", "open"),
        ("normal", "open"),
        ("wide", "smile"),
        ("normal", "open"),
    ],
    "awaiting": [
        ("normal", "dots"),
        ("looking_l", "dots"),
        ("normal", "dots"),
        ("looking_r", "dots"),
    ],
    "reading": [
        ("normal", "open"),
        ("looking_l", "open"),
        ("normal", "open"),
        ("looking_r", "open"),
    ],
    "writing": [
        ("normal", "think"),
        ("wide", "think"),
        ("normal", "flat"),
        ("wide", "think"),
    ],
    "reviewing": [
        ("looking_l", "think"),
        ("normal", "think"),
        ("looking_r", "think"),
        ("normal", "think"),
    ],
    "offline": [
        ("closed", "flat"),
        ("closed", "flat"),
    ],
}

DEFAULT_KEYFRAMES = [("normal", "neutral"), ("normal", "neutral")]


# =============================================================================
# Face Parts
# =============================================================================

EYES = {
    "normal": "o",
    "dots": ".",
    "closed": "-",
    "wide": "O",
    "sleepy": "_",
    "looking_l": "o",
    "looking_r": "o",
}

EYE_POSITIONS = {
    "normal": (3, 1, 3),
    "dots": (3, 1, 3),
    "closed": (3, 1, 3),
    "wide": (3, 1, 3),
    "sleepy": (3, 1, 3),
    "looking_l": (2, 1, 4),
    "looking_r": (4, 1, 2),
}

MOUTHS = {
    "neutral": "~",
    "smile": "u",
    "open": "o",
    "flat": "-",
    "dots": ".",
    "think": "~",
}

BORDERS = {
    "idle": "-",
    "resting": "-",
    "thinking": "~",
    "running": "=",
    "executing": "=",
    "awaiting": ".",
    "reading": ".",
    "writing": "-",
    "reviewing": "~",
    "offline": ".",
}

SUBSTRATES = {
    "idle": " .  .  . ",
    "resting": " .  .  . ",
    "thinking": " * . * . ",
    "running": " * o * o ",
    "executing": " > > > > ",
    "awaiting": " . . . . ",
    "reading": " > . . . ",
    "writing": " # # # # ",
    "reviewing": " * . * . ",
    "offline": "   . .   ",
}


# =============================================================================
# Weather Shapes
# =============================================================================

@dataclass
class Shape:
    """Multi-character pattern for weather particles."""
    pattern: tuple[str, ...]  # Immutable for hashability
    width: int
    height: int

    @classmethod
    def parse(cls, text: str) -> "Shape":
        """Parse text into a shape. Each line becomes a row.

        Use \\n to separate rows in multi-line shapes.
        Example: " ~ \\n~~~" renders as:
           ~
          ~~~
        """
        if not text:
            raise ValueError("Shape text cannot be empty")
        pattern = tuple(text.split("\n"))
        height = len(pattern)
        width = max(len(line) for line in pattern)
        return cls(pattern=pattern, width=width, height=height)


# Shape library - define shapes as text, parsed on demand
SHAPE_LIBRARY = {
    # Snow particles (1x1)
    "snow_star": "*",
    "snow_plus": "+",
    "snow_x": "x",
    "snow_dot": ".",
    "snow_o": "o",
    # Rain particles (1x1)
    "rain_drop": "|",
    "rain_bang": "!",
    "rain_colon": ":",
    "rain_tick": "'",
    "rain_comma": ",",
    # Wind particles (1x1)
    "wind_tilde": "~",
    "wind_dash": "-",
    "wind_tick": "'",
    "wind_back": "`",
    "wind_arrow": ">",
    "wind_paren": ")",
    "wind_slash": "/",
    # Fog/cloud single chars
    "fog_dot": ".",
    "fog_tilde": "~",
    "fog_dash": "-",
    # Multi-char clouds
    "cloud_small": " ~ \n~~~",
    "cloud_medium": " ~~~ \n~~~~~\n ~~~ ",
    "cloud_wisp": "~-~",
    "cloud_puff": " ~ \n~~~\n ~ ",
    # Multi-char fog patches
    "fog_patch": ". .\n . ",
    "fog_bank": "...\n. .",
}

@lru_cache(maxsize=None)
def get_shape(name: str) -> Shape:
    """Load shape from library by name, with caching."""
    if name not in SHAPE_LIBRARY:
        raise KeyError(f"Unknown shape: {name}")
    return Shape.parse(SHAPE_LIBRARY[name])


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    shape: Shape
    age: int = 0
    lifetime: int = 100


@dataclass
class BoundingBox:
    """Rectangle exclusion zone."""
    x: int
    y: int
    w: int
    h: int

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


# =============================================================================
# Numba JIT-compiled particle physics
# =============================================================================

@njit(cache=True)
def _tick_physics_batch(
    p_x: np.ndarray, p_y: np.ndarray,
    p_vx: np.ndarray, p_vy: np.ndarray,
    p_age: np.ndarray, p_lifetime: np.ndarray,
    p_shape_idx: np.ndarray,
    n: int, num_ticks: int,
    width: float, height: float,
    death_alpha: float, death_beta: float
) -> int:
    """
    Batch physics update for multiple ticks. Returns new particle count.

    Runs num_ticks iterations of:
    - Position update (x += vx, y += vy)
    - Age increment
    - Death check (beta-distributed probability)
    - Bounds check
    - In-place compaction
    """
    for _ in range(num_ticks):
        if n == 0:
            break

        # Physics update for all particles
        for i in range(n):
            p_x[i] += p_vx[i]
            p_y[i] += p_vy[i]
            p_age[i] += 1

        # Death and bounds check with in-place compaction
        write_idx = 0
        for i in range(n):
            # Beta-distributed death chance (approximated with uniform for speed)
            # Beta(3,7) mean=0.3, we use simple threshold
            death_roll = np.random.random()
            death_prob = np.random.beta(death_alpha, death_beta)

            alive = (
                death_roll >= death_prob and
                p_age[i] < p_lifetime[i] and
                p_y[i] < height + 2 and
                p_y[i] > -3 and
                p_x[i] < width + 2 and
                p_x[i] > -3
            )

            if alive:
                if write_idx != i:
                    p_x[write_idx] = p_x[i]
                    p_y[write_idx] = p_y[i]
                    p_vx[write_idx] = p_vx[i]
                    p_vy[write_idx] = p_vy[i]
                    p_age[write_idx] = p_age[i]
                    p_lifetime[write_idx] = p_lifetime[i]
                    p_shape_idx[write_idx] = p_shape_idx[i]
                write_idx += 1

        n = write_idx

    return n


@njit(cache=True)
def _spawn_particles_snow(
    p_x: np.ndarray, p_y: np.ndarray,
    p_vx: np.ndarray, p_vy: np.ndarray,
    p_age: np.ndarray, p_lifetime: np.ndarray,
    p_shape_idx: np.ndarray,
    start: int, count: int,
    width: float, speed_mult: float, wind_factor: float, num_shapes: int
):
    """Spawn snow particles."""
    base_vx = wind_factor * 0.15 * speed_mult
    vx_var = (0.02 + wind_factor * 0.03) * speed_mult

    for i in range(count):
        idx = start + i
        p_x[idx] = np.random.random() * width
        p_y[idx] = np.random.random() * 2 - 2  # -2 to 0
        p_vx[idx] = base_vx + (np.random.random() * 2 - 1) * vx_var
        p_vy[idx] = (0.15 + np.random.random() * 0.2) * speed_mult
        p_age[idx] = 0
        p_lifetime[idx] = 40 + int(np.random.random() * 60)
        p_shape_idx[idx] = int(np.random.random() * num_shapes)


@njit(cache=True)
def _spawn_particles_rain(
    p_x: np.ndarray, p_y: np.ndarray,
    p_vx: np.ndarray, p_vy: np.ndarray,
    p_age: np.ndarray, p_lifetime: np.ndarray,
    p_shape_idx: np.ndarray,
    start: int, count: int,
    width: float, speed_mult: float, num_shapes: int
):
    """Spawn rain particles."""
    for i in range(count):
        idx = start + i
        p_x[idx] = np.random.random() * width
        p_y[idx] = np.random.random() * 2 - 2
        p_vx[idx] = (np.random.random() * 0.06 - 0.03) * speed_mult
        p_vy[idx] = (0.5 + np.random.random() * 0.4) * speed_mult
        p_age[idx] = 0
        p_lifetime[idx] = 20 + int(np.random.random() * 30)
        p_shape_idx[idx] = int(np.random.random() * num_shapes)


@njit(cache=True)
def _spawn_particles_windy(
    p_x: np.ndarray, p_y: np.ndarray,
    p_vx: np.ndarray, p_vy: np.ndarray,
    p_age: np.ndarray, p_lifetime: np.ndarray,
    p_shape_idx: np.ndarray,
    start: int, count: int,
    height: float, speed_mult: float, num_shapes: int
):
    """Spawn wind particles."""
    for i in range(count):
        idx = start + i
        p_x[idx] = np.random.random() * 2 - 2  # -2 to 0
        p_y[idx] = np.random.random() * height
        p_vx[idx] = (0.4 + np.random.random() * 0.4) * speed_mult
        p_vy[idx] = (np.random.random() * 0.2 - 0.1) * speed_mult
        p_age[idx] = 0
        p_lifetime[idx] = 30 + int(np.random.random() * 30)
        p_shape_idx[idx] = int(np.random.random() * num_shapes)


@njit(cache=True)
def _spawn_particles_fog(
    p_x: np.ndarray, p_y: np.ndarray,
    p_vx: np.ndarray, p_vy: np.ndarray,
    p_age: np.ndarray, p_lifetime: np.ndarray,
    p_shape_idx: np.ndarray,
    start: int, count: int,
    width: float, height: float, speed_mult: float, num_shapes: int
):
    """Spawn fog/cloudy particles."""
    for i in range(count):
        idx = start + i
        p_x[idx] = np.random.random() * width
        p_y[idx] = np.random.random() * height
        p_vx[idx] = (np.random.random() * 0.1 - 0.05) * speed_mult
        p_vy[idx] = (np.random.random() * 0.06 - 0.03) * speed_mult
        p_age[idx] = 0
        p_lifetime[idx] = 60 + int(np.random.random() * 90)
        p_shape_idx[idx] = int(np.random.random() * num_shapes)


@njit(cache=True)
def _compute_render_cells(
    p_x: np.ndarray, p_y: np.ndarray, p_shape_idx: np.ndarray,
    n: int,
    # Pre-computed shape data: for each shape, list of (dx, dy) offsets
    shape_offsets: np.ndarray,  # (max_shapes, max_cells, 2) - dx, dy per cell
    shape_cell_counts: np.ndarray,  # (max_shapes,) - number of cells per shape
    # Output arrays (pre-allocated, large enough)
    out_x: np.ndarray, out_y: np.ndarray,
    out_shape_idx: np.ndarray, out_cell_idx: np.ndarray
) -> int:
    """
    Compute all render cell positions in one pass.
    Returns total number of cells to render.
    """
    idx = 0
    for i in range(n):
        px = int(p_x[i])
        py = int(p_y[i])
        shape_idx = int(p_shape_idx[i])
        num_cells = shape_cell_counts[shape_idx]

        for c in range(num_cells):
            out_x[idx] = px + shape_offsets[shape_idx, c, 0]
            out_y[idx] = py + shape_offsets[shape_idx, c, 1]
            out_shape_idx[idx] = shape_idx
            out_cell_idx[idx] = c
            idx += 1

    return idx


class WeatherSystem:
    """Manages weather particle spawning and physics using Numba JIT compilation."""

    # At intensity 1.0, spawn up to this many particles
    MAX_PARTICLES_BASE = 30

    # Speed multiplier for all particle movement
    SPEED_MULTIPLIER = 2.0

    # Death chance parameters (Beta distribution)
    DEATH_ALPHA = 3.0  # Beta(3, 7) has mean=0.3
    DEATH_BETA = 7.0

    # Batch size for particle arrays (pre-allocated)
    BATCH_SIZE = 128

    # Number of physics ticks to batch together
    TICK_BATCH_SIZE = 1  # Can increase for smoother motion at cost of latency

    # Ambient cloud settings (kept simple - few particles)
    AMBIENT_CLOUD_SHAPES = ["cloud_small", "cloud_wisp", "cloud_puff"]
    AMBIENT_MAX_CLOUDS = 3
    AMBIENT_SPAWN_RATE = 0.03
    AMBIENT_SPAWN_ZONE = 0.35

    # Shape names for each weather type
    SHAPES = {
        "snow": ["snow_star", "snow_plus", "snow_x", "snow_dot", "snow_o"],
        "rain": ["rain_drop", "rain_drop", "rain_colon", "rain_tick", "rain_comma"],
        "cloudy": ["cloud_small", "cloud_wisp", "cloud_puff", "fog_tilde"],
        "fog": ["fog_patch", "fog_bank", "fog_dot", "fog_tilde"],
        "windy": ["wind_tilde", "wind_dash", "wind_tick", "wind_arrow", "wind_slash"],
    }

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.weather_type: Optional[str] = None
        self.intensity = 0.0
        self.wind_speed = 0.0
        self.exclusion_zones: list[BoundingBox] = []

        # Particle storage (pre-allocated arrays for Numba)
        self._init_particle_arrays()

        # Ambient clouds (kept as list - small count, complex shapes)
        self.ambient_clouds: list[Particle] = []

        # Shape cache for current weather type
        self._shape_cache: list[Shape] = []

        # Render position cache (reused arrays)
        self._render_px = np.zeros(self.BATCH_SIZE, dtype=np.int32)
        self._render_py = np.zeros(self.BATCH_SIZE, dtype=np.int32)
        self._render_shape = np.zeros(self.BATCH_SIZE, dtype=np.int8)

        # Shape cells cache
        self._shape_cells_cache = {}

        # Render cache for position -> cells
        self._render_cache = {}

        # Tick accumulator for batching
        self._pending_ticks = 0

    def _init_particle_arrays(self):
        """Initialize pre-allocated NumPy arrays for particles."""
        n = self.BATCH_SIZE
        self.p_x = np.zeros(n, dtype=np.float64)  # float64 for Numba compatibility
        self.p_y = np.zeros(n, dtype=np.float64)
        self.p_vx = np.zeros(n, dtype=np.float64)
        self.p_vy = np.zeros(n, dtype=np.float64)
        self.p_age = np.zeros(n, dtype=np.int64)
        self.p_lifetime = np.zeros(n, dtype=np.int64)
        self.p_shape_idx = np.zeros(n, dtype=np.int64)
        self.p_count = 0

    def _grow_arrays(self):
        """Double array capacity when needed."""
        old_size = len(self.p_x)
        new_size = old_size * 2

        for attr in ['p_x', 'p_y', 'p_vx', 'p_vy']:
            old = getattr(self, attr)
            new = np.zeros(new_size, dtype=np.float64)
            new[:old_size] = old
            setattr(self, attr, new)

        for attr in ['p_age', 'p_lifetime', 'p_shape_idx']:
            old = getattr(self, attr)
            new = np.zeros(new_size, dtype=np.int64)
            new[:old_size] = old
            setattr(self, attr, new)

        # Grow render arrays too
        self._render_px = np.zeros(new_size, dtype=np.int32)
        self._render_py = np.zeros(new_size, dtype=np.int32)
        self._render_shape = np.zeros(new_size, dtype=np.int8)

    def set_exclusion_zones(self, zones: list[BoundingBox]):
        self.exclusion_zones = zones

    def set_weather(self, weather_type: str, intensity: float = 0.6, wind_speed: float = 0.0):
        if weather_type != self.weather_type:
            self.weather_type = weather_type
            self.p_count = 0
            self._shape_cells_cache.clear()
            self._render_cache.clear()
            if weather_type in self.SHAPES:
                self._shape_cache = [get_shape(name) for name in self.SHAPES[weather_type]]
                self._build_shape_arrays()
            else:
                self._shape_cache = []
                self._shape_offsets = None
        self.intensity = intensity
        self.wind_speed = wind_speed

    def _build_shape_arrays(self):
        """Pre-compute shape offset arrays for Numba render."""
        if not self._shape_cache:
            return

        num_shapes = len(self._shape_cache)
        # Find max cells per shape
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

        # Build arrays
        self._shape_offsets = np.zeros((num_shapes, max_cells, 2), dtype=np.int32)
        self._shape_cell_counts = np.zeros(num_shapes, dtype=np.int32)
        self._shape_chars = []  # Keep chars as Python list (for layer.put)

        for i, cells in enumerate(shape_cells):
            self._shape_cell_counts[i] = len(cells)
            chars = []
            for j, (dx, dy, char) in enumerate(cells):
                self._shape_offsets[i, j, 0] = dx
                self._shape_offsets[i, j, 1] = dy
                chars.append(char)
            self._shape_chars.append(chars)

        # Pre-allocate render output arrays (max particles * max cells)
        max_output = self.BATCH_SIZE * max_cells
        self._render_out_x = np.zeros(max_output, dtype=np.int32)
        self._render_out_y = np.zeros(max_output, dtype=np.int32)
        self._render_out_shape = np.zeros(max_output, dtype=np.int32)
        self._render_out_cell = np.zeros(max_output, dtype=np.int32)

    def _tick_ambient_clouds(self):
        """Update ambient clouds (simple list-based for complex shapes)."""
        alive = []
        for p in self.ambient_clouds:
            p.x += p.vx
            p.y += p.vy
            if (p.x < self.width + 1 and p.x + p.shape.width > -1 and
                    p.y < self.height + 1 and p.y + p.shape.height > -1):
                alive.append(p)
        self.ambient_clouds = alive

        if self.weather_type and self.weather_type not in ("clear", None):
            return

        if (len(self.ambient_clouds) < self.AMBIENT_MAX_CLOUDS and
                random.random() < self.AMBIENT_SPAWN_RATE):
            shape = get_shape(random.choice(self.AMBIENT_CLOUD_SHAPES))
            s = self.SPEED_MULTIPLIER
            self.ambient_clouds.append(Particle(
                x=random.uniform(-shape.width * 2, -shape.width),
                y=random.uniform(0, int(self.height * self.AMBIENT_SPAWN_ZONE)),
                vx=random.uniform(0.25, 0.45) * s,
                vy=random.uniform(-0.08, 0.08) * s,
                shape=shape,
                lifetime=999999,
            ))

    def tick(self, num_ticks: int = 1):
        """Advance simulation by num_ticks steps."""
        self._tick_ambient_clouds()

        if not self.weather_type or not self._shape_cache:
            return

        # Run batched physics via Numba JIT
        if self.p_count > 0:
            self.p_count = _tick_physics_batch(
                self.p_x, self.p_y,
                self.p_vx, self.p_vy,
                self.p_age, self.p_lifetime,
                self.p_shape_idx,
                self.p_count, num_ticks,
                float(self.width), float(self.height),
                self.DEATH_ALPHA, self.DEATH_BETA
            )

        # Spawn new particles (once per tick call, not per batch)
        max_particles = int(self.intensity * self.MAX_PARTICLES_BASE)
        spawn_rate = self.intensity * 2.0
        spawn_count = min(
            np.random.poisson(spawn_rate * 3),
            max_particles - self.p_count
        )

        if spawn_count > 0:
            self._spawn_batch(spawn_count)

    def _spawn_batch(self, count: int):
        """Spawn particles using Numba JIT functions."""
        while self.p_count + count > len(self.p_x):
            self._grow_arrays()

        start = self.p_count
        s = self.SPEED_MULTIPLIER
        num_shapes = len(self._shape_cache)

        if self.weather_type == "snow":
            wind_factor = min(self.wind_speed / 30.0, 1.0)
            _spawn_particles_snow(
                self.p_x, self.p_y, self.p_vx, self.p_vy,
                self.p_age, self.p_lifetime, self.p_shape_idx,
                start, count, float(self.width), s, wind_factor, num_shapes
            )
        elif self.weather_type == "rain":
            _spawn_particles_rain(
                self.p_x, self.p_y, self.p_vx, self.p_vy,
                self.p_age, self.p_lifetime, self.p_shape_idx,
                start, count, float(self.width), s, num_shapes
            )
        elif self.weather_type == "windy":
            _spawn_particles_windy(
                self.p_x, self.p_y, self.p_vx, self.p_vy,
                self.p_age, self.p_lifetime, self.p_shape_idx,
                start, count, float(self.height), s, num_shapes
            )
        else:  # cloudy, fog
            _spawn_particles_fog(
                self.p_x, self.p_y, self.p_vx, self.p_vy,
                self.p_age, self.p_lifetime, self.p_shape_idx,
                start, count, float(self.width), float(self.height), s, num_shapes
            )

        self.p_count += count

    def _build_exclusion_set(self) -> set:
        """Pre-compute set of blocked (x, y) positions for fast lookup."""
        blocked = set()
        for zone in self.exclusion_zones:
            for x in range(zone.x, zone.x + zone.w):
                for y in range(zone.y, zone.y + zone.h):
                    blocked.add((x, y))
        return blocked

    def _get_shape_cells(self, shape_idx: int) -> tuple:
        """Get cached (col_offset, row_offset, char) tuples for a shape."""
        if shape_idx not in self._shape_cells_cache:
            shape = self._shape_cache[shape_idx]
            cells = []
            for row_idx, row in enumerate(shape.pattern):
                for col_idx, char in enumerate(row):
                    if char != " ":
                        cells.append((col_idx, row_idx, char))
            self._shape_cells_cache[shape_idx] = tuple(cells)
        return self._shape_cells_cache[shape_idx]

    def _render_particle(self, layer: Layer, p: Particle, color: int, blocked: set):
        """Render a single Particle object (for ambient clouds)."""
        px, py = int(p.x), int(p.y)
        for row_idx, row in enumerate(p.shape.pattern):
            for col_idx, char in enumerate(row):
                if char == " ":
                    continue
                cx, cy = px + col_idx, py + row_idx
                if (cx, cy) in blocked:
                    continue
                layer.put(cx, cy, char, color)

    def render(self, layer: Layer, color: int = 8):
        """Render all particles to layer using Numba-accelerated position computation."""
        blocked = self._build_exclusion_set()

        # Render ambient clouds (few particles, complex shapes)
        for p in self.ambient_clouds:
            self._render_particle(layer, p, color, blocked)

        # Fast path: use Numba to compute all cell positions
        n = self.p_count
        if n == 0 or self._shape_offsets is None:
            return

        # Ensure output arrays are large enough
        max_cells = self._shape_offsets.shape[1]
        needed_size = n * max_cells
        if len(self._render_out_x) < needed_size:
            new_size = needed_size * 2
            self._render_out_x = np.zeros(new_size, dtype=np.int32)
            self._render_out_y = np.zeros(new_size, dtype=np.int32)
            self._render_out_shape = np.zeros(new_size, dtype=np.int32)
            self._render_out_cell = np.zeros(new_size, dtype=np.int32)

        # Compute all render positions with Numba
        num_cells = _compute_render_cells(
            self.p_x, self.p_y, self.p_shape_idx, n,
            self._shape_offsets, self._shape_cell_counts,
            self._render_out_x, self._render_out_y,
            self._render_out_shape, self._render_out_cell
        )

        # Convert to Python lists for fast iteration (avoids numpy indexing overhead)
        xs = self._render_out_x[:num_cells].tolist()
        ys = self._render_out_y[:num_cells].tolist()
        shapes = self._render_out_shape[:num_cells].tolist()
        cells = self._render_out_cell[:num_cells].tolist()
        shape_chars = self._shape_chars

        for cx, cy, shape_idx, cell_idx in zip(xs, ys, shapes, cells):
            if (cx, cy) not in blocked:
                layer.put(cx, cy, shape_chars[shape_idx][cell_idx], color)


# =============================================================================
# Frame Renderer (uses RenderPipeline)
# =============================================================================

class FrameRenderer:
    """Renders complete widget frames using layered pipeline."""

    # Base dimensions (reference grid)
    BASE_WIDTH = 18
    BASE_HEIGHT = 10

    # Avatar fixed dimensions
    AVATAR_WIDTH = 11
    AVATAR_HEIGHT = 5

    # Layout ratios (relative to base grid)
    MARGIN_RATIO = 0.15        # 15% margin on each side
    BAR_WIDTH_RATIO = 0.65     # Bar is 65% of grid width
    CONTENT_HEIGHT_RATIO = 0.7 # Content uses 70% of height
    BAR_GAP_RATIO = 0.1        # Gap between avatar and bar

    def __init__(self, width: int = 18, height: int = 10,
                 avatar_x_offset: int = 0, avatar_y_offset: int = 0,
                 bar_x_offset: int = 0, bar_y_offset: int = 0):
        self.width = width
        self.height = height

        # Store offsets for layout adjustment
        self.avatar_x_offset = avatar_x_offset
        self.avatar_y_offset = avatar_y_offset
        self.bar_x_offset = bar_x_offset
        self.bar_y_offset = bar_y_offset

        # Pipeline with layers
        self.pipeline = RenderPipeline(width, height)
        self.weather_layer = self.pipeline.add_layer("weather", priority=0)
        self.avatar_layer = self.pipeline.add_layer("avatar", priority=50)
        self.bar_layer = self.pipeline.add_layer("bar", priority=80)
        self.verb_layer = self.pipeline.add_layer("verb", priority=90)

        # Auto-calculate layout
        self._recalculate_layout()

    def _recalculate_layout(self):
        """Calculate element positions using proportional math, then apply offsets."""
        w, h = self.width, self.height

        # Scale factor relative to base
        scale_x = w / self.BASE_WIDTH
        scale_y = h / self.BASE_HEIGHT

        # Margins (proportional to grid size)
        margin_x = int(w * self.MARGIN_RATIO)
        margin_y = int(h * self.MARGIN_RATIO)

        # Content area
        content_w = w - 2 * margin_x
        content_h = h - 2 * margin_y

        # Avatar stays fixed size, centered in content area (auto-centering)
        avatar_x_centered = margin_x + (content_w - self.AVATAR_WIDTH) // 2

        # Vertical layout: avatar + gap + bar within content area
        bar_gap = max(1, int(h * self.BAR_GAP_RATIO))
        total_content_h = self.AVATAR_HEIGHT + bar_gap + 1  # 1 for bar height

        # Center content block vertically (auto-centering)
        content_start_y = margin_y + (content_h - total_content_h) // 2

        avatar_y_centered = content_start_y
        bar_y_centered = content_start_y + self.AVATAR_HEIGHT + bar_gap

        # Bar width scales with grid (clamped to reasonable bounds)
        self.bar_width = max(self.AVATAR_WIDTH, min(int(w * self.BAR_WIDTH_RATIO), w - 2 * margin_x))
        bar_x_centered = margin_x + (content_w - self.bar_width) // 2

        # Apply offsets to centered positions
        self.avatar_x = avatar_x_centered + self.avatar_x_offset
        self.avatar_y = avatar_y_centered + self.avatar_y_offset
        self.bar_x = bar_x_centered + self.bar_x_offset
        self.bar_y = bar_y_centered + self.bar_y_offset

        # Weather system
        self.weather = WeatherSystem(self.width, self.height)

        # Animation state
        self.keyframe_index = 0
        self.current_status = "idle"
        self.current_keyframes = ANIMATION_KEYFRAMES.get("idle", DEFAULT_KEYFRAMES)
        self.current_color = get_status_ansi().get("idle", COLORS["gray"])

    def set_status(self, status: str):
        if status != self.current_status:
            self.current_status = status
            self.current_keyframes = ANIMATION_KEYFRAMES.get(status, DEFAULT_KEYFRAMES)
            self.current_color = get_status_ansi().get(status, COLORS["gray"])
            self.keyframe_index = 0

    def set_weather(self, weather_type: str, intensity: float = 0.6, wind_speed: float = 0.0):
        self.weather.set_weather(weather_type, intensity, wind_speed)

    def tick(self):
        """Advance animation state."""
        if self.current_keyframes:
            self.keyframe_index = (self.keyframe_index + 1) % len(self.current_keyframes)
        self.weather.tick()

    def _render_weather(self):
        """Render weather layer."""
        self.weather_layer.clear()
        # Set exclusion zone for avatar bounding box
        avatar_box = BoundingBox(
            x=self.avatar_x,
            y=self.avatar_y,
            w=self.AVATAR_WIDTH,
            h=self.AVATAR_HEIGHT
        )
        self.weather.set_exclusion_zones([avatar_box])
        self.weather.render(self.weather_layer, color=COLORS["white"])

    def _render_avatar(self):
        """Render avatar layer.

        Uses non-breaking space (U+00A0) for internal padding instead of regular space.
        This makes the avatar fully opaque - particles can never show through.
        Regular space (U+0020) is treated as transparent in compositing.
        """
        self.avatar_layer.clear()

        eyes, mouth = self.current_keyframes[self.keyframe_index]
        eye_char = EYES.get(eyes, "o")
        l, g, r = EYE_POSITIONS.get(eyes, (3, 1, 3))
        mouth_char = MOUTHS.get(mouth, "~")
        border = BORDERS.get(self.current_status, "-")
        substrate = SUBSTRATES.get(self.current_status, " .  .  . ")

        x, y = self.avatar_x, self.avatar_y
        # Use color 0 = default/theme color (lets Swift use its theme color for border sync)
        color = 0

        # Use non-breaking space (NBSP) for internal padding - visually identical to space
        # but won't be treated as transparent during compositing (SPACE = ord(' ') = 32)
        nbsp = '\u00a0'  # Non-breaking space, ord = 160

        # Build face lines with rounded corners, using NBSP for padding
        lines = [
            f"╭{border * 9}╮",
            f"│{nbsp * l}{eye_char}{nbsp * g}{eye_char}{nbsp * r}│",
            f"│{nbsp * 4}{mouth_char}{nbsp * 4}│",
            f"│{substrate.replace(' ', nbsp)}│",
            f"╰{border * 9}╯",
        ]

        for dy, line in enumerate(lines):
            self.avatar_layer.put_text(x, y + dy, line, color)

    def _render_bar(self, context_percent: float):
        """Render progress bar layer."""
        self.bar_layer.clear()

        # Validate and clamp context_percent to prevent flickering
        if context_percent is None or not isinstance(context_percent, (int, float)):
            context_percent = 0.0
        context_percent = max(0.0, min(100.0, float(context_percent)))

        filled = int(context_percent / 100 * self.bar_width)

        # Draw empty track first (dimmed)
        for i in range(self.bar_width):
            self.bar_layer.put(self.bar_x + i, self.bar_y, '-', COLORS["gray"])

        # Draw filled portion on top (bright white = ANSI 15)
        for i in range(filled):
            self.bar_layer.put(self.bar_x + i, self.bar_y, '#', 15)

    def _render_verb(self, verb: str):
        """Render whimsy verb below the progress bar."""
        self.verb_layer.clear()

        if not verb:
            return

        # Format: lowercase with trailing ellipsis
        display_verb = f"{verb.lower()}..."

        # Center the verb below the bar (with extra spacing)
        verb_y = self.bar_y + 2
        verb_x = self.bar_x + (self.bar_width - len(display_verb)) // 2

        # Clamp to valid range
        verb_x = max(0, verb_x)

        # Use a soft gray for the verb (ANSI 249 - light gray)
        self.verb_layer.put_text(verb_x, verb_y, display_verb, 249)

    def render(self, context_percent: float = 0, whimsy_verb: str = None) -> str:
        """Render complete frame."""
        self._render_weather()
        self._render_avatar()
        self._render_bar(context_percent)
        self._render_verb(whimsy_verb)
        return self.pipeline.to_string()

    def render_colored(self, context_percent: float = 0, whimsy_verb: str = None) -> str:
        """Render complete frame with ANSI colors."""
        self._render_weather()
        self._render_avatar()
        self._render_bar(context_percent)
        self._render_verb(whimsy_verb)
        return self.pipeline.to_ansi()


# =============================================================================
# Test
# =============================================================================

if __name__ == "__main__":
    import time
    import sys

    renderer = FrameRenderer(width=18, height=10)
    renderer.set_status("running")
    renderer.set_weather("snow", 1.0)

    print("\033[2J\033[H")
    print("Pipeline Renderer Demo (Ctrl+C to stop)\n")

    try:
        ctx = 0
        for _ in range(100):
            renderer.tick()
            frame = renderer.render(context_percent=ctx)

            print("\033[3;0H")
            print(frame)
            print(f"\nStatus: {renderer.current_status}  Context: {ctx:.0f}%")

            ctx = (ctx + 1) % 100
            time.sleep(0.15)
    except KeyboardInterrupt:
        pass

    print("\nDone!")
