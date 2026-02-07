"""Tests for click region system and mic icon rendering."""

from unittest.mock import MagicMock

import pytest

from clarvis.widget.click_regions import ClickRegion, ClickRegionManager
from clarvis.widget.renderer import FrameRenderer

# ── ClickRegionManager ──────────────────────────────────────────────


class TestClickRegionManager:
    def test_register_and_handle(self):
        socket = MagicMock()
        manager = ClickRegionManager(socket)
        handler = MagicMock()
        region = ClickRegion("test", 0, 0, 3, 1)

        manager.register(region, handler)

        assert manager._regions["test"] == region
        socket.send_command.assert_called()
        assert socket.send_command.call_args[0][0]["method"] == "set_click_regions"

        manager.handle_click("test")
        handler.assert_called_once()

    def test_unregister(self):
        socket = MagicMock()
        manager = ClickRegionManager(socket)
        manager.register(ClickRegion("test", 0, 0, 3, 1), MagicMock())
        manager.unregister("test")
        assert "test" not in manager._regions
        assert "test" not in manager._handlers

    def test_handle_unknown_noop(self):
        manager = ClickRegionManager(MagicMock())
        manager.handle_click("unknown")  # should not raise


# ── FrameRenderer Mic Icon ──────────────────────────────────────────


class TestFrameRendererMicIcon:
    def test_defaults_and_set_state(self):
        r = FrameRenderer(18, 10)
        assert (r._mic_visible, r._mic_enabled, r._mic_style) == (False, False, "bracket")

        r.set_mic_state(visible=True, enabled=True, style="dot")
        assert (r._mic_visible, r._mic_enabled, r._mic_style) == (True, True, "dot")

        # Invalid style falls back to bracket
        r.set_mic_state(visible=True, enabled=True, style="invalid")
        assert r._mic_style == "bracket"

    @pytest.mark.parametrize(
        "style, expected_col, expected_width",
        [("bracket", 15, 3), ("dot", 17, 1)],
    )
    def test_icon_position(self, style, expected_col, expected_width):
        r = FrameRenderer(18, 10)
        r.set_mic_state(visible=True, enabled=True, style=style)
        row, col, width = r.mic_icon_position()
        assert row == 9  # bar_y (7) + 2
        assert col == expected_col
        assert width == expected_width

    def test_render_states(self):
        r = FrameRenderer(18, 10)
        mic_row = r.bar_y + 2

        # Not visible → no icon
        r.set_mic_state(visible=False, enabled=True, style="bracket")
        rows, _ = r.render_grid()
        assert "[M]" not in rows[mic_row]

        # Visible + enabled
        r.set_mic_state(visible=True, enabled=True, style="bracket")
        rows_en, colors_en = r.render_grid()
        assert "[M]" in rows_en[mic_row]

        # Visible + disabled
        r.set_mic_state(visible=True, enabled=False, style="bracket")
        rows_dis, colors_dis = r.render_grid()
        assert "[·]" in rows_dis[mic_row]

        # Colors differ between enabled and disabled
        assert colors_en[mic_row] != colors_dis[mic_row]
