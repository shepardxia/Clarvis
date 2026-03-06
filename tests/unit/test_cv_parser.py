"""Tests for .cv Lark grammar and parser."""

from pathlib import Path

from lark import Lark

from clarvis.display.cv.parser import parse_cv
from clarvis.display.cv.specs import PaletteSpec, SceneSpec, SequenceSpec, TemplateSpec

GRAMMAR = (Path(__file__).parents[2] / "clarvis" / "display" / "cv" / "grammar.lark").read_text()


class TestGrammarParses:
    """Verify the grammar accepts valid .cv syntax without errors."""

    def _parse(self, text: str):
        parser = Lark(GRAMMAR, parser="earley", start="start")
        return parser.parse(text)

    def test_palette_block(self):
        tree = self._parse("""
            palette classic {
                tags [classic]
                eyes { open "◕"  closed "─" }
                mouths { smile "◡" }
                borders { thin "─" }
                corners { round ["╭" "╮" "╰" "╯"] }
                substrates { idle " .  .  . " }
                presets {
                    happy { eyes=open mouth=smile border=thin }
                }
            }
        """)
        assert tree.data == "start"

    def test_template_block(self):
        tree = self._parse("""
            template box_face {
                edge "│"
                default_corners round
                eyes row=0.0 cols=[0.33 0.56]
                mouth row=0.5 col=0.5
                substrate row=1.0
            }
        """)
        assert tree.data == "start"

    def test_sequence_block(self):
        tree = self._parse("""
            sequence idle {
                tags [classic]
                define blink [ {eyes=half} {eyes=closed} ]
                define rest [ happy happy ]
                frames [ $rest $blink happy ]
            }
        """)
        assert tree.data == "start"

    def test_scene_block(self):
        tree = self._parse("""
            scene default 43x17 {
                weather fullscreen priority=0
                face center priority=50 {
                    skin classic
                }
                bar below(face, gap=1) width=0.65 priority=80
            }
        """)
        assert tree.data == "start"

    def test_on_blocks(self):
        tree = self._parse("""
            scene default 43x17 {
                face center priority=50 {
                    skin classic
                    on status {
                        resting { scale 0.8 }
                        excited { scale 1.2 }
                    }
                }
            }
        """)
        assert tree.data == "start"

    def test_multiple_blocks_in_one_file(self):
        tree = self._parse("""
            template box_face {
                edge "│"
                default_corners round
                eyes row=0.0 cols=[0.33 0.56]
                mouth row=0.5 col=0.5
                substrate row=1.0
            }
            palette classic {
                eyes { open "◕" }
                mouths { smile "◡" }
                borders { thin "─" }
            }
            sequence idle {
                frames [ {eyes=open mouth=smile border=thin} ]
            }
        """)
        assert tree.data == "start"

    def test_comments_ignored(self):
        tree = self._parse("""
            # This is a comment
            palette test {
                eyes { open "◕" }  # inline comment
                mouths { smile "◡" }
                borders { thin "─" }
            }
        """)
        assert tree.data == "start"


class TestParser:
    def test_parse_palette(self):
        blocks = parse_cv("""
            palette classic {
                tags [classic]
                eyes { open "◕"  closed "─" }
                mouths { smile "◡" }
                borders { thin "─" }
                corners { round ["╭" "╮" "╰" "╯"] }
                substrates { idle " .  .  . " }
                presets {
                    happy { eyes=open mouth=smile border=thin }
                }
            }
        """)
        palettes = [b for b in blocks if isinstance(b, PaletteSpec)]
        assert len(palettes) == 1
        p = palettes[0]
        assert p.name == "classic"
        assert p.tags == ["classic"]
        assert p.eyes["open"] == "◕"
        assert p.corners["round"] == ["╭", "╮", "╰", "╯"]
        assert p.presets["happy"].eyes == "open"

    def test_parse_template(self):
        blocks = parse_cv("""
            template box_face {
                edge "│"
                default_corners round
                eyes row=0.0 cols=[0.33 0.56]
                mouth row=0.5 col=0.5
                substrate row=1.0
            }
        """)
        templates = [b for b in blocks if isinstance(b, TemplateSpec)]
        assert len(templates) == 1
        t = templates[0]
        assert t.name == "box_face"
        assert t.edge == "│"
        assert t.eyes_row == 0.0
        assert t.eyes_cols == [0.33, 0.56]

    def test_parse_sequence(self):
        blocks = parse_cv("""
            sequence idle {
                tags [classic]
                define blink [ {eyes=half} {eyes=closed} ]
                define rest [ happy happy ]
                frames [ $rest $blink happy ]
            }
        """)
        seqs = [b for b in blocks if isinstance(b, SequenceSpec)]
        assert len(seqs) == 1
        s = seqs[0]
        assert s.name == "idle"
        assert "blink" in s.defines
        assert len(s.frames) == 3
        assert s.frames[0].define_ref == "rest"
        assert s.frames[2].preset == "happy"

    def test_parse_scene(self):
        blocks = parse_cv("""
            scene default 43x17 {
                weather fullscreen priority=0
                face center priority=50 {
                    skin classic
                }
                bar below(face, gap=1) width=0.65 priority=80
            }
        """)
        scenes = [b for b in blocks if isinstance(b, SceneSpec)]
        assert len(scenes) == 1
        sc = scenes[0]
        assert sc.width == 43
        assert sc.height == 17
        assert len(sc.sprites) == 3
        assert sc.sprites[0].type == "weather"
        assert sc.sprites[0].placement.kind == "fullscreen"
        assert sc.sprites[1].properties.get("skin") == "classic"
        assert sc.sprites[2].placement.ref == "face"
        assert sc.sprites[2].placement.gap == 1

    def test_parse_multi_block_file(self):
        blocks = parse_cv("""
            template box_face {
                edge "│"
                default_corners round
                eyes row=0.0 cols=[0.33 0.56]
                mouth row=0.5 col=0.5
                substrate row=1.0
            }
            palette classic {
                eyes { open "◕" }
                mouths { smile "◡" }
                borders { thin "─" }
            }
        """)
        assert len(blocks) == 2
        types = {type(b) for b in blocks}
        assert TemplateSpec in types
        assert PaletteSpec in types

    def test_parse_on_blocks(self):
        blocks = parse_cv("""
            scene test 10x10 {
                face center priority=50 {
                    skin classic
                    on status {
                        resting { scale 0.8 }
                        excited { scale 1.2 skin energetic }
                    }
                }
            }
        """)
        scene = blocks[0]
        face = scene.sprites[0]
        assert len(face.on_blocks) == 1
        on = face.on_blocks[0]
        assert on.context_key == "status"
        assert on.cases[0].match == "resting"
        assert on.cases[0].overrides["scale"] == 0.8
