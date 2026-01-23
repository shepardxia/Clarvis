"""Tests for render pipeline module."""

import pytest

from central_hub.widget.pipeline import Layer, RenderPipeline


class TestLayer:
    """Tests for Layer class."""

    def test_create_layer(self):
        layer = Layer("test", priority=10, width=20, height=10)
        assert layer.name == "test"
        assert layer.priority == 10
        assert layer.width == 20
        assert layer.height == 10

    def test_put_char(self):
        layer = Layer("test", priority=0, width=10, height=5)
        layer.put(3, 2, "X", color=1)

        # Verify character was placed
        assert layer.chars[2, 3] == ord("X")
        assert layer.colors[2, 3] == 1

    def test_put_out_of_bounds(self):
        """Out of bounds put should not raise."""
        layer = Layer("test", priority=0, width=10, height=5)
        # Should not raise
        layer.put(100, 100, "X")
        layer.put(-1, -1, "Y")

    def test_clear(self):
        layer = Layer("test", priority=0, width=10, height=5)
        layer.put(3, 2, "X")
        layer.clear()

        # Should be cleared (space = 32)
        assert layer.chars[2, 3] == 32

    def test_fill(self):
        layer = Layer("test", priority=0, width=10, height=5)
        layer.fill(2, 1, 3, 2, "#", color=5)

        # Check filled area
        assert layer.chars[1, 2] == ord("#")
        assert layer.chars[1, 3] == ord("#")
        assert layer.chars[2, 2] == ord("#")
        assert layer.colors[1, 2] == 5


class TestRenderPipeline:
    """Tests for RenderPipeline class."""

    def test_create_pipeline(self):
        pipeline = RenderPipeline(20, 10)
        assert pipeline.width == 20
        assert pipeline.height == 10
        assert len(pipeline.layers) == 0

    def test_add_layer(self):
        pipeline = RenderPipeline(20, 10)
        layer = pipeline.add_layer("background", priority=0)

        assert "background" in pipeline.layers
        assert layer.name == "background"
        assert layer.width == 20
        assert layer.height == 10

    def test_layer_priority_ordering(self):
        """Higher priority layers should render on top."""
        pipeline = RenderPipeline(10, 5)

        bg = pipeline.add_layer("background", priority=0)
        fg = pipeline.add_layer("foreground", priority=10)

        # Put different chars at same position
        bg.put(5, 2, "B")
        fg.put(5, 2, "F")

        # Composite and check
        result = pipeline.to_string()
        lines = result.split("\n")
        assert "F" in lines[2]  # Foreground should win

    def test_transparent_compositing(self):
        """Spaces in higher layers should show lower layers."""
        pipeline = RenderPipeline(10, 5)

        bg = pipeline.add_layer("background", priority=0)
        fg = pipeline.add_layer("foreground", priority=10)

        bg.put(5, 2, "B")
        # fg has space at 5,2 (default)

        result = pipeline.to_string()
        lines = result.split("\n")
        assert "B" in lines[2]  # Background should show through

    def test_to_string(self):
        pipeline = RenderPipeline(5, 2)
        layer = pipeline.add_layer("main", priority=0)

        layer.put(0, 0, "H")
        layer.put(1, 0, "I")

        result = pipeline.to_string()
        assert result.startswith("HI")
