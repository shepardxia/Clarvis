# Archetype-to-Sprite Migration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate the archetype→Layer→scratch-copy bridge by inlining rendering logic directly into sprites, then delete archetypes/, Layer, and pipeline.py.

**Architecture:** Each archetype's rendering code moves into its corresponding sprite. Sprites read from `ElementRegistry` directly and render into `out_chars`/`out_colors` numpy arrays. Numba JIT functions (weather physics) become a standalone utility module. The `Layer` class and `Archetype` base class are deleted.

**Tech Stack:** Python 3.13, numpy, numba (optional JIT), ElementRegistry (YAML loading)

---

## Phase A: Resolve Review Findings

### Task 1: Pre-allocate scratch arrays in SceneManager

**Files:**
- Modify: `clarvis/display/sprites/scenes.py`
- Test: `tests/unit/test_sprites_scenes.py`

**Context:** `SceneManager.render()` allocates two full-screen numpy arrays per transparent sprite per frame (lines 47-48). Pre-allocate once in `__init__`, `.fill()` before each use.

**Step 1: Write the failing test**

Add to `tests/unit/test_sprites_scenes.py`:

```python
class TestSceneManagerScratch:
    def test_scratch_arrays_are_reused(self):
        """Verify scratch arrays exist on the scene and are not re-allocated."""
        scene = SceneManager(10, 5)
        # Scratch arrays should be pre-allocated
        assert hasattr(scene, "_scratch_chars")
        assert hasattr(scene, "_scratch_colors")
        assert scene._scratch_chars.shape == (5, 10)
        assert scene._scratch_colors.shape == (5, 10)
        # Get references before render
        id_c = id(scene._scratch_chars)
        id_k = id(scene._scratch_colors)
        scene.add(TransparentSprite(0, 0, priority=0))
        scene.tick()
        scene.render()
        # Same objects after render (not re-allocated)
        assert id(scene._scratch_chars) == id_c
        assert id(scene._scratch_colors) == id_k
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_sprites_scenes.py::TestSceneManagerScratch -v`
Expected: FAIL — `_scratch_chars` attribute doesn't exist

**Step 3: Implement**

In `scenes.py` `__init__`, add:
```python
self._scratch_chars = np.full((height, width), SPACE, dtype=np.uint32)
self._scratch_colors = np.zeros((height, width), dtype=np.uint8)
```

In `render()`, replace lines 47-48 (per-sprite allocation) with:
```python
scratch_c = self._scratch_chars
scratch_k = self._scratch_colors
scratch_c.fill(SPACE)
scratch_k.fill(0)
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_sprites_scenes.py -v`
Expected: ALL PASS

**Step 5: Commit**

```
Pre-allocate scratch arrays in SceneManager to avoid per-frame allocation
```

---

### Task 2: Make WeatherSandbox opaque

**Files:**
- Modify: `clarvis/display/sprites/system.py`
- Test: `tests/unit/test_sprites_system.py`

**Context:** WeatherSandbox is lowest priority (WEATHER=0) — nothing renders below it. It's marked transparent but gains nothing from the scratch+mask path. Making it opaque lets it render directly into output arrays. However, WeatherSandbox.render() currently does its OWN transparency logic internally (lines 106-131: renders to scratch Layer, masks SPACE, copies). After this change, it still needs to preserve whatever is already in the output for SPACE cells — but since it's the first sprite rendered (lowest priority), the output is all SPACE anyway. So opaque write is correct.

**Important:** WeatherSandbox.render() already handles transparency internally via its own mask logic. This is because the archetype renders sparse particles. When we make the sprite opaque, SceneManager skips its scratch+mask path and calls `sprite.render(out_c, out_k)` directly. WeatherSandbox.render() already writes only to non-SPACE cells (via its internal mask at lines 124-131), so the visual output is identical.

**Step 1: Write the failing test**

Add to `tests/unit/test_sprites_system.py`:

```python
class TestWeatherOpaque:
    def test_weather_is_opaque(self):
        scene = build_default_scene(width=43, height=17)
        weather = next(s for s in scene.registry.alive() if isinstance(s, WeatherSandbox))
        assert weather.transparent is False
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_sprites_system.py::TestWeatherOpaque -v`
Expected: FAIL — `True is not False`

