"""Typed dataclasses produced by the .cv parser."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Placement:
    kind: str  # center, fullscreen, below, right, top, bottom, bottom_right, at
    ref: str | None = None
    gap: int = 0
    x: float | None = None
    y: float | None = None


@dataclass
class PresetSpec:
    eyes: str | None = None
    mouth: str | None = None
    border: str | None = None
    corners: str | None = None
    substrate: str | None = None


@dataclass
class PaletteSpec:
    name: str
    tags: list[str] = field(default_factory=list)
    eyes: dict[str, str] = field(default_factory=dict)
    mouths: dict[str, str] = field(default_factory=dict)
    borders: dict[str, str] = field(default_factory=dict)
    corners: dict[str, list[str]] = field(default_factory=dict)
    substrates: dict[str, str] = field(default_factory=dict)
    presets: dict[str, PresetSpec] = field(default_factory=dict)


@dataclass
class TemplateSpec:
    name: str
    edge: str = "│"
    default_corners: str = "round"
    default_substrate: str | None = None
    eyes_row: float = 0.0
    eyes_cols: list[float] = field(default_factory=lambda: [0.3, 0.7])
    mouth_row: float = 0.5
    mouth_col: float = 0.5
    substrate_row: float = 1.0


@dataclass
class FrameRef:
    """A single item in a sequence's frame list."""

    preset: str | None = None  # reference to palette preset
    define_ref: str | None = None  # $name reference to a define block
    inline: PresetSpec | None = None  # inline {eyes=X mouth=Y}


@dataclass
class SequenceSpec:
    name: str
    tags: list[str] = field(default_factory=list)
    defines: dict[str, list[FrameRef]] = field(default_factory=dict)
    frames: list[FrameRef] = field(default_factory=list)


@dataclass
class OnCase:
    match: str  # value to match, or "0..6" range string
    overrides: dict[str, object] = field(default_factory=dict)


@dataclass
class OnBlock:
    context_key: str
    cases: list[OnCase] = field(default_factory=list)


@dataclass
class SpriteSpec:
    type: str  # face, weather, celestial, bar, mic, voice
    placement: Placement = field(default_factory=lambda: Placement(kind="center"))
    priority: int = 0
    properties: dict[str, object] = field(default_factory=dict)
    on_blocks: list[OnBlock] = field(default_factory=list)


@dataclass
class SceneSpec:
    name: str
    width: int = 43
    height: int = 17
    sprites: list[SpriteSpec] = field(default_factory=list)
