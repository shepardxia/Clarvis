"""Tests for SceneBuilder — specs to sprites."""

from pathlib import Path

import numpy as np

from clarvis.display.cv.builder import SceneBuilder
from clarvis.display.cv.registry import CvRegistry
from clarvis.display.cv.specs import (
    FrameRef,
    PaletteSpec,
    PresetSpec,
    SequenceSpec,
    TemplateSpec,
)
from clarvis.display.sprites.core import SPACE
from clarvis.display.sprites.system import FaceCel


def _make_palette():
    return PaletteSpec(
        name="test",
        eyes={"open": "◕", "closed": "─", "half": "◔"},
        mouths={"smile": "◡", "neutral": "─"},
        borders={"thin": "─", "medium": "━"},
        corners={"round": ["╭", "╮", "╰", "╯"]},
        substrates={"idle": " .  .  . "},
        presets={"happy": PresetSpec(eyes="open", mouth="smile", border="thin")},
    )


def _make_template():
    return TemplateSpec(
        name="box_face",
        edge="│",
        default_corners="round",
        eyes_row=0.0,
        eyes_cols=[0.33, 0.56],
        mouth_row=0.5,
        mouth_col=0.5,
        substrate_row=1.0,
    )


def _make_sequence():
    return SequenceSpec(
        name="idle",
        frames=[
            FrameRef(preset="happy"),
            FrameRef(inline=PresetSpec(eyes="closed", mouth="smile", border="thin")),
        ],
    )


def _make_scene_registry(tmp_path):
    """Write minimal .cv files and return a loaded registry."""
    (tmp_path / "scene.cv").write_text("""
        scene default 43x17 {
            weather fullscreen priority=0
            celestial top priority=1
            face center priority=50 {
                skin classic
            }
            mic bottom_right priority=92
            voice bottom width=1.0 priority=95
        }
    """)
    (tmp_path / "classic.cv").write_text("""
        template box_face {
            edge "│"
            default_corners round
            eyes row=0.0 cols=[0.33 0.56]
            mouth row=0.5 col=0.5
            substrate row=1.0
        }
        palette classic {
            tags [classic]
            eyes { open "◕"  closed "─"  half "◔"  sparkle "✧"  left "◐"  right "◑" }
            mouths { smile "◡"  neutral "─"  open "○"  soft "‿"  hmm "∪"  grin "◠" }
            borders { thin "─"  medium "━"  thick "═"  sparkle "✧"  star "✦"
                      dotted "┉"  arrow "▸" }
            corners { round ["╭" "╮" "╰" "╯"]  heavy ["┏" "┓" "┗" "┛"] }
            substrates { idle " .  .  . "  thinking " * . * . " }
            presets {
                happy { eyes=open mouth=smile border=thin }
                neutral { eyes=open mouth=neutral border=thin }
                pondering { eyes=open mouth=neutral border=medium corners=heavy }
            }
        }
        sequence idle {
            tags [classic]
            define rest [ happy happy happy happy ]
            frames [ $rest ]
        }
        sequence thinking {
            tags [classic]
            frames [ pondering pondering ]
        }
    """)
    reg = CvRegistry(tmp_path)
    reg.load()
    return reg


def test_face_cel_construction_from_specs():
    """Build FaceCel from specs, verify dimensions, rendering, and scaling."""

    # construct and verify default dimensions
    face = FaceCel.from_specs(
        template=_make_template(),
        palette=_make_palette(),
        sequences={"idle": _make_sequence()},
        x=5,
        y=3,
    )
    assert face.width == 11
    assert face.height == 5

    # renders visible content (not all spaces)
    face_at_origin = FaceCel.from_specs(
        template=_make_template(),
        palette=_make_palette(),
        sequences={"idle": _make_sequence()},
        x=0,
        y=0,
    )
    out_c = np.full((5, 11), SPACE, dtype=np.uint32)
    out_k = np.zeros((5, 11), dtype=np.uint8)
    face_at_origin.render(out_c, out_k)
    assert np.any(out_c != SPACE)

    # scales with larger dimensions
    face_large = FaceCel.from_specs(
        template=_make_template(),
        palette=_make_palette(),
        sequences={"idle": _make_sequence()},
        x=0,
        y=0,
        width=15,
        height=7,
    )
    assert face_large.width == 15
    assert face_large.height == 7
    out_c = np.full((7, 15), SPACE, dtype=np.uint32)
    out_k = np.zeros((7, 15), dtype=np.uint8)
    face_large.render(out_c, out_k)
    assert out_c[0, 0] != SPACE  # top-left corner
    assert out_c[6, 14] != SPACE  # bottom-right corner


