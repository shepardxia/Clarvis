"""
Weather archetype - particle physics simulation for weather effects.

Loads particle shapes and weather type definitions from YAML.
Uses Numba JIT compilation for performant physics simulation.
"""

import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import numpy as np
from numba import njit

from ..widget.pipeline import Layer
from ..elements.registry import ElementRegistry
from .base import Archetype


# =============================================================================
# Shape and Particle Data Structures
# =============================================================================

@dataclass
class Shape:
    """Multi-character pattern for weather particles."""
    pattern: tuple[str, ...]
    width: int
    height: int

    @classmethod
    def parse(cls, text: str) -> "Shape":
        """Parse text into a shape. Each line becomes a row."""
        if not text:
            raise ValueError("Shape text cannot be empty")
        # Handle both literal newlines and escaped newlines
        if '\n' in text:
            pattern = tuple(line for line in text.split('\n') if line)
        else:
            pattern = (text,)
        height = len(pattern)
        width = max(len(line) for line in pattern) if pattern else 0
        return cls(pattern=pattern, width=width, height=height)


@dataclass
class Particle:
    """A single particle for ambient clouds (non-JIT path)."""
    x: float
    y: float
    vx: float
    vy: float
    shape: Shape
    age: int = 0
    lifetime: int = 200


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
    death_prob: float
) -> int:
    """Batch physics update for multiple ticks. Returns new particle count."""
    for _ in range(num_ticks):
        if n == 0:
            break

        for i in range(n):
            p_x[i] += p_vx[i]
            p_y[i] += p_vy[i]
            p_age[i] += 1

        write_idx = 0
        for i in range(n):
            survives_death = np.random.random() >= death_prob
            alive = (
                survives_death and
                p_age[i] < p_lifetime[i] and
                p_y[i] < height + 1 and
                p_y[i] > -2 and
                p_x[i] < width + 1 and
                p_x[i] > -2
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
        p_y[idx] = np.random.random() * 2 - 2
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
        p_x[idx] = np.random.random() * 2 - 2
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
    shape_offsets: np.ndarray,
    shape_cell_counts: np.ndarray,
    out_x: np.ndarray, out_y: np.ndarray,
    out_shape_idx: np.ndarray, out_cell_idx: np.ndarray
) -> int:
    """Compute all render cell positions in one pass."""
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


# =============================================================================
# Weather Archetype
# =============================================================================

