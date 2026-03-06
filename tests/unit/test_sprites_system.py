"""Tests for sprites/system.py — system sprites and SceneBuilder-driven scenes."""

from pathlib import Path

import numpy as np

from clarvis.display.cv.builder import SceneBuilder
from clarvis.display.cv.registry import CvRegistry
from clarvis.display.sprites.control import Control
from clarvis.display.sprites.core import SPACE
from clarvis.display.sprites.system import (
    AVATAR,
    WEATHER,
    BarSprite,
    CelestialCel,
    FaceCel,
    WeatherSandbox,
)

_ELEMENTS_DIR = Path(__file__).parents[2] / "clarvis" / "display" / "elements"


def _build_scene(width=43, height=17):
    reg = CvRegistry(_ELEMENTS_DIR)
    reg.load()
    return SceneBuilder.build(reg, scene_name="default", width=width, height=height)


class TestFaceCel:
    def test_renders_non_empty(self):
        scene = _build_scene()
        face = next(s for s in scene.registry.alive() if isinstance(s, FaceCel))
        out_c = np.full((17, 43), SPACE, dtype=np.uint32)
        out_k = np.zeros((17, 43), dtype=np.uint8)
        face.render(out_c, out_k)
        assert np.any(out_c != SPACE)

    def test_bbox_correct(self):
        scene = _build_scene()
        face = next(s for s in scene.registry.alive() if isinstance(s, FaceCel))
        b = face.bbox
        assert b.w == 11
        assert b.h == 5

    def test_set_status_switches_animation(self):
        scene = _build_scene()
        face = next(s for s in scene.registry.alive() if isinstance(s, FaceCel))
        face.set_status("thinking")
        assert face._current_animation == "thinking"

    def test_tick_reads_status_from_ctx(self):
        scene = _build_scene()
        face = next(s for s in scene.registry.alive() if isinstance(s, FaceCel))
        face.tick(status="reading")
        assert face._current_animation == "reading"

    def test_face_has_border_chars(self):
        """Face frame should contain border characters like ╭ and │."""
        scene = _build_scene()
        face = next(s for s in scene.registry.alive() if isinstance(s, FaceCel))
        out_c = np.full((17, 43), SPACE, dtype=np.uint32)
        out_k = np.zeros((17, 43), dtype=np.uint8)
        face.render(out_c, out_k)
        b = face.bbox
        region = out_c[b.y : b.y2, b.x : b.x2]
        chars = {chr(c) for c in region.flat if c != SPACE}
        assert "╭" in chars or "┌" in chars  # top-left corner
        assert "│" in chars  # vertical edge

    def test_different_statuses_different_frames(self):
        """Different statuses should produce different frame content."""
        scene = _build_scene()
        face = next(s for s in scene.registry.alive() if isinstance(s, FaceCel))
        b = face.bbox

        out1 = np.full((17, 43), SPACE, dtype=np.uint32)
        face.set_status("idle")
        face.render(out1, np.zeros((17, 43), dtype=np.uint8))
        region1 = out1[b.y : b.y2, b.x : b.x2].copy()

        out2 = np.full((17, 43), SPACE, dtype=np.uint32)
        face.set_status("thinking")
        face.render(out2, np.zeros((17, 43), dtype=np.uint8))
        region2 = out2[b.y : b.y2, b.x : b.x2].copy()

        assert not np.array_equal(region1, region2)


class TestWeatherSandbox:
    def test_is_opaque(self):
        scene = _build_scene()
        weather = next(s for s in scene.registry.alive() if isinstance(s, WeatherSandbox))
        assert weather.transparent is False

    def test_tick_no_crash(self):
        scene = _build_scene()
        weather = next(s for s in scene.registry.alive() if isinstance(s, WeatherSandbox))
        weather.tick(weather_type="rain", weather_intensity=0.5, wind_speed=1.0)

    def test_render_no_crash(self):
        scene = _build_scene()
        weather = next(s for s in scene.registry.alive() if isinstance(s, WeatherSandbox))
        weather.tick(weather_type="rain", weather_intensity=0.5)
        out_c = np.full((17, 43), SPACE, dtype=np.uint32)
        out_k = np.zeros((17, 43), dtype=np.uint8)
        weather.render(out_c, out_k)

    def test_rain_renders_particles(self):
        """After several ticks of rain, some non-SPACE chars should appear."""
        scene = _build_scene()
        weather = next(s for s in scene.registry.alive() if isinstance(s, WeatherSandbox))
        for _ in range(20):
            weather.tick(weather_type="rain", weather_intensity=0.8)
        out_c = np.full((17, 43), SPACE, dtype=np.uint32)
        out_k = np.zeros((17, 43), dtype=np.uint8)
        weather.render(out_c, out_k)
        assert np.any(out_c != SPACE)

    def test_exclusion_zones_from_registry(self):
        scene = _build_scene()
        weather = next(s for s in scene.registry.alive() if isinstance(s, WeatherSandbox))
        assert weather._scene_registry is scene.registry