**Step 3: Implement**

In `system.py` `WeatherSandbox.__init__`, change:
```python
super().__init__(priority=priority, transparent=True)
```
to:
```python
super().__init__(priority=priority, transparent=False)
```

**Step 4: Run full test suite**

Run: `.venv/bin/python -m pytest tests/unit/ -v`
Expected: ALL PASS

**Step 5: Commit**

```
Make WeatherSandbox opaque — lowest priority, nothing below it
```

---

### Task 3: Deduplicate SPACE constant

**Files:**
- Modify: `clarvis/display/pipeline.py`
- Modify: `clarvis/display/sprites/system.py`
- Test: existing tests

**Context:** `SPACE = ord(" ")` is defined in both `core.py` and `pipeline.py`. After migration, `pipeline.py` will be deleted, so canonicalize on `core.py` now. `system.py` imports SPACE from `pipeline.py` — switch it.

**Step 1: In `system.py`, change the import**

From:
```python
from ..pipeline import SPACE, Layer
```
To:
```python
from ..pipeline import Layer
from .core import SPACE
```

**Step 2: In `pipeline.py`, replace the local definition with a re-export**

From:
```python
SPACE = ord(" ")
```
To:
```python
from .sprites.core import SPACE  # canonical definition
```

Wait — this creates a circular import: `pipeline.py` → `sprites.core` → ... The archetypes import from `pipeline.py`, and sprites import from `core.py`. The safe approach: keep SPACE in pipeline.py for now (archetypes still need it), but update system.py to import from core.py. The full dedup happens in Phase C when pipeline.py is deleted.

**Step 1 (revised): Just update system.py import**

In `system.py`, change:
```python
from ..pipeline import SPACE, Layer
```
To:
```python
from ..pipeline import Layer
from .core import SPACE
```

**Step 2: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/ -v`
Expected: ALL PASS

**Step 3: Commit**

```
Import SPACE from canonical core.py in system sprites
```

---

### Task 4: Fix moon art width inconsistency

**Files:**
- Modify: `clarvis/display/sprites/system.py`
- Test: `tests/unit/test_sprites_system.py`

**Context:** `MOON_ART = [" _ ", "(') ", " ~ "]` — second line is 4 chars (trailing space), others are 3. `CELESTIAL_WIDTH = 3`. Fix the art to be consistent.

**Step 1: Write the failing test**

Add to `tests/unit/test_sprites_system.py`:

```python
class TestMoonArt:
    def test_moon_art_consistent_widths(self):
        """All MOON_ART lines should be CELESTIAL_WIDTH chars."""
        for i, line in enumerate(CelestialCel.MOON_ART):
            assert len(line) == CelestialCel.CELESTIAL_WIDTH, (
                f"MOON_ART[{i}] is {len(line)} chars, expected {CelestialCel.CELESTIAL_WIDTH}: {line!r}"
            )

    def test_sun_art_consistent_widths(self):
        """All SUN_ART lines should be CELESTIAL_WIDTH chars."""
        for i, line in enumerate(CelestialCel.SUN_ART):
            assert len(line) == CelestialCel.CELESTIAL_WIDTH, (
                f"SUN_ART[{i}] is {len(line)} chars, expected {CelestialCel.CELESTIAL_WIDTH}: {line!r}"
            )
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_sprites_system.py::TestMoonArt -v`
Expected: FAIL on `test_moon_art_consistent_widths` — `MOON_ART[1]` is 4 chars

**Step 3: Fix the art**

In `system.py`, change:
```python
MOON_ART = [" _ ", "(') ", " ~ "]
```
To:
```python
MOON_ART = [" _ ", "(')", " ~ "]
```

The trailing space on `"(') "` was unintentional. `"(')"` is 3 chars and renders the same (the space was outside the visible area anyway).

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_sprites_system.py -v`
Expected: ALL PASS

**Step 5: Commit**

```
Fix moon art inconsistent width: remove trailing space from line 2
```

---

### Task 5: Add public accessor for FaceArchetype animation cache

**Files:**
- Modify: `clarvis/display/archetypes/face.py`
- Modify: `clarvis/display/sprites/system.py`
- Test: `tests/unit/test_sprites_system.py`

