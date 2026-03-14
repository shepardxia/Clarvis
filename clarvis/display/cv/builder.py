"""SceneBuilder: resolves SceneSpec + CvRegistry into a SceneManager with sprites."""

from __future__ import annotations

from ..elements.registry import ElementRegistry
from ..sprites.reel import ReelMode
from ..sprites.scenes import SceneManager
from ..sprites.system import (
    AVATAR,
    BAR,
    CELESTIAL,
    MIC,
    TEXT,
    WEATHER,
    BarSprite,
    CelestialCel,
    FaceCel,
    MicControl,
    VoiceReel,
    WeatherSandbox,
)
from .registry import CvRegistry
from .specs import OnBlock, SpriteSpec

# Default priority map for sprite types
_DEFAULT_PRIORITIES = {
    "weather": WEATHER,
    "celestial": CELESTIAL,
    "face": AVATAR,
    "bar": BAR,
    "mic": MIC,
    "voice": TEXT,
}


def build(
    registry: CvRegistry,
    scene_name: str = "default",
    width: int | None = None,
    height: int | None = None,
    *,
    include_on_blocks: bool = False,
) -> SceneManager | tuple[SceneManager, dict[str, list[OnBlock]]]:
    """Build a SceneManager from CV specs.

    Args:
        registry: CvRegistry with loaded .cv files.
        scene_name: Name of the scene to build.
        width: Override scene width.
        height: Override scene height.
        include_on_blocks: If True, return (scene, on_block_map) tuple.

    Returns:
        SceneManager, or (SceneManager, on_block_map) if include_on_blocks is True.
    """
    spec = registry.get_scene(scene_name)
    if spec is None:
        raise ValueError(f"Scene '{scene_name}' not found in registry")

    w = width or spec.width
    h = height or spec.height
    scene = SceneManager(w, h)

    # Element registry for weather (still uses YAML)
    elem_registry = ElementRegistry()
    elem_registry.load_all()

    # Two-pass: first create sprites with known sizes, then resolve relative placements
    sprite_map: dict[str, object] = {}
    sprite_order: list[tuple[SpriteSpec, object]] = []
    on_block_map: dict[str, list[OnBlock]] = {}

    for sspec in spec.sprites:
        priority = sspec.priority or _DEFAULT_PRIORITIES.get(sspec.type, 0)
        sprite = _create_sprite(sspec, w, h, priority, registry, elem_registry)
        sprite_map[sspec.type] = sprite
        sprite_order.append((sspec, sprite))
        if include_on_blocks and sspec.on_blocks:
            on_block_map[sspec.type] = sspec.on_blocks

    # Resolve relative placements now that we know all bboxes
    for sspec, sprite in sprite_order:
        _resolve_placement(sspec, sprite, sprite_map, w, h)

    # Post-placement fixups
    _fixup_celestial(sprite_map)

    # Add to scene in spec order (SceneManager sorts by priority)
    for _sspec, sprite in sprite_order:
        if isinstance(sprite, WeatherSandbox):
            sprite._scene_registry = scene.registry
        scene.add(sprite)

    if include_on_blocks:
        return scene, on_block_map
    return scene


# Backward-compatible class wrapper — delegates to module-level build()
class SceneBuilder:
    """Builds a SceneManager from CV specs."""

    @staticmethod
    def build(
        registry: CvRegistry,
        scene_name: str = "default",
        width: int | None = None,
        height: int | None = None,
    ) -> SceneManager:
        return build(registry, scene_name=scene_name, width=width, height=height)

    @staticmethod
    def build_with_on_blocks(
        registry: CvRegistry,
        scene_name: str = "default",
        width: int | None = None,
        height: int | None = None,
    ) -> tuple[SceneManager, dict[str, list[OnBlock]]]:
        return build(registry, scene_name=scene_name, width=width, height=height, include_on_blocks=True)


