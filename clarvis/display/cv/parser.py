"""Lark transformer that converts .cv parse trees into typed spec dataclasses."""

from __future__ import annotations

from pathlib import Path

from lark import Lark, Transformer

from .specs import (
    FrameRef,
    OnBlock,
    OnCase,
    PaletteSpec,
    Placement,
    PresetSpec,
    SceneSpec,
    SequenceSpec,
    SpriteSpec,
    TemplateSpec,
)

_GRAMMAR = (Path(__file__).parent / "grammar.lark").read_text()
_PARSER = Lark(_GRAMMAR, parser="earley", start="start")


def _strip_quotes(s: str) -> str:
    """Remove surrounding quotes from an ESCAPED_STRING token."""
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return s


class CvTransformer(Transformer):
    """Transform Lark parse tree into spec dataclasses."""

    # --- Values ---

    def string_value(self, items):
        return _strip_quotes(str(items[0]))

    def number_value(self, items):
        s = str(items[0])
        return float(s) if "." in s else int(s)

    def true_value(self, _items):
        return True

    def false_value(self, _items):
        return False

    def name_value(self, items):
        return str(items[0])

    def value_list(self, items):
        return list(items)

    # --- Shared ---

    def tag_list(self, items):
        return [str(t) for t in items]

    def string_list(self, items):
        return [_strip_quotes(str(s)) for s in items]

    def kv_pair(self, items):
        key = str(items[0])
        value = items[1]
        return (key, value)

    # --- Palette ---

    def char_entry(self, items):
        return (str(items[0]), _strip_quotes(str(items[1])))

    def char_map(self, items):
        return dict(items)

    def corner_entry(self, items):
        return (str(items[0]), items[1])

    def corner_map(self, items):
        return dict(items)

    def preset_assign(self, items):
        return (str(items[0]), str(items[1]))

    def preset_entry(self, items):
        name = str(items[0])
        assigns = dict(items[1:])
        return (name, PresetSpec(**assigns))

    def palette_tags(self, items):
        return ("tags", items[0])

    def palette_eyes(self, items):
        return ("eyes", items[0])

    def palette_mouths(self, items):
        return ("mouths", items[0])

    def palette_borders(self, items):
        return ("borders", items[0])

    def palette_corners(self, items):
        return ("corners", items[0])

    def palette_substrates(self, items):
        return ("substrates", items[0])

    def palette_presets(self, items):
        return ("presets", dict(items))

    def palette_block(self, items):
        name = str(items[0])
        fields: dict = {}
        for item in items[1:]:
            if isinstance(item, tuple):
                fields[item[0]] = item[1]
        return PaletteSpec(name=name, **fields)

    # --- Template ---

    def template_edge(self, items):
        return ("edge", _strip_quotes(str(items[0])))

    def template_default_corners(self, items):
        return ("default_corners", str(items[0]))

    def template_default_substrate(self, items):
        return ("default_substrate", str(items[0]))

    def template_eyes(self, items):
        kvs = dict(items)
        result = {}
        if "row" in kvs:
            result["eyes_row"] = kvs["row"]
        if "cols" in kvs:
            result["eyes_cols"] = kvs["cols"]
        return ("_eyes", result)

    def template_mouth(self, items):
        kvs = dict(items)
        result = {}
        if "row" in kvs:
            result["mouth_row"] = kvs["row"]
        if "col" in kvs:
            result["mouth_col"] = kvs["col"]
        return ("_mouth", result)

    def template_substrate(self, items):
        kvs = dict(items)
        result = {}
        if "row" in kvs:
            result["substrate_row"] = kvs["row"]
        return ("_substrate", result)

    def template_block(self, items):
        name = str(items[0])
        fields: dict = {}
        for item in items[1:]:
            if isinstance(item, tuple):
                key, val = item
                if key.startswith("_"):
                    fields.update(val)
                else:
                    fields[key] = val
        return TemplateSpec(name=name, **fields)

    # --- Sequence ---

    def frame_preset_ref(self, items):
        return FrameRef(preset=str(items[0]))

    def frame_define_ref(self, items):
        return FrameRef(define_ref=str(items[0]))

    def frame_inline(self, items):
        assigns = dict(items)
        return FrameRef(inline=PresetSpec(**assigns))

    def frame_list(self, items):
        return list(items)

    def sequence_tags(self, items):
        return ("tags", items[0])

    def sequence_define(self, items):
        name = str(items[0])
        frames = items[1]
        return ("define", name, frames)

    def sequence_frames(self, items):
        return ("frames", items[0])

    def sequence_block(self, items):
        name = str(items[0])
        tags = []
        defines = {}
        frames = []
        for item in items[1:]:
            if isinstance(item, tuple):
                if item[0] == "tags":
                    tags = item[1]
                elif item[0] == "define":
                    defines[item[1]] = item[2]
                elif item[0] == "frames":
                    frames = item[1]
        return SequenceSpec(name=name, tags=tags, defines=defines, frames=frames)

    # --- Scene ---

    def dimensions(self, items):
        return (int(items[0]), int(items[1]))

    def place_fullscreen(self, _items):
        return Placement(kind="fullscreen")

    def place_center(self, _items):
        return Placement(kind="center")

    def place_top(self, _items):
        return Placement(kind="top")

    def place_bottom(self, _items):
        return Placement(kind="bottom")

    def place_relative(self, items):
        kind = str(items[0])
        ref = str(items[1])
        kvs = dict(items[2:])
        return Placement(kind=kind, ref=ref, gap=int(kvs.get("gap", 0)))

    def sprite_props(self, items):
        return items[0]  # unwrap kv_pair

    def sprite_prop_positional(self, items):
        return (str(items[0]), items[1])

    def sprite_body(self, items):
        return items[0]

    def on_case(self, items):
        match = str(items[0])
        overrides = dict(items[1:])
        return OnCase(match=match, overrides=overrides)

    def case_prop(self, items):
        return (str(items[0]), items[1])

    def on_block(self, items):
        context_key = str(items[0])
        cases = [c for c in items[1:] if isinstance(c, OnCase)]
        return OnBlock(context_key=context_key, cases=cases)

    def sprite_decl(self, items):
        sprite_type = str(items[0])
        placement = items[1]
        props = {}
        on_blocks = []
        priority = 0

        for item in items[2:]:
            if isinstance(item, tuple):
                key, val = item
                if key == "priority":
                    priority = int(val)
                elif key == "width":
                    props[key] = val
                elif key == "visible":
                    props[key] = val
                else:
                    props[key] = val
            elif isinstance(item, OnBlock):
                on_blocks.append(item)

        return SpriteSpec(
            type=sprite_type,
            placement=placement,
            priority=priority,
            properties=props,
            on_blocks=on_blocks,
        )

    def scene_block(self, items):
        name = str(items[0])
        dims = items[1]
        sprites = [s for s in items[2:] if isinstance(s, SpriteSpec)]
        return SceneSpec(name=name, width=dims[0], height=dims[1], sprites=sprites)

    # --- Top level ---

    def start(self, items):
        return list(items)


def parse_cv(text: str) -> list[PaletteSpec | TemplateSpec | SequenceSpec | SceneSpec]:
    """Parse .cv text into a list of spec dataclasses."""
    tree = _PARSER.parse(text)
    return CvTransformer().transform(tree)