**Context:** FaceCel accesses `archetype._state_cache` (private). Add a public method and use it. This also prepares for Phase B where FaceCel will absorb the face logic directly.

**Step 1: In `face.py`, add public accessor**

After `prewarm_cache()` (line 125), add:

```python
def get_cached_frames(self, status: str) -> list[np.ndarray]:
    """Return pre-computed frame matrices for a status, caching on demand."""
    if status not in self._state_cache:
        original = self.status
        self.status = status
        self._cache_animation()
        self.status = original
        self._cache_animation()
    return self._state_cache.get(status, [])
```

**Step 2: In `system.py`, use the public accessor**

Change `FaceCel.__init__` (line 38-39):
```python
super().__init__(
    animations=archetype._state_cache,
```
To:
```python
super().__init__(
    animations=dict(archetype._state_cache),
```

Actually, `_state_cache` is still needed for the initial bulk pass. The key change is in `set_status` (line 57):
```python
self._animations[status] = self._archetype._state_cache.get(status, [])
```
To:
```python
self._animations[status] = self._archetype.get_cached_frames(status)
```

And update `__init__` to use public API too. Since `prewarm_cache()` is already called, the cache is populated. Use:
```python
super().__init__(
    animations={s: self._archetype.get_cached_frames(s) for s in archetype._state_cache},
```

Wait — that still reads `_state_cache` keys. Simpler: since `prewarm_cache()` returns `{status: frame_count}`, use that:

Change FaceCel `__init__` to:
```python
def __init__(self, registry: ElementRegistry, x: int, y: int, priority: int = AVATAR):
    archetype = FaceArchetype(registry)
    stats = archetype.prewarm_cache()
    super().__init__(
        animations={s: archetype.get_cached_frames(s) for s in stats},
        default_animation="idle",
        x=x,
        y=y,
        width=FaceArchetype.WIDTH,
        height=FaceArchetype.HEIGHT,
        priority=priority,
        transparent=False,
    )
    self._archetype = archetype
```

And `set_status`:
```python
def set_status(self, status: str) -> None:
    if status == self._current_animation:
        return
    if status not in self._animations:
        self._animations[status] = self._archetype.get_cached_frames(status)
    if status in self._animations:
        self.set_animation(status)
```

**Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_sprites_system.py -v`
Expected: ALL PASS

**Step 4: Commit**

```
Add public get_cached_frames() to FaceArchetype, stop accessing _state_cache
```

---

## Phase B: Inline Archetypes into Sprites

### Task 6: Inline FaceArchetype into FaceCel

**Files:**
- Modify: `clarvis/display/sprites/system.py`
- Test: `tests/unit/test_sprites_system.py`

**Context:** FaceCel currently delegates to FaceArchetype for frame computation. Move the frame computation logic (`_compute_frame_matrix`, `_resolve_char`, `_elem`, `_get_corners`, element caching) directly into FaceCel. FaceCel already IS a Cel, so it keeps frame cycling from the Cel base class.

**Step 1: Write a regression test**

Add to `test_sprites_system.py`:

```python
class TestFaceCelRegression:
    def test_face_frame_has_border_chars(self):
        """Face frames should contain border characters (╭, ╮, │, etc.)."""
        scene = build_default_scene(width=43, height=17)
        face = next(s for s in scene.registry.alive() if isinstance(s, FaceCel))
        out_c = np.full((17, 43), SPACE, dtype=np.uint32)
        out_k = np.zeros((17, 43), dtype=np.uint8)
        face.render(out_c, out_k)
        b = face.bbox
        region = out_c[b.y : b.y2, b.x : b.x2]
        # Top-left corner should be ╭
        assert region[0, 0] == ord("╭")
        # Edges should be │
        assert region[1, 0] == ord("│")

    def test_face_status_changes_frames(self):
        """Different statuses should produce different frame content."""
        scene = build_default_scene(width=43, height=17)
        face = next(s for s in scene.registry.alive() if isinstance(s, FaceCel))
        face.set_status("idle")
        idle_frames = list(face.current_frames)
        face.set_status("thinking")
        thinking_frames = list(face.current_frames)
        # At minimum, different statuses should have frames
        assert len(idle_frames) > 0
        assert len(thinking_frames) > 0