class WeatherArchetype(Archetype):
    """
    Manages weather particle spawning and physics.

    Loads configuration from elements/archetypes/weather.yaml.
    Loads weather types from elements/weather/*.yaml.
    Loads particle shapes from elements/particles/*.yaml.
    """

    def __init__(self, registry: ElementRegistry, width: int, height: int):
        self.width = width
        self.height = height
        super().__init__(registry, 'weather')

        # Physics parameters (loaded from config)
        self._load_physics_params()

        # Weather state
        self.weather_type: Optional[str] = None
        self.intensity = 0.0
        self.wind_speed = 0.0
        self.exclusion_zones: list[BoundingBox] = []

        # Particle storage
        self._init_particle_arrays()

        # Ambient clouds
        self.ambient_clouds: list[Particle] = []

        # Shape cache
        self._shape_cache: list[Shape] = []
        self._shape_cells_cache = {}

    def _load_physics_params(self) -> None:
        """Load physics parameters from config."""
        physics = self.config.get('physics', {})
        self.death_prob = physics.get('death_prob', 0.08)
        self.max_particles_base = physics.get('max_particles_base', 40)
        self.speed_multiplier = physics.get('speed_multiplier', 2.0)
        self.batch_size = physics.get('batch_size', 128)

        ambient = self.config.get('ambient', {})
        self.ambient_shapes = ambient.get('shapes', ['cloud_small', 'cloud_wisp', 'cloud_puff'])
        self.ambient_max_clouds = ambient.get('max_clouds', 3)
        self.ambient_spawn_rate = ambient.get('spawn_rate', 0.03)
        self.ambient_spawn_zone = ambient.get('spawn_zone', 0.35)

    def _init_particle_arrays(self) -> None:
        """Initialize pre-allocated NumPy arrays for particles."""
        n = self.batch_size
        self.p_x = np.zeros(n, dtype=np.float64)
        self.p_y = np.zeros(n, dtype=np.float64)
        self.p_vx = np.zeros(n, dtype=np.float64)
        self.p_vy = np.zeros(n, dtype=np.float64)
        self.p_age = np.zeros(n, dtype=np.int64)
        self.p_lifetime = np.zeros(n, dtype=np.int64)
        self.p_shape_idx = np.zeros(n, dtype=np.int64)
        self.p_count = 0

        # Render arrays
        self._render_px = np.zeros(self.batch_size, dtype=np.int32)
        self._render_py = np.zeros(self.batch_size, dtype=np.int32)
        self._render_shape = np.zeros(self.batch_size, dtype=np.int8)

    def _grow_arrays(self) -> None:
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

        self._render_px = np.zeros(new_size, dtype=np.int32)
        self._render_py = np.zeros(new_size, dtype=np.int32)
        self._render_shape = np.zeros(new_size, dtype=np.int8)

    def _on_element_change(self, kind: str, name: str) -> None:
        """Handle element changes."""
        if kind == 'archetypes' and name == 'weather':
            self._load_physics_params()
        elif kind == 'weather' and name == self.weather_type:
            self._rebuild_shape_cache()
        elif kind == 'particles':
            if self.weather_type:
                self._rebuild_shape_cache()

    def _get_shape(self, name: str) -> Optional[Shape]:
        """Get shape from registry."""
        elem = self.registry.get('particles', name)
        if not elem:
            return None
        pattern = elem.get('pattern', '')
        return Shape.parse(pattern)

    def _rebuild_shape_cache(self) -> None:
        """Rebuild shape cache for current weather type."""
        self._shape_cache = []
        self._shape_cells_cache.clear()

        if not self.weather_type:
            self._shape_offsets = None
            return

        # Get weather type definition
        weather_def = self.registry.get('weather', self.weather_type)
        if not weather_def:
            self._shape_offsets = None
            return

        # Load particle shapes
        particle_names = weather_def.get('particles', [])
        for name in particle_names:
            shape = self._get_shape(name)
            if shape:
                self._shape_cache.append(shape)

        if not self._shape_cache:
            self._shape_offsets = None
            return

        self._build_shape_arrays()

    def _build_shape_arrays(self) -> None:
        """Pre-compute shape offset arrays for Numba render."""
        if not self._shape_cache:
            return

        num_shapes = len(self._shape_cache)
        max_cells = 0
        shape_cells = []

        for shape in self._shape_cache:
            cells = []
            for row_idx, row in enumerate(shape.pattern):
                for col_idx, char in enumerate(row):
                    if char != ' ':
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

        max_output = self.batch_size * max_cells
        self._render_out_x = np.zeros(max_output, dtype=np.int32)
        self._render_out_y = np.zeros(max_output, dtype=np.int32)
        self._render_out_shape = np.zeros(max_output, dtype=np.int32)
        self._render_out_cell = np.zeros(max_output, dtype=np.int32)

    def prewarm_shapes(self) -> dict[str, int]:
        """Pre-build shape arrays for all weather types.
        
        Weather particles are dynamic (positions change each tick),
        but shape data can be pre-computed for instant weather switching.
        
        Returns stats dict with weather type -> particle count.
        """
        stats = {}
        original_type = self.weather_type
        
        # Get all weather types
        weather_names = self.registry.list_names('weather')
        
        for name in weather_names:
            self.weather_type = name
            self._rebuild_shape_cache()
            stats[name] = len(self._shape_cache)
        
        # Restore original state
        self.weather_type = original_type
        if original_type:
            self._rebuild_shape_cache()
        
        return stats

    def cache_stats(self) -> dict:
        """Return shape cache statistics."""
        return {
            'current_weather': self.weather_type,
            'cached_shapes': len(self._shape_cache),
            'active_particles': self.p_count,
            'ambient_clouds': len(self.ambient_clouds)
        }

    def set_exclusion_zones(self, zones: list[BoundingBox]) -> None:
        """Set areas where particles should not render."""
        self.exclusion_zones = zones

    def set_weather(self, weather_type: str, intensity: float = 0.6, wind_speed: float = 0.0) -> None:
        """Set current weather type and intensity."""
        if weather_type != self.weather_type:
            self.weather_type = weather_type
            self.p_count = 0
            self._rebuild_shape_cache()
        self.intensity = intensity
        self.wind_speed = wind_speed

    def _tick_ambient_clouds(self) -> None:
        """Update ambient clouds."""
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

        if (len(self.ambient_clouds) < self.ambient_max_clouds and
                random.random() < self.ambient_spawn_rate):
            shape_name = random.choice(self.ambient_shapes)
            shape = self._get_shape(shape_name)
            if shape:
                s = self.speed_multiplier
                self.ambient_clouds.append(Particle(
                    x=random.uniform(-shape.width * 2, -shape.width),
                    y=random.uniform(0, int(self.height * self.ambient_spawn_zone)),
                    vx=random.uniform(0.25, 0.45) * s,
                    vy=random.uniform(-0.08, 0.08) * s,
                    shape=shape,
                    lifetime=999999,
                ))

    def tick(self, num_ticks: int = 1) -> None:
        """Advance simulation by num_ticks steps."""
        self._tick_ambient_clouds()

        if not self.weather_type or not self._shape_cache:
            return

        if self.p_count > 0:
            self.p_count = _tick_physics_batch(
                self.p_x, self.p_y,
                self.p_vx, self.p_vy,
                self.p_age, self.p_lifetime,
                self.p_shape_idx,
                self.p_count, num_ticks,
                float(self.width), float(self.height),
                self.death_prob
            )

        max_particles = int(self.intensity * self.max_particles_base)
        spawn_rate = self.intensity * 2.0
        spawn_count = min(
            np.random.poisson(spawn_rate * 3),
            max_particles - self.p_count
        )

        if spawn_count > 0:
            self._spawn_batch(spawn_count)

    def _spawn_batch(self, count: int) -> None:
        """Spawn particles using Numba JIT functions."""
        while self.p_count + count > len(self.p_x):
            self._grow_arrays()

        start = self.p_count
        s = self.speed_multiplier
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
        """Pre-compute set of blocked positions."""
        blocked = set()
        for zone in self.exclusion_zones:
            for x in range(zone.x, zone.x + zone.w):
                for y in range(zone.y, zone.y + zone.h):
                    blocked.add((x, y))
        return blocked

    def _render_particle(self, layer: Layer, p: Particle, color: int, blocked: set) -> None:
        """Render a single Particle object."""
        px, py = int(p.x), int(p.y)
        for row_idx, row in enumerate(p.shape.pattern):
            for col_idx, char in enumerate(row):
                if char == ' ':
                    continue
                cx, cy = px + col_idx, py + row_idx
                if (cx, cy) in blocked:
                    continue
                layer.put(cx, cy, char, color)

    def render(self, layer: Layer, color: int = 8, **kwargs) -> None:
        """Render all particles to layer."""
        blocked = self._build_exclusion_set()

        # Render ambient clouds
        for p in self.ambient_clouds:
            self._render_particle(layer, p, color, blocked)

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

        num_cells = _compute_render_cells(
            self.p_x, self.p_y, self.p_shape_idx, n,
            self._shape_offsets, self._shape_cell_counts,
            self._render_out_x, self._render_out_y,
            self._render_out_shape, self._render_out_cell
        )

        xs = self._render_out_x[:num_cells].tolist()
        ys = self._render_out_y[:num_cells].tolist()
        shapes = self._render_out_shape[:num_cells].tolist()
        cells = self._render_out_cell[:num_cells].tolist()
        shape_chars = self._shape_chars

        for cx, cy, shape_idx, cell_idx in zip(xs, ys, shapes, cells):
            if (cx, cy) not in blocked:
                layer.put(cx, cy, shape_chars[shape_idx][cell_idx], color)
