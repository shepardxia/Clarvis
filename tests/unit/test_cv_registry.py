"""Tests for .cv registry — file loading, tag indexing, queries."""

from pathlib import Path

from clarvis.display.cv.registry import CvRegistry
from clarvis.display.cv.specs import PaletteSpec


def _write_cv(dir_path: Path, name: str, content: str):
    (dir_path / name).write_text(content)


def test_registry_load_and_query(tmp_path):
    """Load .cv files, query by type/tag, verify universal palette behavior."""

    # load a tagged palette and verify retrieval
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

    # basic palette retrieval
    p = reg.get_palette("classic")
    assert p is not None
    assert p.eyes["open"] == "◕"

    # tag filtering returns only matching palettes
    palettes = reg.query_palettes(tags=["classic"])
    assert len(palettes) == 1
    assert palettes[0].name == "classic"

    # universal palettes (no tags) are included in tag queries
    _write_cv(
        tmp_path,
        "universal.cv",
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
    reg.load()
    palettes = reg.query_palettes(tags=["fancy"])
    names = {p.name for p in palettes}
    assert "base" in names
    assert "fancy" in names

    # no-tags defaults to empty list (universal)
    p = PaletteSpec(name="bare", eyes={"x": "X"}, mouths={}, borders={})
    assert p.tags == []


def test_registry_reload(tmp_path):
    """Reload replaces old specs with new ones."""
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
    reg.load()
    assert reg.get_palette("v1") is None
    assert reg.get_palette("v2") is not None