```

**Step 2: Run test to verify it passes (regression baseline)**

Run: `.venv/bin/python -m pytest tests/unit/test_sprites_system.py::TestFaceCelRegression -v`
Expected: PASS (this is a baseline)

**Step 3: Inline the face rendering logic**

Replace `FaceCel` class in `system.py` with one that reads directly from `ElementRegistry`:

```python
class FaceCel(Cel):
    """Face animation sprite. Reads elements from registry, computes frames directly."""

    WIDTH = 11
    HEIGHT = 5
    DEFAULT_CORNERS = ("╭", "╮", "╰", "╯")
    CORNER_PRESETS = {
        "round": ("╭", "╮", "╰", "╯"),
        "light": ("┌", "┐", "└", "┘"),
        "heavy": ("┏", "┓", "┗", "┛"),
        "double": ("╔", "╗", "╚", "╝"),
    }
    EDGE_V = ord("│")

    def __init__(self, registry: ElementRegistry, x: int, y: int, priority: int = AVATAR):
        self._registry = registry
        self._eyes = registry.get_all("eyes")
        self._mouths = registry.get_all("mouths")
        self._borders = registry.get_all("borders")
        self._substrates = registry.get_all("substrates")

        # Pre-compute all animation statuses
        animations = {}
        for status in registry.list_names("animations"):
            if status.startswith("_"):
                continue
            anim = registry.get("animations", status)
            frames_def = anim.get("frames", []) if anim else [{"eyes": "normal", "mouth": "neutral"}]
            animations[status] = [self._compute_frame(f, status) for f in frames_def]

        super().__init__(
            animations=animations,
            default_animation="idle",
            x=x, y=y,
            width=self.WIDTH, height=self.HEIGHT,
            priority=priority, transparent=False,
        )

    def _elem(self, registry: dict, name: str, field: str, fallback):
        return registry.get(name, {}).get(field, fallback)

    def _resolve_char(self, value: str, registry: dict, field: str, fallback: str) -> str:
        if not value:
            return fallback
        if len(value) == 1:
            return value
        result = self._elem(registry, value, field, fallback)
        return result if result else fallback

    def _get_corners(self, frame: dict) -> tuple[int, ...]:
        corners_spec = frame.get("corners")
        if corners_spec is None:
            corners = self.DEFAULT_CORNERS
        elif isinstance(corners_spec, str):
            corners = self.CORNER_PRESETS.get(corners_spec, self.DEFAULT_CORNERS)
        elif isinstance(corners_spec, (list, tuple)) and len(corners_spec) == 4:
            corners = tuple(corners_spec)
        else:
            corners = self.DEFAULT_CORNERS
        return tuple(ord(c) for c in corners)

    def _compute_frame(self, frame: dict, status: str) -> np.ndarray:
        m = np.full((self.HEIGHT, self.WIDTH), SPACE, dtype=np.uint32)

        eyes_name = frame.get("eyes", "normal")
        if eyes_name == "looking_l":
            eyes_name = "looking_left"
        elif eyes_name == "looking_r":
            eyes_name = "looking_right"
        eye_char = self._resolve_char(eyes_name, self._eyes, "char", "o")
        eye_code = ord(eye_char)
        if len(eyes_name) == 1:
            left, gap, right = 3, 1, 3
        else:
            left, gap, right = tuple(self._elem(self._eyes, eyes_name, "position", [3, 1, 3]))

        mouth_name = frame.get("mouth", "neutral")
        mouth_code = ord(self._resolve_char(mouth_name, self._mouths, "char", "~"))

        border_spec = frame.get("border", status)
        border_code = ord(self._resolve_char(border_spec, self._borders, "char", "-"))

        corner_tl, corner_tr, corner_bl, corner_br = self._get_corners(frame)
        substrate = self._elem(self._substrates, status, "pattern", " .  .  . ")

        m[0, 0] = corner_tl
        m[0, 1:10] = border_code
        m[0, 10] = corner_tr
        m[1, 0] = self.EDGE_V
        m[1, 1:10] = SPACE
        m[1, 1 + left] = eye_code
        m[1, 1 + left + 1 + gap] = eye_code
        m[1, 10] = self.EDGE_V
        m[2, 0] = self.EDGE_V
        m[2, 1:10] = SPACE
        m[2, 5] = mouth_code
        m[2, 10] = self.EDGE_V
        m[3, 0] = self.EDGE_V
        for i, c in enumerate(substrate[:9]):
            m[3, 1 + i] = ord(c)
        m[3, 10] = self.EDGE_V
        m[4, 0] = corner_bl
        m[4, 1:10] = border_code
        m[4, 10] = corner_br

        return m

    def set_status(self, status: str) -> None:
        if status == self._current_animation:
            return
        if status not in self._animations:
            anim = self._registry.get("animations", status)
            frames_def = anim.get("frames", []) if anim else [{"eyes": "normal", "mouth": "neutral"}]
            self._animations[status] = [self._compute_frame(f, status) for f in frames_def]
        if status in self._animations:
            self.set_animation(status)

    def tick(self, **ctx) -> None:
        status = ctx.get("status")
        if status:
            self.set_status(status)
        super().tick(**ctx)
