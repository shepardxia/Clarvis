"""Weather particle physics: data structures and Numba JIT simulation functions.

Pure functions on numpy arrays — no dependency on archetypes, Layer, or registry.
"""

from dataclasses import dataclass

import numpy as np

try:
    from numba import njit
except ImportError:

    def njit(**kwargs):
        def decorator(fn):
            return fn

        return decorator


# =============================================================================
# Data Structures
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
        if "\n" in text:
            pattern = tuple(line for line in text.split("\n") if line)
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
def tick_physics_batch(
    p_x: np.ndarray,
    p_y: np.ndarray,
    p_vx: np.ndarray,
    p_vy: np.ndarray,
    p_age: np.ndarray,
    p_lifetime: np.ndarray,
    p_shape_idx: np.ndarray,
    n: int,
    num_ticks: int,
    width: float,
    height: float,
    death_prob: float,
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
                survives_death
                and p_age[i] < p_lifetime[i]
                and p_y[i] < height + 1
                and p_y[i] > -2
                and p_x[i] < width + 1
                and p_x[i] > -2
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
def spawn_particles(
    p_x: np.ndarray,
    p_y: np.ndarray,
    p_vx: np.ndarray,
    p_vy: np.ndarray,
    p_age: np.ndarray,
    p_lifetime: np.ndarray,
    p_shape_idx: np.ndarray,
    start: int,
    count: int,
    num_shapes: int,
    x_off: float,
    x_range: float,
    y_off: float,
    y_range: float,
    vx_off: float,
    vx_range: float,
    vy_off: float,
    vy_range: float,
    life_base: int,
    life_range: int,
):
    """Spawn particles with parameterized position, velocity, and lifetime."""
    for i in range(count):
        idx = start + i
        p_x[idx] = x_off + np.random.random() * x_range
        p_y[idx] = y_off + np.random.random() * y_range
        p_vx[idx] = vx_off + np.random.random() * vx_range
        p_vy[idx] = vy_off + np.random.random() * vy_range
        p_age[idx] = 0
        p_lifetime[idx] = life_base + int(np.random.random() * life_range)
        p_shape_idx[idx] = int(np.random.random() * num_shapes)


@njit(cache=True)
def compute_render_cells(
    p_x: np.ndarray,
    p_y: np.ndarray,
    p_shape_idx: np.ndarray,
    n: int,
    shape_offsets: np.ndarray,
    shape_cell_counts: np.ndarray,
    out_x: np.ndarray,
    out_y: np.ndarray,
    out_shape_idx: np.ndarray,
    out_cell_idx: np.ndarray,
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