class TestCelestialCel:
    def test_art_width_consistency(self):
        for line in CelestialCel.SUN_ART:
            assert len(line) == CelestialCel.CELESTIAL_WIDTH
        for line in CelestialCel.MOON_ART:
            assert len(line) == CelestialCel.CELESTIAL_WIDTH

    def test_renders_sun_during_day(self):
        scene = _build_scene()
        celestial = next(s for s in scene.registry.alive() if isinstance(s, CelestialCel))
        out_c = np.full((17, 43), SPACE, dtype=np.uint32)
        out_k = np.zeros((17, 43), dtype=np.uint8)
        celestial.tick(hour=12)
        celestial.render(out_c, out_k)
        assert np.any(out_c[:3, :] != SPACE)

    def test_renders_moon_at_night(self):
        scene = _build_scene()
        celestial = next(s for s in scene.registry.alive() if isinstance(s, CelestialCel))
        out_c = np.full((17, 43), SPACE, dtype=np.uint32)
        out_k = np.zeros((17, 43), dtype=np.uint8)
        celestial.tick(hour=23)
        celestial.render(out_c, out_k)
        assert np.any(out_c[:3, :] != SPACE)

    def test_position_varies_with_hour(self):
        scene = _build_scene()
        celestial = next(s for s in scene.registry.alive() if isinstance(s, CelestialCel))

        out_morning = np.full((17, 43), SPACE, dtype=np.uint32)
        out_evening = np.full((17, 43), SPACE, dtype=np.uint32)
        ok = np.zeros((17, 43), dtype=np.uint8)

        celestial.tick(hour=7)
        celestial.render(out_morning, ok.copy())
        celestial.tick(hour=18)
        celestial.render(out_evening, ok.copy())

        morning_cols = np.where(out_morning[0, :] != SPACE)[0]
        evening_cols = np.where(out_evening[0, :] != SPACE)[0]
        if len(morning_cols) > 0 and len(evening_cols) > 0:
            assert morning_cols[0] < evening_cols[0]


class TestBarSprite:
    def test_writes_one_row(self):
        scene = _build_scene()
        bar = next(s for s in scene.registry.alive() if isinstance(s, BarSprite))
        b = bar.bbox
        assert b.h == 1

    def test_tick_updates_percent(self):
        scene = _build_scene()
        bar = next(s for s in scene.registry.alive() if isinstance(s, BarSprite))
        bar.tick(context_percent=75.0)
        assert bar._percent == 75.0

    def test_bar_at_50_has_filled_and_empty(self):
        """Bar at 50% should have both # (filled) and - (empty) chars."""
        scene = _build_scene()
        bar = next(s for s in scene.registry.alive() if isinstance(s, BarSprite))
        bar.tick(context_percent=50.0)
        out_c = np.full((17, 43), SPACE, dtype=np.uint32)
        out_k = np.zeros((17, 43), dtype=np.uint8)
        bar.render(out_c, out_k)
        b = bar.bbox
        row = out_c[b.y, b.x : b.x2]
        assert ord("#") in row
        assert ord("-") in row


class TestMicControl:
    def test_mic_is_control(self):
        scene = _build_scene()
        mic = next(s for s in scene.registry.alive() if isinstance(s, Control))
        assert mic.action_id == "mic_toggle"

    def test_mic_invisible_by_default(self):
        scene = _build_scene()
        mic = next(s for s in scene.registry.alive() if isinstance(s, Control))
        assert mic._visible is False


class TestSceneBuilderScene:
    def test_sprite_count(self):
        scene = _build_scene()
        sprites = scene.registry.alive()
        assert len(sprites) == 6

    def test_tick_and_render_no_crash(self):
        scene = _build_scene()
        scene.tick(
            status="idle",
            context_percent=50.0,
            weather_type="clear",
            hour=12,
        )
        rows, colors = scene.to_grid()
        assert len(rows) == 17
        assert all(len(r) == 43 for r in rows)

    def test_priorities_correct(self):
        scene = _build_scene()
        sprites = scene.registry.alive()
        priorities = [s.priority for s in sprites]
        assert priorities == sorted(priorities)
        assert WEATHER in priorities
        assert AVATAR in priorities

    def test_face_renders_in_output(self):
        scene = _build_scene()
        scene.tick(status="idle", context_percent=0, weather_type="clear", hour=12)
        rows, _ = scene.to_grid()
        avatar_rows = rows[5:10]
        non_space = sum(1 for r in avatar_rows for c in r if c != " ")
        assert non_space > 0