```

Remove `FaceArchetype` import from system.py.

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/ -v`
Expected: ALL PASS

**Step 5: Commit**

```
Inline face rendering into FaceCel, remove FaceArchetype dependency
```

---

### Task 7: Inline ProgressArchetype into BarSprite

**Files:**
- Modify: `clarvis/display/sprites/system.py`
- Test: `tests/unit/test_sprites_system.py`

**Context:** ProgressArchetype is simple: cached 1-row bar matrices. Move the cache and render logic into BarSprite directly. BarSprite renders a single row — no need for Layer as intermediary.

**Step 1: Write regression test**

```python
class TestBarSpriteRegression:
    def test_bar_renders_filled_and_empty(self):
        """Bar at 50% should have both filled (#) and empty (-) chars."""
        scene = build_default_scene(width=43, height=17)
        bar = next(s for s in scene.registry.alive() if isinstance(s, BarSprite))
        bar.tick(context_percent=50.0)
        out_c = np.full((17, 43), SPACE, dtype=np.uint32)
        out_k = np.zeros((17, 43), dtype=np.uint8)
        bar.render(out_c, out_k)
        b = bar.bbox
        row = out_c[b.y, b.x:b.x2]
        assert ord("#") in row  # filled portion
        assert ord("-") in row  # empty portion
```

**Step 2: Run regression test (baseline)**

Run: `.venv/bin/python -m pytest tests/unit/test_sprites_system.py::TestBarSpriteRegression -v`
Expected: PASS

**Step 3: Inline progress logic**

Replace `BarSprite` with self-contained implementation:

```python
# Constants for progress bar
_FILLED = ord("#")
_EMPTY = ord("-")
_FILLED_COLOR = 15
_EMPTY_COLOR = 8


class BarSprite(Sprite):
    """Progress bar. Renders a single row with cached percentage matrices."""

    CACHE_SNAP_THRESHOLD = 0.5

    def __init__(self, x: int, y: int, width: int, priority: int = BAR):
        super().__init__(priority=priority, transparent=True)
        self._x = x
        self._y = y
        self._bar_width = width
        self._percent = 0.0
        # Percentage cache: int(percent) -> (chars_row, colors_row)
        self._cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self._prewarm()

    def _prewarm(self) -> None:
        for pct in range(101):
            self._cache_percent(pct)

    def _cache_percent(self, percent: int) -> tuple[np.ndarray, np.ndarray]:
        if percent in self._cache:
            return self._cache[percent]
        filled = int(percent / 100 * self._bar_width)
        chars = np.full(self._bar_width, _EMPTY, dtype=np.uint32)
        chars[:filled] = _FILLED
        colors = np.full(self._bar_width, _EMPTY_COLOR, dtype=np.uint8)
        colors[:filled] = _FILLED_COLOR
        self._cache[percent] = (chars, colors)
        return chars, colors

    @property
    def bbox(self) -> BBox:
        return BBox(self._x, self._y, self._bar_width, 1)

    def tick(self, **ctx) -> None:
        pct = ctx.get("context_percent")
        if pct is not None:
            self._percent = pct

    def render(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None:
        percent = max(0.0, min(100.0, float(self._percent)))
        int_pct = int(percent)
        if abs(percent - int_pct) < self.CACHE_SNAP_THRESHOLD:
            chars, colors = self._cache_percent(int_pct)
        else:
            filled = int(percent / 100 * self._bar_width)
            chars = np.full(self._bar_width, _EMPTY, dtype=np.uint32)
            chars[:filled] = _FILLED
            colors = np.full(self._bar_width, _EMPTY_COLOR, dtype=np.uint8)
            colors[:filled] = _FILLED_COLOR
        y, x = self._y, self._x
        out_chars[y, x : x + self._bar_width] = chars
        # Apply status color to empty portion
        status_color = StatusColors.get("idle").ansi
        color_row = colors.copy()
        filled_count = int(int_pct / 100 * self._bar_width)
        color_row[filled_count:] = status_color
        out_colors[y, x : x + self._bar_width] = color_row
```

