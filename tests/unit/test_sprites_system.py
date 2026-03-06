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


def test_face_rendering_and_status():
    """Face renders visible output, status drives animation, different statuses
    produce different frames."""
    scene = _build_scene()
    face = next(s for s in scene.registry.alive() if isinstance(s, FaceCel))

    # Phase 1: renders non-empty content
    out_c = np.full((17, 43), SPACE, dtype=np.uint32)
    out_k = np.zeros((17, 43), dtype=np.uint8)
    face.render(out_c, out_k)
    assert np.any(out_c != SPACE)

    # Phase 2: tick reads status from context
    face.tick(status="reading")
    assert face._current_animation == "reading"

    # Phase 3: different statuses produce different frame content
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


def test_weather_particle_system():
    """Smoke test: ticking with rain doesn't crash, and particles actually render."""
    scene = _build_scene()
    weather = next(s for s in scene.registry.alive() if isinstance(s, WeatherSandbox))

    # Phase 1: tick with weather params doesn't crash
    weather.tick(weather_type="rain", weather_intensity=0.5, wind_speed=1.0)

    # Phase 2: after several ticks, rain produces non-SPACE chars
    for _ in range(20):
        weather.tick(weather_type="rain", weather_intensity=0.8)
    out_c = np.full((17, 43), SPACE, dtype=np.uint32)
    out_k = np.zeros((17, 43), dtype=np.uint8)
    weather.render(out_c, out_k)
    assert np.any(out_c != SPACE)


def test_celestial_day_night_cycle():
    """Art data consistency, day/night rendering, and position varies with hour."""

    # Phase 1: art width consistency
    for line in CelestialCel.SUN_ART:
        assert len(line) == CelestialCel.CELESTIAL_WIDTH
    for line in CelestialCel.MOON_ART:
        assert len(line) == CelestialCel.CELESTIAL_WIDTH

    # Phase 2: renders sun during day
    scene = _build_scene()
    celestial = next(s for s in scene.registry.alive() if isinstance(s, CelestialCel))
    out_c = np.full((17, 43), SPACE, dtype=np.uint32)
    out_k = np.zeros((17, 43), dtype=np.uint8)
    celestial.tick(hour=12)
    celestial.render(out_c, out_k)
    assert np.any(out_c[:3, :] != SPACE)

    # Phase 3: renders moon at night
    out_c = np.full((17, 43), SPACE, dtype=np.uint32)
    out_k = np.zeros((17, 43), dtype=np.uint8)
    celestial.tick(hour=23)
    celestial.render(out_c, out_k)
    assert np.any(out_c[:3, :] != SPACE)

    # Phase 4: position varies with hour
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


def test_bar_fill_rendering():
    """Bar at 50% should have both filled (#) and empty (-) chars."""
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


def test_mic_control_wiring():
    """Mic sprite is a Control with the correct action_id."""
    scene = _build_scene()
    mic = next(s for s in scene.registry.alive() if isinstance(s, Control))
    assert mic.action_id == "mic_toggle"


def test_full_scene_from_cv_files():
    """Build from .cv files -> verify sprite count -> tick and render -> verify priorities."""
    scene = _build_scene()

    # Phase 1: correct sprite count
    sprites = scene.registry.alive()
    assert len(sprites) == 6

    # Phase 2: tick and render without crash
    scene.tick(
        status="idle",
        context_percent=50.0,
        weather_type="clear",
        hour=12,
    )
    rows, colors = scene.to_grid()
    assert len(rows) == 17
    assert all(len(r) == 43 for r in rows)

    # Phase 3: priorities are sorted and include expected values
    sprites = scene.registry.alive()
    priorities = [s.priority for s in sprites]
    assert priorities == sorted(priorities)
    assert WEATHER in priorities
    assert AVATAR in priorities