def test_scene_builder_layout(tmp_path):
    """Build scene, verify sprite count, centering, render, and priority order."""
    reg = _make_scene_registry(tmp_path)
    scene = SceneBuilder.build(reg, scene_name="default")
    sprites = scene.registry.alive()

    # sprite count
    assert len(sprites) == 5

    # face is centered in 43-wide canvas: (43 - 11) // 2 = 16
    face = next(s for s in sprites if isinstance(s, FaceCel))
    assert face.bbox.x == 16

    # tick and render produces correct grid dimensions
    scene.tick(status="idle", weather_type="clear", hour=12)
    rows, colors = scene.to_grid()
    assert len(rows) == 17
    assert all(len(r) == 43 for r in rows)

    # priorities are sorted ascending
    priorities = [s.priority for s in scene.registry.alive()]
    assert priorities == sorted(priorities)


def test_on_block_changes_property(tmp_path):
    """On-blocks parsed from .cv files are available via build_with_on_blocks."""
    (tmp_path / "scene.cv").write_text("""
        scene default 20x10 {
            face center priority=50 {
                skin classic
                on status {
                    resting { scale 0.8 }
                }
            }
        }
    """)
    (tmp_path / "skin.cv").write_text("""
        palette classic {
            tags [classic]
            eyes { open "o" }
            mouths { smile "u" }
            borders { thin "-" }
            presets {
                happy { eyes=open mouth=smile border=thin }
            }
        }
        template box_face {
            edge "|"
            default_corners round
            eyes row=0.0 cols=[0.33 0.56]
            mouth row=0.5 col=0.5
            substrate row=1.0
        }
        sequence idle {
            tags [classic]
            frames [ happy ]
        }
        sequence resting {
            tags [classic]
            frames [ happy ]
        }
    """)
    reg = CvRegistry(tmp_path)
    reg.load()
    scene, on_map = SceneBuilder.build_with_on_blocks(reg, scene_name="default")
    assert len(on_map) > 0


def test_hot_reload(tmp_path):
    """Registry reload picks up changes to .cv files."""
    (tmp_path / "scene.cv").write_text("""
        scene default 20x10 {
            face center priority=50
        }
    """)
    (tmp_path / "skin.cv").write_text("""
        palette classic {
            tags [classic]
            eyes { open "o" }
            mouths { smile "u" }
            borders { thin "-" }
        }
        template box_face {
            edge "|"
            default_corners round
            eyes row=0.0 cols=[0.33 0.56]
            mouth row=0.5 col=0.5
            substrate row=1.0
        }
        sequence idle {
            tags [classic]
            frames [ {eyes=open mouth=smile border=thin} ]
        }
    """)
    reg = CvRegistry(tmp_path)
    reg.load()
    assert reg.get_palette("classic").eyes["open"] == "o"

    # change palette and reload
    (tmp_path / "skin.cv").write_text("""
        palette classic {
            tags [classic]
            eyes { open "◕" }
            mouths { smile "◡" }
            borders { thin "─" }
        }
        template box_face {
            edge "│"
            default_corners round
            eyes row=0.0 cols=[0.33 0.56]
            mouth row=0.5 col=0.5
            substrate row=1.0
        }
        sequence idle {
            tags [classic]
            frames [ {eyes=open mouth=smile border=thin} ]
        }
    """)
    reg.load()
    assert reg.get_palette("classic").eyes["open"] == "◕"


def test_production_cv_files():
    """Production .cv files build, render, and cover all required statuses."""
    pkg_dir = Path(__file__).parents[2] / "clarvis" / "display" / "elements"
    reg = CvRegistry(pkg_dir)
    reg.load()

    # build with custom config dimensions
    scene_custom = SceneBuilder.build(reg, scene_name="default", width=29, height=12)
    assert scene_custom.width == 29
    assert scene_custom.height == 12

    # smoke test: default build produces expected sprites
    scene = SceneBuilder.build(reg, scene_name="default")
    sprites = scene.registry.alive()
    assert len(sprites) == 5

    # renders with visible content
    scene.tick(status="idle", weather_type="clear", hour=12)
    rows, colors = scene.to_grid()
    assert len(rows) == 17
    non_space = sum(1 for r in rows for c in r if c != " ")
    assert non_space > 20  # face at minimum

    # all required statuses have classic sequences
    required = [
        "idle",
        "thinking",
        "reading",
        "writing",
        "executing",
        "running",
        "reviewing",
        "resting",
        "offline",
    ]
    seqs = reg.query_sequences(tags=["classic"])
    seq_names = {s.name for s in seqs}
    for name in required:
        assert name in seq_names, f"Missing sequence: {name}"