Remove `ProgressArchetype` import. Remove `Layer` import if no longer needed (WeatherSandbox still uses it — remove in Task 8).

Update `build_default_scene`: remove `registry` param from `BarSprite(...)` call since it no longer needs it.

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/ -v`
Expected: ALL PASS

**Step 5: Commit**

```
Inline progress bar logic into BarSprite, remove ProgressArchetype dependency
```

---

### Task 8: Extract weather physics into utility module

**Files:**
- Create: `clarvis/display/sprites/weather_physics.py`
- Test: `tests/unit/test_weather_physics.py`

**Context:** The Numba JIT functions (`_tick_physics_batch`, `_spawn_particles`, `_compute_render_cells`) and data structures (`Shape`, `Particle`, `BoundingBox`) are pure functions on numpy arrays. Extract them to a utility module before inlining WeatherArchetype into WeatherSandbox.

**Step 1: Write test for the extracted module**

```python
"""Tests for weather physics utility functions."""
import numpy as np
from clarvis.display.sprites.weather_physics import (
    Shape,
    BoundingBox,
    tick_physics_batch,
    spawn_particles,
    compute_render_cells,
)


class TestShape:
    def test_parse_single_line(self):
        s = Shape.parse(".")
        assert s.width == 1
        assert s.height == 1

    def test_parse_multiline(self):
        s = Shape.parse(" . \n...")
        assert s.width == 3
        assert s.height == 2


class TestBoundingBox:
    def test_contains(self):
        bb = BoundingBox(5, 5, 3, 3)
        assert bb.contains(5, 5)
        assert bb.contains(7, 7)
        assert not bb.contains(8, 8)


class TestPhysicsBatch:
    def test_particles_move(self):
        n = 3
        p_x = np.array([1.0, 2.0, 3.0])
        p_y = np.array([1.0, 2.0, 3.0])
        p_vx = np.array([0.1, 0.1, 0.1])
        p_vy = np.array([0.2, 0.2, 0.2])
        p_age = np.zeros(n, dtype=np.int64)
        p_lifetime = np.full(n, 1000, dtype=np.int64)
        p_shape_idx = np.zeros(n, dtype=np.int64)

        new_n = tick_physics_batch(
            p_x, p_y, p_vx, p_vy, p_age, p_lifetime, p_shape_idx,
            n, 1, 100.0, 100.0, 0.0,  # death_prob=0 so none die
        )
        assert new_n == 3
        assert p_x[0] > 1.0  # moved
```

**Step 2: Create the utility module**

Move from `archetypes/weather.py` to `sprites/weather_physics.py`:
- `Shape` dataclass + `parse()`
- `Particle` dataclass
- `BoundingBox` dataclass + `contains()`
- `_tick_physics_batch` → `tick_physics_batch` (public)
- `_spawn_particles` → `spawn_particles` (public)
- `_compute_render_cells` → `compute_render_cells` (public)
- Numba import with fallback

Keep the functions identical — just move them.

**Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_weather_physics.py -v`
Expected: ALL PASS

**Step 4: Commit**

```
Extract weather physics functions to standalone utility module
```

---

### Task 9: Inline WeatherArchetype into WeatherSandbox

