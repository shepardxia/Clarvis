"""Tests for sprites/weather_physics.py — data structures and physics functions."""

import numpy as np

from clarvis.display.sprites.weather_physics import (
    BoundingBox,
    Shape,
    tick_physics_batch,
)


class TestShape:
    def test_parse_single_line(self):
        s = Shape.parse(".")
        assert s.pattern == (".",)
        assert s.width == 1
        assert s.height == 1

    def test_parse_multiline(self):
        s = Shape.parse("ab\ncd")
        assert s.pattern == ("ab", "cd")
        assert s.width == 2
        assert s.height == 2

    def test_parse_empty_raises(self):
        try:
            Shape.parse("")
            assert False, "Should have raised"
        except ValueError:
            pass


class TestBoundingBox:
    def test_contains_inside(self):
        bb = BoundingBox(5, 5, 10, 10)
        assert bb.contains(5, 5)
        assert bb.contains(14, 14)

    def test_contains_outside(self):
        bb = BoundingBox(5, 5, 10, 10)
        assert not bb.contains(4, 5)
        assert not bb.contains(15, 5)
        assert not bb.contains(5, 15)


class TestTickPhysics:
    def test_particles_move(self):
        n = 3
        p_x = np.array([1.0, 2.0, 3.0])
        p_y = np.array([1.0, 2.0, 3.0])
        p_vx = np.array([0.1, 0.1, 0.1])
        p_vy = np.array([0.2, 0.2, 0.2])
        p_age = np.zeros(n, dtype=np.int64)
        p_lifetime = np.full(n, 1000, dtype=np.int64)
        p_shape_idx = np.zeros(n, dtype=np.int64)

        new_n = tick_physics_batch(
            p_x,
            p_y,
            p_vx,
            p_vy,
            p_age,
            p_lifetime,
            p_shape_idx,
            n,
            1,
            100.0,
            100.0,
            0.0,
        )
        # With death_prob=0, all should survive and move
        assert new_n == n
        assert p_x[0] > 1.0
        assert p_y[0] > 1.0
