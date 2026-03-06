"""Tests for SceneBuilder — specs → sprites."""

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
from clarvis.display.sprites.system import BarSprite, FaceCel


class TestFaceCelFromSpecs:
    def _make_palette(self):
        return PaletteSpec(
            name="test",
            eyes={"open": "◕", "closed": "─", "half": "◔"},
            mouths={"smile": "◡", "neutral": "─"},
            borders={"thin": "─", "medium": "━"},
            corners={"round": ["╭", "╮", "╰", "╯"]},
            substrates={"idle": " .  .  . "},
            presets={"happy": PresetSpec(eyes="open", mouth="smile", border="thin")},
        )

    def _make_template(self):
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

    def _make_sequence(self):
        return SequenceSpec(
            name="idle",
            frames=[
                FrameRef(preset="happy"),
                FrameRef(inline=PresetSpec(eyes="closed", mouth="smile", border="thin")),
            ],
        )

    def test_construct_from_specs(self):
        face = FaceCel.from_specs(
            template=self._make_template(),
            palette=self._make_palette(),
            sequences={"idle": self._make_sequence()},
            x=5,
            y=3,
        )
        assert face.width == 11  # default box_face at standard size
        assert face.height == 5

    def test_renders_non_empty(self):
        face = FaceCel.from_specs(
            template=self._make_template(),
            palette=self._make_palette(),
            sequences={"idle": self._make_sequence()},
            x=0,
            y=0,
        )
        out_c = np.full((5, 11), SPACE, dtype=np.uint32)
        out_k = np.zeros((5, 11), dtype=np.uint8)
        face.render(out_c, out_k)
        assert np.any(out_c != SPACE)

    def test_scales_with_dimensions(self):
        """Larger dimensions should produce a larger face."""
        face = FaceCel.from_specs(
            template=self._make_template(),
            palette=self._make_palette(),
            sequences={"idle": self._make_sequence()},
            x=0,
            y=0,
            width=15,
            height=7,
        )
        assert face.width == 15
        assert face.height == 7
        out_c = np.full((7, 15), SPACE, dtype=np.uint32)
        out_k = np.zeros((7, 15), dtype=np.uint8)
        face.render(out_c, out_k)
        # Should have border chars in corners
        assert out_c[0, 0] != SPACE  # top-left corner
        assert out_c[6, 14] != SPACE  # bottom-right corner

    def test_set_status_with_specs(self):
        face = FaceCel.from_specs(
            template=self._make_template(),
            palette=self._make_palette(),
            sequences={"idle": self._make_sequence(), "thinking": self._make_sequence()},
            x=0,
            y=0,
        )
        face.set_status("thinking")
        assert face._current_animation == "thinking"


class TestSceneBuilder:
    def _make_registry(self, tmp_path):
        """Write minimal .cv files and return a loaded registry."""
        (tmp_path / "scene.cv").write_text("""
            scene default 43x17 {
                weather fullscreen priority=0
                celestial top priority=1
                face center priority=50 {
                    skin classic
                }
                bar below(face, gap=1) width=0.65 priority=80
                mic right(bar, gap=1) priority=92
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

    def test_builds_scene(self, tmp_path):
        reg = self._make_registry(tmp_path)
        scene = SceneBuilder.build(reg, scene_name="default")
        sprites = scene.registry.alive()
        assert len(sprites) == 6

    def test_face_is_centered(self, tmp_path):
        reg = self._make_registry(tmp_path)
        scene = SceneBuilder.build(reg, scene_name="default")
        face = next(s for s in scene.registry.alive() if isinstance(s, FaceCel))
        # Centered in 43-wide canvas: (43 - 11) // 2 = 16
        assert face.bbox.x == 16

    def test_bar_below_face(self, tmp_path):
        reg = self._make_registry(tmp_path)
        scene = SceneBuilder.build(reg, scene_name="default")
        face = next(s for s in scene.registry.alive() if isinstance(s, FaceCel))
        bar = next(s for s in scene.registry.alive() if isinstance(s, BarSprite))
        assert bar.bbox.y == face.bbox.y2 + 1  # gap=1

    def test_tick_and_render(self, tmp_path):
        reg = self._make_registry(tmp_path)
        scene = SceneBuilder.build(reg, scene_name="default")
        scene.tick(status="idle", context_percent=50.0, weather_type="clear", hour=12)
        rows, colors = scene.to_grid()
        assert len(rows) == 17
        assert all(len(r) == 43 for r in rows)

    def test_priorities_sorted(self, tmp_path):
        reg = self._make_registry(tmp_path)
        scene = SceneBuilder.build(reg, scene_name="default")
        priorities = [s.priority for s in scene.registry.alive()]
        assert priorities == sorted(priorities)


class TestOnBlockIntegration:
    def test_on_block_changes_property(self, tmp_path):
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
        # on_map should have face's on blocks
        assert len(on_map) > 0

    def test_evaluate_on_blocks_in_tick(self, tmp_path):
        from clarvis.display.cv.runtime import evaluate_on_blocks
        from clarvis.display.cv.specs import OnBlock, OnCase

        blocks = [
            OnBlock(
                context_key="status",
                cases=[OnCase(match="resting", overrides={"scale": 0.8})],
            )
        ]
        result = evaluate_on_blocks(blocks, {"status": "resting"})
        assert result["scale"] == 0.8


class TestHotReload:
    def test_reload_picks_up_changes(self, tmp_path):
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

        # Change palette
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
        reg.load()  # reload
        assert reg.get_palette("classic").eyes["open"] == "◕"


class TestDaemonIntegration:
    def test_build_from_config_dimensions(self):
        """SceneBuilder respects config dimensions."""
        pkg_dir = Path(__file__).parents[2] / "clarvis" / "display" / "elements"
        reg = CvRegistry(pkg_dir)
        reg.load()
        scene = SceneBuilder.build(reg, scene_name="default", width=29, height=12)
        assert scene.width == 29
        assert scene.height == 12


class TestProductionCvFiles:
    """Test that the actual .cv files in display/elements/ produce a working scene."""

    def test_production_scene_builds(self):
        pkg_dir = Path(__file__).parents[2] / "clarvis" / "display" / "elements"
        reg = CvRegistry(pkg_dir)
        reg.load()
        scene = SceneBuilder.build(reg, scene_name="default")
        sprites = scene.registry.alive()
        assert len(sprites) == 6

    def test_production_scene_renders(self):
        pkg_dir = Path(__file__).parents[2] / "clarvis" / "display" / "elements"
        reg = CvRegistry(pkg_dir)
        reg.load()
        scene = SceneBuilder.build(reg, scene_name="default")
        scene.tick(status="idle", context_percent=50.0, weather_type="clear", hour=12)
        rows, colors = scene.to_grid()
        assert len(rows) == 17
        non_space = sum(1 for r in rows for c in r if c != " ")
        assert non_space > 20  # face + bar at minimum

    def test_all_statuses_have_sequences(self):
        pkg_dir = Path(__file__).parents[2] / "clarvis" / "display" / "elements"
        reg = CvRegistry(pkg_dir)
        reg.load()
        required = [
            "idle",
            "thinking",
            "reading",
            "writing",
            "executing",
            "running",
            "reviewing",
            "awaiting",
            "resting",
            "offline",
        ]
        seqs = reg.query_sequences(tags=["classic"])
        seq_names = {s.name for s in seqs}
        for name in required:
            assert name in seq_names, f"Missing sequence: {name}"