def _create_sprite(sspec, w, h, priority, cv_registry, elem_registry):
    """Create a sprite from a SpriteSpec (placement resolved later for relative ones)."""
    stype = sspec.type

    if stype == "weather":
        return WeatherSandbox(elem_registry, w, h, priority=priority)

    if stype == "celestial":
        # avatar_y filled later during placement resolution
        return CelestialCel(w, h, avatar_y=h // 2, priority=priority)

    if stype == "face":
        skin = sspec.properties.get("skin", "classic")
        # Resolve palette, template, sequences from cv_registry
        palette = cv_registry.get_palette(skin)
        template = None
        # Get first available template
        for name in ("box_face",):
            template = cv_registry.get_template(name)
            if template:
                break
        if palette is None or template is None:
            raise ValueError(f"Skin '{skin}' requires a palette and template in the registry")
        sequences_list = cv_registry.query_sequences(tags=[skin])
        sequences = {s.name: s for s in sequences_list}
        if not sequences:
            raise ValueError(f"No sequences found for skin '{skin}'")
        face_w = int(sspec.properties.get("width", 11))
        face_h = int(sspec.properties.get("height", 5))
        return FaceCel.from_specs(
            template=template,
            palette=palette,
            sequences=sequences,
            x=0,
            y=0,  # resolved later
            width=face_w,
            height=face_h,
            priority=priority,
        )

    if stype == "bar":
        bar_width_ratio = sspec.properties.get("width", 0.65)
        bar_width = max(1, int(float(bar_width_ratio) * w))
        return BarSprite(x=0, y=0, width=bar_width, priority=priority)

    if stype == "mic":
        icons = {"enabled": "[M]", "disabled": "[·]"}
        return MicControl(
            x=0,
            y=0,
            priority=priority,
            labels=icons,
            action_id="mic_toggle",
            state="disabled",
            visible=sspec.properties.get("visible", False),
            color=240,
            transparent=True,
        )

    if stype == "voice":
        text_x_margin = 2
        text_y_start = 1
        text_max_rows = 8
        text_width = w - 2 * text_x_margin
        return VoiceReel(
            x=text_x_margin,
            y=text_y_start,
            width=text_width,
            height=min(text_max_rows, h - text_y_start),
            priority=priority,
            mode=ReelMode.REVEAL,
            color=255,
            transparent=True,
        )

    raise ValueError(f"Unknown sprite type: {stype}")


def _resolve_placement(sspec, sprite, sprite_map, canvas_w, canvas_h):
    """Resolve a Placement to absolute x, y coordinates on the sprite."""
    p = sspec.placement

    if p.kind == "fullscreen":
        _set_pos(sprite, 0, 0)
        return

    if p.kind == "center":
        bbox = sprite.bbox
        x = (canvas_w - bbox.w) // 2
        # Compute vertical center considering total content height
        total_h = _total_content_height(sspec, sprite, sprite_map)
        y = (canvas_h - total_h) // 2
        _set_pos(sprite, x, y)
        return

    if p.kind == "top":
        _set_pos(sprite, 0, 0)
        return

    if p.kind == "bottom":
        bbox = sprite.bbox
        _set_pos(sprite, 0, canvas_h - bbox.h)
        return

    if p.kind == "bottom_right":
        bbox = sprite.bbox
        _set_pos(sprite, canvas_w - bbox.w, canvas_h - bbox.h)
        return

    if p.kind in ("below", "right", "above", "left"):
        ref = sprite_map.get(p.ref)
        if ref is None:
            _set_pos(sprite, 0, 0)
            return
        ref_bbox = ref.bbox
        sprite_bbox = sprite.bbox

        if p.kind == "below":
            x = (canvas_w - sprite_bbox.w) // 2  # center horizontally
            y = ref_bbox.y2 + p.gap
            _set_pos(sprite, x, y)
        elif p.kind == "right":
            x = ref_bbox.x2 + p.gap
            y = ref_bbox.y
            _set_pos(sprite, x, y)
        elif p.kind == "above":
            x = (canvas_w - sprite_bbox.w) // 2
            y = ref_bbox.y - sprite_bbox.h - p.gap
            _set_pos(sprite, x, y)
        elif p.kind == "left":
            x = ref_bbox.x - sprite_bbox.w - p.gap
            y = ref_bbox.y
            _set_pos(sprite, x, y)
        return

    # At (explicit x, y) — not yet needed but supported by grammar
    if p.kind == "at" and p.x is not None and p.y is not None:
        _set_pos(sprite, int(p.x * canvas_w), int(p.y * canvas_h))
        return


def _set_pos(sprite, x, y):
    """Set position on a sprite, handling different sprite attribute patterns."""
    if hasattr(sprite, "x"):
        sprite.x = x
        sprite.y = y
    if hasattr(sprite, "_x"):
        sprite._x = x
        sprite._y = y
    # CelestialCel uses _grid_width etc but position is computed dynamically
    if isinstance(sprite, CelestialCel):
        sprite._avatar_y = y


def _fixup_celestial(sprite_map):
    """Set CelestialCel._avatar_y to the face's actual y position."""
    celestial = sprite_map.get("celestial")
    face = sprite_map.get("face")
    if isinstance(celestial, CelestialCel) and face is not None:
        celestial._avatar_y = face.bbox.y


def _total_content_height(sspec, sprite, sprite_map):
    """Estimate total content block height for vertical centering."""
    # Simple: just the sprite's own height
    # Could be smarter by summing face + gap + bar, but for now just use sprite height
    return sprite.bbox.h