**Files:**
- Modify: `clarvis/display/sprites/system.py`
- Test: `tests/unit/test_sprites_system.py`

**Context:** This is the largest migration. WeatherArchetype has particle spawning, physics, shape caching, ambient clouds, exclusion zones, and JIT-accelerated rendering. Move all of this into WeatherSandbox (now renamed WeatherSprite), importing physics functions from `weather_physics.py`.

**Step 1: Write regression test**

```python
class TestWeatherRegression:
    def test_rain_produces_particles(self):
        """After several ticks of rain, weather should render some chars."""
        scene = build_default_scene(width=43, height=17)
        weather = next(s for s in scene.registry.alive() if isinstance(s, WeatherSandbox))
        for _ in range(20):
            weather.tick(weather_type="rain", weather_intensity=0.8, wind_speed=5.0)
        out_c = np.full((17, 43), SPACE, dtype=np.uint32)
        out_k = np.zeros((17, 43), dtype=np.uint8)
        weather.render(out_c, out_k)
        assert np.any(out_c != SPACE)
```

**Step 2: Inline**

Replace `WeatherSandbox` with a self-contained class that:
- Reads particle shapes from `ElementRegistry`
- Reads weather type definitions from `ElementRegistry`
- Uses `weather_physics.py` functions for tick/spawn/render
- Renders directly to `out_chars`/`out_colors` (no scratch Layer)
- Keeps ambient cloud logic
- Keeps exclusion zone logic

This is the full body of the old `WeatherArchetype` (~360 lines) minus the `Archetype` base class, `Layer` dependency, and `render()` method (which gets rewritten to output directly to numpy arrays instead of `layer.put()`).

The render method changes from:
```python
layer.put(cx, cy, char, color)
```
To:
```python
if 0 <= cx < width and 0 <= cy < height:
    out_chars[cy, cx] = ord(char)
    out_colors[cy, cx] = color
```

**Step 3: Remove all archetype imports from system.py**

After this task, system.py should NOT import from `..archetypes` or `..pipeline`.

**Step 4: Run full test suite**

Run: `.venv/bin/python -m pytest tests/unit/ -v`
Expected: ALL PASS

**Step 5: Commit**

```
Inline weather simulation into WeatherSandbox, remove WeatherArchetype dependency
```

---

## Phase C: Delete Dead Code

### Task 10: Delete archetypes and pipeline

**Files:**
- Delete: `clarvis/display/archetypes/` (entire directory)
- Delete: `clarvis/display/pipeline.py`
- Modify: `clarvis/display/__init__.py`
- Modify: any remaining imports

**Context:** After Tasks 6-9, no code should import from archetypes or pipeline. Verify, then delete.

**Step 1: Verify no imports remain**

```bash
grep -r "from.*archetypes\|from.*pipeline\|import.*Layer\|import.*Archetype" clarvis/ --include="*.py"
```

If any remain, fix them first.

**Step 2: Delete the files**

```bash
rm -rf clarvis/display/archetypes/
rm clarvis/display/pipeline.py
```

**Step 3: Update display/__init__.py**

```python
from .socket_server import get_socket_server

__all__ = ["get_socket_server"]
```

**Step 4: Run full test suite**

Run: `.venv/bin/python -m pytest tests/unit/ -v`
Expected: ALL PASS

**Step 5: Verify daemon imports**

```bash
.venv/bin/python -c "from clarvis.daemon import CentralHubDaemon; print('OK')"
```

**Step 6: Commit**

```
Delete archetypes/ and pipeline.py — all rendering logic now in sprites
```

---

## Summary

| Phase | Tasks | What happens | LOC change (est.) |
|-------|-------|-------------|-------------------|
| A | 1-5 | Fix review findings | ~+30 / -10 |
| B | 6-9 | Inline archetypes into sprites | ~+400 / -0 (new code in system.py) |
| C | 10 | Delete dead code | ~-1010 (archetypes/ + pipeline.py) |
| **Net** | | | **~-590 lines** |

After completion:
- `sprites/` is fully self-contained — reads from ElementRegistry, renders to numpy
- No Layer, no Archetype, no pipeline.py
- `elements/` and ElementRegistry stay (YAML-driven visual definitions)
- Weather physics extracted to reusable utility module
