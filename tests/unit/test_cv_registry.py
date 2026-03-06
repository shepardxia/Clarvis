"""Tests for .cv registry — file loading, tag indexing, queries."""

from pathlib import Path

from clarvis.display.cv.registry import CvRegistry


def _write_cv(dir_path: Path, name: str, content: str):
    (dir_path / name).write_text(content)


class TestCvRegistry:
    def test_load_palette(self, tmp_path):
        _write_cv(
            tmp_path,
            "test.cv",
            """
            palette classic {
                tags [classic]
                eyes { open "◕" }
                mouths { smile "◡" }
                borders { thin "─" }
            }
        """,
        )
        reg = CvRegistry(tmp_path)
        reg.load()
        p = reg.get_palette("classic")
        assert p is not None
        assert p.eyes["open"] == "◕"

    def test_tag_filtering(self, tmp_path):
        _write_cv(
            tmp_path,
            "skins.cv",
            """
            palette classic {
                tags [classic]
                eyes { open "◕" }
                mouths { smile "◡" }
                borders { thin "─" }
            }
            palette pixel {
                tags [pixel]
                eyes { open "■" }
                mouths { smile "▬" }
                borders { thin "═" }
            }
        """,
        )
        reg = CvRegistry(tmp_path)
        reg.load()
        palettes = reg.query_palettes(tags=["classic"])
        assert len(palettes) == 1
        assert palettes[0].name == "classic"

    def test_universal_included_in_tag_query(self, tmp_path):
        _write_cv(
            tmp_path,
            "test.cv",
            """
            palette base {
                eyes { open "o" }
                mouths { smile "u" }
                borders { thin "-" }
            }
            palette fancy {
                tags [fancy]
                eyes { sparkle "✧" }
                mouths { smile "◡" }
                borders { thin "─" }
            }
        """,
        )
        reg = CvRegistry(tmp_path)
        reg.load()
        palettes = reg.query_palettes(tags=["fancy"])
        names = {p.name for p in palettes}
        assert "base" in names
        assert "fancy" in names

    def test_get_template(self, tmp_path):
        _write_cv(
            tmp_path,
            "test.cv",
            """
            template box_face {
                edge "│"
                default_corners round
                eyes row=0.0 cols=[0.33 0.56]
                mouth row=0.5 col=0.5
                substrate row=1.0
            }
        """,
        )
        reg = CvRegistry(tmp_path)
        reg.load()
        t = reg.get_template("box_face")
        assert t is not None
        assert t.edge == "│"

    def test_get_sequences(self, tmp_path):
        _write_cv(
            tmp_path,
            "test.cv",
            """
            sequence idle {
                tags [classic]
                frames [ {eyes=open mouth=smile border=thin} ]
            }
            sequence thinking {
                tags [classic]
                frames [ {eyes=half mouth=neutral border=medium} ]
            }
        """,
        )
        reg = CvRegistry(tmp_path)
        reg.load()
        seqs = reg.query_sequences(tags=["classic"])
        assert len(seqs) == 2

    def test_get_scene(self, tmp_path):
        _write_cv(
            tmp_path,
            "test.cv",
            """
            scene default 20x10 {
                face center priority=50
            }
        """,
        )
        reg = CvRegistry(tmp_path)
        reg.load()
        sc = reg.get_scene("default")
        assert sc is not None
        assert sc.width == 20

    def test_reload(self, tmp_path):
        _write_cv(
            tmp_path,
            "test.cv",
            """
            palette v1 {
                eyes { open "o" }
                mouths { smile "u" }
                borders { thin "-" }
            }
        """,
        )
        reg = CvRegistry(tmp_path)
        reg.load()
        assert reg.get_palette("v1") is not None

        _write_cv(
            tmp_path,
            "test.cv",
            """
            palette v2 {
                eyes { open "◕" }
                mouths { smile "◡" }
                borders { thin "─" }
            }
        """,
        )
        reg.load()  # reload
        assert reg.get_palette("v1") is None
        assert reg.get_palette("v2") is not None
