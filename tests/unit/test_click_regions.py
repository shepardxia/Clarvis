"""Tests for click region system and mic icon rendering."""

from unittest.mock import MagicMock

import pytest

from clarvis.widget.click_regions import ClickRegion, ClickRegionManager
from clarvis.widget.renderer import FrameRenderer


# ── ClickRegionManager ──────────────────────────────────────────────────

class TestClickRegionManager:
    def test_register_stores_region_and_handler(self):
        socket = MagicMock()
        manager = ClickRegionManager(socket)
        region = ClickRegion("test", 0, 0, 3, 1)
        handler = MagicMock()

        manager.register(region, handler)

        assert manager._regions["test"] == region
        assert manager._handlers["test"] == handler

    def test_register_pushes_regions(self):
        socket = MagicMock()
        manager = ClickRegionManager(socket)
        region = ClickRegion("test", 0, 0, 3, 1)

        manager.register(region, MagicMock())

        socket.send_command.assert_called()
        call_args = socket.send_command.call_args[0][0]
        assert call_args["method"] == "set_click_regions"
        assert len(call_args["params"]["regions"]) == 1

    def test_unregister_removes_region(self):
        socket = MagicMock()
        manager = ClickRegionManager(socket)
        region = ClickRegion("test", 0, 0, 3, 1)
        manager.register(region, MagicMock())

        manager.unregister("test")

        assert "test" not in manager._regions
        assert "test" not in manager._handlers

    def test_handle_click_calls_handler(self):
        socket = MagicMock()
        manager = ClickRegionManager(socket)
        handler = MagicMock()
        region = ClickRegion("test", 0, 0, 3, 1)
        manager.register(region, handler)

        manager.handle_click("test")

        handler.assert_called_once()

    def test_handle_click_unknown_region(self):
        socket = MagicMock()
        manager = ClickRegionManager(socket)

        # Should not raise
        manager.handle_click("unknown")

    def test_multiple_regions(self):
        socket = MagicMock()
        manager = ClickRegionManager(socket)
        regions = [
            ClickRegion("mic", 9, 15, 3, 1),
            ClickRegion("button", 5, 5, 5, 1),
        ]
        handlers = [MagicMock(), MagicMock()]

        for region, handler in zip(regions, handlers):
            manager.register(region, handler)

        assert len(manager._regions) == 2
        manager.handle_click("mic")
        handlers[0].assert_called_once()
        handlers[1].assert_not_called()


# ── FrameRenderer Mic Icon ──────────────────────────────────────────────

class TestFrameRendererMicIcon:
    def test_mic_state_defaults(self):
        renderer = FrameRenderer(18, 10)
        assert renderer._mic_visible is False
        assert renderer._mic_enabled is False
        assert renderer._mic_style == "bracket"

    def test_set_mic_state(self):
        renderer = FrameRenderer(18, 10)
        renderer.set_mic_state(visible=True, enabled=True, style="dot")

        assert renderer._mic_visible is True
        assert renderer._mic_enabled is True
        assert renderer._mic_style == "dot"

    def test_mic_icon_position_bracket(self):
        renderer = FrameRenderer(18, 10)
        renderer.set_mic_state(visible=True, enabled=True, style="bracket")
        row, col, width = renderer.mic_icon_position()

        assert row == 9  # bar_y (7) + 2
        assert col == 15  # width (18) - icon_width (3)
        assert width == 3  # "[M]" is 3 chars

    def test_mic_icon_position_dot(self):
        renderer = FrameRenderer(18, 10)
        renderer.set_mic_state(visible=True, enabled=True, style="dot")
        row, col, width = renderer.mic_icon_position()

        assert row == 9  # bar_y (7) + 2
        assert col == 17  # width (18) - icon_width (1)
        assert width == 1

    def test_mic_icon_render_visible_enabled(self):
        renderer = FrameRenderer(18, 10)
        renderer.set_mic_state(visible=True, enabled=True, style="bracket")

        # Render and check that mic_layer has content
        rows, cell_colors = renderer.render_grid()

        # The icon should be visible at the mic row (bar_y + 2 = 9 for 18x10)
        mic_row = renderer.bar_y + 2
        assert "[M]" in rows[mic_row]

    def test_mic_icon_render_visible_disabled(self):
        renderer = FrameRenderer(18, 10)
        renderer.set_mic_state(visible=True, enabled=False, style="bracket")

        rows, cell_colors = renderer.render_grid()

        # The disabled icon should be visible
        mic_row = renderer.bar_y + 2
        assert "[·]" in rows[mic_row]

    def test_mic_icon_render_not_visible(self):
        renderer = FrameRenderer(18, 10)
        renderer.set_mic_state(visible=False, enabled=True, style="bracket")

        rows, cell_colors = renderer.render_grid()

        # Icon should not appear at the mic position
        mic_row = renderer.bar_y + 2
        assert "[M]" not in rows[mic_row]

    def test_mic_icon_invalid_style_defaults_to_bracket(self):
        renderer = FrameRenderer(18, 10)
        renderer.set_mic_state(visible=True, enabled=True, style="invalid")

        assert renderer._mic_style == "bracket"

    def test_mic_colors_enabled_vs_disabled(self):
        renderer = FrameRenderer(18, 10)
        renderer.set_mic_state(visible=True, enabled=True, style="bracket")
        rows1, colors1 = renderer.render_grid()

        renderer.set_mic_state(visible=True, enabled=False, style="bracket")
        rows2, colors2 = renderer.render_grid()

        # Mic row colors should differ between enabled/disabled
        # Enabled uses color 0, disabled uses ANSI 240
        mic_row = renderer.bar_y + 2
        mic_colors1 = colors1[mic_row] if colors1 else []
        mic_colors2 = colors2[mic_row] if colors2 else []

        # At least one color should be different (the mic icon color)
        assert mic_colors1 != mic_colors2
