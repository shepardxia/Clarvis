"""Tests for .cv spec dataclasses."""

from clarvis.display.cv.specs import (
    FrameRef,
    OnBlock,
    OnCase,
    PaletteSpec,
    Placement,
    PresetSpec,
    SceneSpec,
    SequenceSpec,
    SpriteSpec,
)


class TestPlacement:
    def test_center(self):
        p = Placement(kind="center")
        assert p.kind == "center"
        assert p.ref is None

    def test_relative(self):
        p = Placement(kind="below", ref="face", gap=1)
        assert p.ref == "face"
        assert p.gap == 1

    def test_explicit(self):
        p = Placement(kind="at", x=0.5, y=0.3)
        assert p.x == 0.5


class TestPaletteSpec:
    def test_basic(self):
        p = PaletteSpec(
            name="classic",
            tags=["classic"],
            eyes={"open": "◕", "closed": "─"},
            mouths={"smile": "◡"},
            borders={"thin": "─"},
            corners={"round": ["╭", "╮", "╰", "╯"]},
            substrates={"idle": " .  .  . "},
            presets={"happy": PresetSpec(eyes="open", mouth="smile", border="thin")},
        )
        assert p.eyes["open"] == "◕"
        assert p.presets["happy"].eyes == "open"

    def test_no_tags_is_universal(self):
        p = PaletteSpec(name="base", eyes={"x": "X"}, mouths={}, borders={})
        assert p.tags == []


class TestSequenceSpec:
    def test_frames(self):
        s = SequenceSpec(
            name="idle",
            tags=["classic"],
            defines={"blink": [FrameRef(preset="happy")]},
            frames=[FrameRef(define_ref="blink"), FrameRef(preset="happy")],
        )
        assert s.frames[0].define_ref == "blink"
        assert s.frames[1].preset == "happy"


class TestSceneSpec:
    def test_sprites(self):
        scene = SceneSpec(
            name="default",
            width=43,
            height=17,
            sprites=[
                SpriteSpec(type="face", placement=Placement(kind="center"), priority=50),
            ],
        )
        assert len(scene.sprites) == 1
        assert scene.sprites[0].type == "face"


class TestOnBlock:
    def test_cases(self):
        on = OnBlock(
            context_key="status",
            cases=[
                OnCase(match="resting", overrides={"scale": 0.8}),
                OnCase(match="excited", overrides={"scale": 1.2}),
            ],
        )
        assert on.cases[0].overrides["scale"] == 0.8
