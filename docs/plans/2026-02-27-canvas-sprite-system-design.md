# Canvas & Sprite System Design

**Date:** 2026-02-27
**Status:** Design
**Scope:** Display system overhaul — everything is a sprite on a shared canvas

## Vision

The 43x17 ASCII grid becomes a **living canvas** where every visual element — the face, progress bar, lyrics, creatures, generative art, buttons, info panels — is a **sprite**. Sprites are positioned freely, composited by priority, and managed by a **SceneManager**. The agent (Clarvis) can see the canvas as text and curate it via MCP tools. Context triggers auto-manage sprites based on events (music playing, status changes, time of day).

The current system has 3 hardcoded archetypes, 5 fixed layers, and ~60% empty space. The new system is an open canvas where anything can appear anywhere.

### Design Inspirations

- **VGDL** (`directory/genlm/vgdl/`) — SpriteRegistry, hierarchical types, pluggable physics, kill list, domain/level separation, definition-order z-layering
- **Clarvis WeatherArchetype** — Numba JIT particle physics, pre-allocated numpy SoA arrays, shape pre-computation, exclusion zones
- **Clarvis FaceArchetype** — Pre-computed frame matrices, YAML-driven animation, status-based state machine
- **Clarvis ElementRegistry** — Auto-discovery of YAML assets by directory, change notification infrastructure

---

## 1. Core Abstractions

### 1.1 Sprite

The fundamental visual unit. Everything on the canvas is a sprite.

```python
class Sprite:
    """Base class for all visual elements on the canvas."""

    # Identity (VGDL pattern: key=type, id=unique instance)
    key: str                    # sprite type name ("cat", "lyrics", "face")
    id: str                     # unique instance ID ("cat.0", "lyrics.main")
    stypes: list[str]           # type hierarchy for group queries

    # Spatial
    x: int                      # grid column (0-based)
    y: int                      # grid row (0-based)
    width: int                  # bounding box width in cells
    height: int                 # bounding box height in cells

    # Compositing
    priority: int               # draw order (0=back, 100=front)
    transparent: bool = True    # if True, space chars pass through

    # Physics / Behavior
    behavior: Behavior | None   # pluggable movement/update logic
    speed: float = 0            # movement speed (cells per tick)
    orientation: tuple[int,int] # movement direction (dx, dy)

    # Visual
    color: int = 0              # ANSI-256 color code (0=theme default)
    visible: bool = True

    # Lifecycle
    alive: bool = True
    age: int = 0                # ticks since spawn
    lifetime: int = -1          # -1 = immortal, >0 = auto-dies

    # State serialization (VGDL pattern)
    state_attributes: ClassVar[list[str]] = [
        'x', 'y', 'alive', 'visible', 'age', 'priority'
    ]

    # --- Interface ---
    def tick(self, scene: SceneManager) -> None:
        """Called every frame. Advance animation, apply behavior."""
        self.age += 1
        if self.lifetime > 0 and self.age >= self.lifetime:
            self.alive = False
            return
        if self.behavior:
            self.behavior.update(self, scene)

    def render(self, layer: Layer) -> None:
        """Draw this sprite onto the given layer at (self.x, self.y)."""
        ...  # subclass implements

    def configure(self, **kwargs) -> None:
        """Runtime reconfiguration by agent. Dumps kwargs onto self."""
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get_state(self) -> dict:
        """Serializable state for agent queries and save/restore."""
        return {attr: getattr(self, attr) for attr in self.state_attributes}
```

### 1.2 Behavior (VGDL Physics Analog)

Pluggable movement/update component. Replaces VGDL's `physicstype`.

```python
class Behavior:
    """Base behavior — no-op."""
    def update(self, sprite: Sprite, scene: SceneManager) -> None: ...

class StaticBehavior(Behavior):
    """No movement. Default."""
    pass

class DriftBehavior(Behavior):
    """Slow constant movement in orientation direction."""
    def update(self, sprite, scene):
        # Advance position by speed * orientation, with edge wrapping or bounce

class WanderBehavior(Behavior):
    """Random direction changes. VGDL RandomNPC analog."""
    prob: float = 0.1  # probability of direction change per tick
    def update(self, sprite, scene):
        # Randomly change orientation, then move

class PatrolBehavior(Behavior):
    """Move between two points, reverse at each end. VGDL Walker analog."""
    def update(self, sprite, scene):
        # Move in orientation, reverse when hitting bounds or patrol limits

class ScrollBehavior(Behavior):
    """Vertical or horizontal scrolling content. For lyrics, ticker, feed."""
    direction: str = "up"  # "up", "down", "left", "right"
    rate: float = 1.0      # lines/chars per tick
    def update(self, sprite, scene):
        # Shift content, not position (content scrolls within fixed bbox)

class LifecycleBehavior(Behavior):
    """Grow, exist, shrink, die. For plants, effects."""
    phases: list[dict]  # [{duration: N, frame: "seed"}, {duration: N, frame: "sprout"}, ...]
    def update(self, sprite, scene):
        # Advance through lifecycle phases based on age
```

Behaviors can be composed: a sprite could have both `WanderBehavior` (for movement) and `LifecycleBehavior` (for visual phases). If composition is needed, use a `CompositeBehavior` wrapper. Start simple — single behavior per sprite — and add composition when needed.

### 1.3 SpriteRegistry (VGDL Pattern)

Central sprite manager with live/dead tracking and type-based queries.

```python
class SpriteRegistry:
    """Manages all sprite instances. VGDL SpriteRegistry pattern."""

    _live: dict[str, Sprite]    # id -> sprite (alive sprites)
    _dead: dict[str, Sprite]    # id -> sprite (dead but not destroyed)
    _counters: dict[str, int]   # key -> next instance number

    def create(self, key: str, name: str | None = None, **kwargs) -> Sprite:
        """Create a sprite. Auto-generates id as '{key}.{N}' if no name given."""

    def kill(self, id: str) -> None:
        """Move sprite to dead storage. Deferred — actual removal in process_kills()."""

    def destroy(self, id: str) -> None:
        """Permanent removal from both live and dead."""

    def get(self, id: str) -> Sprite | None:
        """Get sprite by unique id."""

    def with_stype(self, stype: str) -> list[Sprite]:
        """All live sprites matching a type (including parent types). VGDL pattern."""

    def alive(self) -> Iterable[Sprite]:
        """All live sprites, sorted by priority."""

    def sprites_at(self, x: int, y: int) -> list[Sprite]:
        """All live sprites whose bounding box contains (x, y)."""
```

### 1.4 SceneManager

The canvas controller. Orchestrates sprites, handles triggers, exposes the agent API.

```python
class SceneManager:
    """Manages the sprite canvas. Replaces FrameRenderer's manual orchestration."""

    registry: SpriteRegistry
    kill_list: list[str]            # deferred removal (VGDL pattern)
    triggers: list[Trigger]         # context-driven auto-management
    sprite_types: dict[str, type]   # "cat" -> CatSprite class (type registry)
    element_registry: ElementRegistry  # YAML asset access
    width: int                      # grid width (43)
    height: int                     # grid height (17)

    def tick(self) -> None:
        """Per-frame update. VGDL tick pattern."""
        # 1. Update all alive sprites in priority order
        for sprite in self.registry.alive():
            sprite.tick(self)
        # 2. Process kill list (deferred removal)
        self._process_kill_list()
        # 3. Check triggers (auto-spawn/remove based on context)
        self._check_triggers()

    def render(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None:
        """Render all alive+visible sprites onto the output grid."""
        for sprite in self.registry.alive():
            if sprite.visible:
                sprite.render_to(out_chars, out_colors)

    # --- Agent API (exposed via MCP canvas tools) ---

    def spawn(self, sprite_type: str, name: str,
              x: int, y: int, **config) -> Sprite:
        """Create and register a sprite."""

    def remove(self, name: str) -> None:
        """Mark sprite for death (processed end of tick)."""

    def move(self, name: str, x: int, y: int) -> None:
        """Reposition a sprite."""

    def configure(self, name: str, **config) -> None:
        """Update sprite configuration."""

    def list_sprites(self) -> list[dict]:
        """All sprites with id, type, position, state."""

    def snapshot(self) -> str:
        """Return the current grid as readable text.
        The agent can SEE the canvas — it's just text."""

    def load_scene(self, scene_name: str) -> None:
        """Load a YAML scene definition, spawning its sprites."""

    def unload_scene(self, scene_name: str) -> None:
        """Remove all sprites that were loaded by a scene."""

    def clear(self) -> None:
        """Remove all dynamic sprites (keep system sprites like face/bar)."""
```

---

## 2. Sprite Catalog

The hierarchy is kept shallow — a few base classes, with diversity coming from YAML definitions + agent programming, not deep inheritance.

### 2.1 Base Types (Python classes)

See **section 3 (Implementation Pattern Taxonomy)** for the full class hierarchy derived from rendering mechanics. Summary:

```
Sprite (base)
├── Cel                     — YAML-driven frame animation (pre-drawn ASCII art)
├── Reel                    — Text content + viewport + temporal effects (scroll/reveal/marquee)
├── Sandbox                 — Programmable computational simulations (agent-defined rules)
├── Control                 — Click regions + action dispatch
├── PostFx                  — Post-processing on composited output
├── FaceSprite              — System wrapper (FaceArchetype)
├── WeatherSprite           — System wrapper (WeatherArchetype)
└── BarSprite               — System wrapper (ProgressArchetype)
```

Most sprite diversity comes from **configuration**, not subclassing. A `Cel` with `behavior: wander` and creature frames IS a creature. A `Sandbox` with `engine: automaton` and agent-defined rules IS generative art. 5 implementation modules cover all ~50 sprite ideas.

### 2.2 System Sprites

Auto-created at startup, survive `clear()`, special internal machinery.

- **WeatherSprite** — Numba JIT particle physics, full-grid, exclusion zones
- **FaceSprite** — pre-computed numpy matrices, status-driven animation
- **BarSprite** — percentage-cached progress bar
- **MicButton** — Control, toggle wake word listening

### 2.3 Programmable Engines — Agent as Programmer

**This is NOT a screensaver.** Pre-defined algorithm classes with fixed behavior are screensavers. Instead, sprites expose **computational engines** that the agent programs by defining rules, parameters, initial conditions, and character mappings. The agent is the artist.

Each engine type accepts structured configuration that defines its behavior:

**Cellular Automaton Engine** (`engine: automaton`)
Agent defines: neighborhood type (Moore/von Neumann/hex/custom offsets), birth/survive rule sets (arbitrary — not just Conway's), number of states, char mapping per state, wrapping, initial seed pattern or random density. Supports 1D (scrolling downward) and 2D modes.
```
canvas_spawn("automaton", "myart", 1, 1, config={
  "rules": {"birth": [3, 6, 7], "survive": [2, 3]},
  "states": 3,
  "chars": {0: " ", 1: "░", 2: "█"},
  "neighborhood": "moore",
  "seed": {"type": "random", "density": 0.35},
  "width": 15, "height": 10
})
```

**Particle Engine** (`engine: particles`)
Agent defines: emitter positions + rates, force vectors (gravity, wind, attractor points), lifetime distributions, char sets, boundary behavior (wrap/bounce/die). Generalization of the existing weather system.
```
canvas_spawn("particles", "sparks", 10, 8, config={
  "emitters": [{"x": 5, "y": 8, "rate": 0.3, "spread": 1.5}],
  "forces": [{"type": "gravity", "strength": 0.08}],
  "chars": ["*", ".", "'", "·"],
  "lifetime": [10, 25],
  "width": 12, "height": 8
})
```

**L-System Engine** (`engine: lsystem`)
Agent provides: axiom, production rules, angle, iteration depth, turtle-to-char mapping. Procedural trees, curves, fractals. Grows step by step.
```
canvas_spawn("lsystem", "tree", 10, 14, config={
  "axiom": "F",
  "rules": {"F": "FF+[+F-F-F]-[-F+F+F]"},
  "angle": 22.5,
  "iterations": 4,
  "chars": {"F": "|", "+": "/", "-": "\\", "[": "{", "]": "}"}
})
```

**Boids Engine** (`engine: boids`)
Agent defines: flock size, separation/alignment/cohesion weights, speed, char per boid, boundary behavior. Emergent flocking from simple rules.

**Wave Engine** (`engine: waves`)
Agent defines: wave sources (position, frequency, amplitude, phase), interference mode, char gradient (e.g., `" ·∙•●"`). Dynamically add/remove sources.

**Reaction-Diffusion Engine** (`engine: reaction_diffusion`)
Agent sets: feed rate, kill rate, diffusion rates. Turing patterns emerge — spots, stripes, spirals, mazes. Mapped to ASCII density.

**Sandpile Engine** (`engine: sandpile`)
Agent drops grains at positions. Avalanches cascade. Beautiful fractal patterns emerge from simple toppling rules.

### 2.4 Reactive / Data-Driven Sprites

Sprites that breathe with Claude's activity and real-world context:

- **Heartbeat** — EKG trace pulsing with activity rate. Flatlines during idle, spikes during intense tool use, arrhythmia on errors. Configurable chars (`─╲╱─`).
- **Thought bubbles** — `○◯` float upward from the face when thinking, containing word fragments. Pop and vanish at the top. Spawn rate = thinking intensity.
- **Error lightning** — test failures / errors crack lightning across the grid. Afterglow traces fade over several frames. Triggered by `hook:event` errors.
- *Stashed: Token river, code rain (content pipeline complexity, privacy), git bonsai (complex git parsing), memory web (needs graph layout), word cloud (collision avoidance at 43x17)*

### 2.5 Living World Sprites

The face lives in a world with life, physics, and ecology:

- **Creatures** (YAML-defined) — cat, bird, fish, butterfly, firefly, spider, snake, frog. Multi-frame ASCII art + behavior (wander, patrol, drift, lifecycle). Agent spawns them.
- **Vine/ivy** — grows along grid edges frame by frame. Tendrils branch, creep, flower. Gets trimmed when sprites spawn nearby. Regrows over idle time.
- **Campfire** — flickering particle flame with rising sparks and curling smoke. Warmth glow radius.
- **Aquarium** — fish swimming, bubbles rising, seaweed swaying. The face becomes underwater.
- **Shadow** — face casts a shadow whose angle tracks sun/moon position. Lengthens at dawn/dusk.
- **Rain puddles** — water pools at bottom during real rain weather. Ripples from new drops. Evaporates when cleared.
- **Snowdrift** — snow accumulates against the face and bottom during snow. Melts when weather changes.
- **Cobwebs** — form in unused corners over idle time. Cleared by activity. Spread if idle for hours.
- *Stashed: Ecosystem (depends on creatures), ant highway (complex pathfinding), bioluminescent deep (niche theme), coral reef (complex growth), moss (overlaps vine/ivy)*

### 2.6 Music-Reactive Sprites

Beyond lyrics — sprites that feel the music:

- **Lyrics** — Spotify-synced, current line highlighted, optional translation, scrolling context.
- **Playback controls** — ⏮ ⏯ ⏭ as clickable Controls. Show track progress.
- **Now-playing ticker** — horizontal marquee: "Artist — Track Name".
- **Spectrum analyzer** — frequency bars bouncing. Agent defines bar count, char gradient, color.
- **Vinyl record** — spinning `(( o ))` with track name. RPM synced to BPM.
- **Beat grid** — 16-step drum pattern, highlighting current beat position.
- **BPM pendulum** — visual metronome ticking at song tempo.
- *Stashed: Piano roll (complex note data parsing)*

### 2.7 Typography / Text Art Sprites

- **Concrete poetry** — text shaped like its subject. A poem about rain shaped like rain.
- **Kanji study** — large decorative character with readings and meaning. Agent picks.
- **Quote reveal** — text appears character by character, hangs, dissolves. Agent picks quotes.
- **Cipher stream** — encrypted-looking noise slowly decoding to a message. Agent sets message.
- **ASCII clock** — large decorative clock. Styles: seven-segment, dot-matrix, binary, sundial.
- **Typewriter** — text appearing with mechanical cadence. Carriage return animation.

### 2.8 Interactive / Playful Sprites

- **Buttons** — any clickable element. Label + click region + action callback.
- **Controls cluster** — group of buttons (playback, volume, settings).
- **Tamagotchi mode** — the face IS a pet. Happiness tracks interaction frequency. Gets hungry when ignored. Agent defines mood rules.
- **Maze runner** — procedural maze with a dot solving it. Agent defines parameters.
- **Fortune cookie** — cracks open with animation, reveals agent-written wisdom.

### 2.9 Meta / Self-Referential Sprites

- **Sprite debugger** — semi-transparent overlay showing all bounding boxes, priorities, ages.
- **Canvas replay** — tiny filmstrip of recent canvas states. Session time-lapse.
- **Dream mode** — during long idle, face "sleeps" and "dreams" — surreal sprite compositions cycle.
- **Boot sequence** — retro POST/boot animation on startup before normal scene loads.
- **Glitch** — intentional visual artifacts (shifted rows, corrupted chars, color noise). Aesthetic chaos.

### System vs Dynamic Sprites

- **System sprites** (face, bar, weather, mic): auto-created at startup, survive `clear()`, special internal machinery. `system: bool = True`.
- **Dynamic sprites** (everything else): created by agent, triggers, or scene definitions. Removed by `clear()`.

---

## 3. Implementation Pattern Taxonomy

The sprite catalog (section 2) organizes ideas by *domain* — music, living world, typography. But implementation doesn't care about domain. A scrolling lyrics panel and a now-playing ticker are the same code with different data. A vine growing along edges and a cellular automaton are both grid-state sprites with step functions. The real modules emerge from **rendering mechanics**, not from what the sprite "is about."

This section identifies the implementation patterns that generalize across all kept+stashed sprites, and maps them to concrete modules.

### 3.1 Pattern Map

```
┌─────────────────────────────────────────────────────────────────┐
│                    Sprite (base)                                │
│  identity, position, priority, lifecycle, state_attributes      │
│  + Behavior (composition axis: static/drift/wander/patrol/...)  │
├─────────────┬───────────┬──────────────┬───────────┬────────────┤
│     Cel     │   Reel    │   Sandbox    │  Control  │   PostFx   │
│             │           │              │           │            │
│ YAML frames │ text +    │ numpy state +│ click     │ post-      │
│ + animation │ viewport +│ step func +  │ region +  │ processing │
│ cycle       │ temporal  │ char map     │ action    │ on output  │
│             │ effect    │              │           │            │
├─────────────┼───────────┼──────────────┼───────────┼────────────┤
│ creatures   │ lyrics    │ automaton    │ buttons   │ glitch     │
│ vinyl       │ ticker    │ particles    │ playback  │ debugger   │
│ pendulum    │ quote     │ lsystem      │ mic       │            │
│ concrete    │ cipher    │ boids        │ controls  │            │
│ kanji       │ typewriter│ waves        │           │            │
│ fortune     │ boot seq  │ react-diff   │           │            │
│ plant       │ clock     │ sandpile     │           │            │
│             │           │ vine/cobweb  │           │            │
│             │           │ maze runner  │           │            │
└─────────────┴───────────┴──────────────┴───────────┴────────────┘

Cross-cutting concerns (not sprite subclasses):
  DataSource  — adapters for StateStore, time, Spotify, hooks, git
  Emitter     — meta-behavior that spawns child sprites at a rate
  Scene       — YAML-defined sprite compositions + trigger system
```

### 3.2 Pattern A: Cel — YAML-Driven Frame Animation

**Mechanic**: Load multi-frame ASCII art from YAML. Animation sequences cycle frames by tick counter. Position controlled by behavior plugin. The workhorse for any sprite that "looks like something."

**Sprites it covers**:
- Creatures (cat, bird, fish, butterfly, firefly, spider, snake, frog) — frames + wander/drift/patrol behavior
- Vinyl record — rotating frames synced to BPM
- BPM pendulum — swing animation frames
- Concrete poetry — shaped text as a static frame
- Kanji study — large character frame + metadata
- Fortune cookie — multi-phase frames (closed → cracking → open)
- Plant — lifecycle phases (seed → sprout → grown)
- Shadow — angle-dependent frame selection
- Campfire — base flame frames (sparks/smoke can be a child particle emitter)

**Module**: `sprites/cel.py`
- Loads `frames:` dict from YAML (name → ASCII art string, parsed to numpy uint32 matrix)
- `animation:` dict maps animation names to frame sequence lists (reuse ElementRegistry's shorthand expansion: `$blink`, `*3`)
- `tick()`: advance animation counter, select frame
- `render_to()`: blit current frame matrix at (x, y) with color
- Integrates with `Behavior` for movement

**Key infrastructure**: YAML frame parsing (already exists in FaceArchetype/ElementRegistry), animation sequence expansion, frame matrix pre-computation.

### 3.3 Pattern B: Reel — Text Content with Temporal Effects

**Mechanic**: Text content rendered within a viewport with a temporal effect (scrolling, character-by-character reveal, horizontal marquee, or static display). Different data sources feed the same rendering machinery.

**Sprites it covers**:
- Lyrics — vertical scroll, highlight current line, content from Spotify
- Now-playing ticker — horizontal marquee, content from Spotify
- Quote reveal — char-by-char reveal + dissolve, content from agent
- Cipher stream — noise→decode transition, content from agent
- Typewriter — char reveal with carriage-return cadence, content from agent
- Boot sequence — line-by-line reveal, scripted content
- ASCII clock — static formatted, content from system time
- Beat grid — step highlight, content from Spotify beat position
- Heartbeat — 1D waveform trace chars, content from activity rate
- *Stashed: Code rain (vertical cascade), piano roll (horizontal scroll), word cloud*

**Module**: `sprites/reel.py`
- `mode` enum: `SCROLL` | `REVEAL` | `MARQUEE` | `STATIC`
- `content`: text buffer (string or list of lines)
- `viewport`: width × height window into content
- `SCROLL`: offset advances per tick, optional line highlight. Direction: vertical or horizontal.
- `REVEAL`: cursor advances through content (char/word/line granularity), optional hold + dissolve
- `MARQUEE`: horizontal loop with configurable speed
- `STATIC`: just render text, refresh on data change
- `set_content(text)`: update the text buffer (called by data source or agent)

**Key infrastructure**: Text wrapping/clipping to viewport, reveal cursor tracking, dissolve mask (random char decay), highlight styling (color change for current line/word).

### 3.4 Pattern C: Sandbox — Programmable Computational Grid

**Mechanic**: numpy state array + per-tick step function + state→char mapping. The agent programs the sandbox by providing rules, parameters, and initial conditions via config. This is the generalization of all "simulation" sprites.

**Sprites it covers**:
- Cellular automaton — grid rules (birth/survive/states/neighborhood)
- Reaction-diffusion — feed/kill/diffusion rates → Turing patterns
- Sandpile — toppling rules, grain drops
- Wave interference — source superposition, char gradient
- L-System — string rewriting + turtle rendering
- Boids — N-body flocking with steering weights
- Particles — emitters + forces + lifetime (generalized weather)
- Vine/ivy — edge-growth automaton with trim-on-proximity events
- Cobwebs — idle-growth automaton with activity-clearing events
- Snowdrift — weather-driven accumulation + melt
- Rain puddles — weather-driven pooling + ripple + evaporation
- Maze runner — procedural maze gen (CA) + pathfinding dot
- Spectrum analyzer — frequency bars (vertical particles or bar chart)
- *Stashed: Token river, ecosystem, ant highway, bioluminescent, coral reef, moss*

**Module**: `sprites/sandbox/`
```
sandbox/
├── base.py          — Sandbox base: state array, step(), char_map, configure()
├── registry.py      — Engine type registry (name → engine class)
├── automaton.py     — Cellular automaton (1D/2D, arbitrary rules, Numba JIT)
├── particles.py     — Particle system (SoA arrays, emitters, forces, Numba JIT)
├── lsystem.py       — L-System (string rewrite + turtle render, no JIT needed)
├── boids.py         — Flocking (N-body forces, Numba JIT)
├── waves.py         — Wave interference (source superposition, per-cell eval)
├── reaction_diffusion.py — Turing patterns (Laplacian convolution, Numba JIT)
└── sandpile.py      — Avalanche dynamics (toppling rules)
```

**Sandbox base interface**:
```python
class Sandbox(Sprite):
    engine_type: str
    state: np.ndarray           # engine-specific shape
    char_map: dict[int, str]    # state value → display char
    width: int
    height: int

    def configure(self, **config): ...   # agent reprograms rules
    def step(self): ...                  # one simulation tick
    def render_to(self, out_chars, out_colors): ...  # state → chars → blit
```

**Growth sprites** (vine, cobweb, snowdrift, puddles) are sandboxes with **event hooks** — they subscribe to SignalBus events (`hook:event`, `weather.changed`) that trigger growth/decay in their grid state. Same `step()` mechanic, just with external stimuli added.

**Numba JIT**: automaton, particles, boids, reaction-diffusion benefit from JIT. Others (lsystem, waves, sandpile) are fast enough without. The existing WeatherArchetype JIT functions serve as the template — SoA arrays, `@njit(cache=True)`, Python bridge for layer writes.

### 3.5 Pattern D: Control — Click Regions

**Mechanic**: Renders a label/icon. Registers bounding box with widget's ClickRegionManager. Dispatches action callback on click.

**Sprites it covers**:
- Buttons (generic label + action)
- Playback controls (⏮ ⏯ ⏭)
- Mic toggle
- Controls cluster (group of buttons)
- Tamagotchi interactions (pet/feed)

**Module**: `sprites/control.py`
- `label`: display text
- `action`: callback identifier (string → handler function mapping)
- `on_spawn()`: register click region
- `on_death()`: deregister click region
- `on_click()`: dispatch action

Controls clusters are just multiple Controls spawned together by a scene definition. No special compound class needed.

### 3.6 Pattern E: PostFx — Post-Processing

**Mechanic**: Runs *after* all normal sprites render. Operates on the composited output arrays. Injects visual artifacts, overlays debug info, or applies global transformations.

**Sprites it covers**:
- Glitch — shifted rows, corrupted chars, color noise
- Sprite debugger — bounding box overlay, priority labels
- Error lightning — grid-wide flash + afterglow fade (alternative: could be particle-based)
- Dream mode — global color shift / blur during idle sleep

**Module**: `sprites/postfx.py`
- `PostFx(Sprite)` with `render_post(out_chars, out_colors)` instead of `render_to()`
- SceneManager calls `render_post()` in a second pass after normal sprite compositing
- PostFx sprites see the final composited output and can modify it in-place

### 3.7 Cross-Cutting: Data Sources

Not a sprite subclass — a composition concern. Many sprites need external data (Spotify track info, system time, activity rate, weather state). Rather than each sprite polling independently:

**Module**: `sprites/sources.py`
- `DataSource` protocol: `poll() → dict`, `subscribe(callback)`
- Adapters: `StateStoreSource` (reads StateStore sections), `SpotifySource` (track/lyrics/beat), `TimeSource` (clock), `HookSource` (activity rate from hook events)
- Sprites that need data hold a `source` reference. SceneManager ticks sources alongside sprites.
- Reel's `set_content()` is called by its source adapter when data changes
- Sandbox's event hooks use source callbacks

This prevents N sprites each independently polling Spotify or reading StateStore.

### 3.8 Cross-Cutting: Emitter

A meta-behavior, not a sprite subclass. Any sprite can be an emitter — it spawns child sprites at a configurable rate within an area.

- Emitter config: `sprite_def` (YAML reference), `rate` (spawn probability per tick), `max_children`, `area` (spawn region)
- Children are normal sprites (Cels, usually) with lifetime
- Emitter tracks children, culls dead ones, respawns up to max
- Used by: firefly swarms, thought bubbles, sparkle effects, campfire sparks

This could be a `Behavior` subclass or a mixin on Sprite. It's orthogonal to how the sprite renders.

### 3.9 Cross-Cutting: Scene & Trigger Orchestration

The scene/trigger system is the management layer above sprites.

**Module**: `sprites/scenes.py`
- Scene YAML loading (sprite compositions)
- Scene lifecycle (load → active → unload, tracking which sprites belong to which scene)
- Trigger evaluation (event → action mapping, cooldown)
- Dream mode / scene rotation are orchestrators that load/unload scenes on timers

### 3.10 System Wrappers

Thin adapter sprites wrapping existing heavy archetypes. They adapt the existing `FaceArchetype`, `WeatherArchetype`, and `ProgressArchetype` to the `Sprite` interface without reimplementing their internals.

**Module**: `sprites/system.py`
- `FaceSprite` — delegates tick/render to `FaceArchetype`, exposes status-based animation
- `WeatherSprite` — delegates to `WeatherArchetype` (Numba JIT particles), reports exclusion zones
- `BarSprite` — delegates to `ProgressArchetype` (percentage cache)

These are migration shims. As the sandbox system matures, weather could migrate to `ParticleSandbox` and the face to `Cel`, but there's no rush — the wrappers work.

### 3.11 Summary: Idea → Pattern Mapping

| Sprite Idea | Pattern | Module |
|---|---|---|
| **Creatures** (cat, bird, fish, butterfly, firefly, spider, snake, frog) | Cel | `cel` + behaviors |
| **Plant** | Cel | `cel` + lifecycle behavior |
| **Vine/ivy**, **Cobwebs** | Sandbox (grid) | `sandbox/automaton` + event hooks |
| **Campfire** | Cel + Emitter | `cel` (base flame) + emitter (sparks) |
| **Aquarium** | Scene composition | `scenes` (fish + bubbles + seaweed) |
| **Shadow** | Cel | `cel` (angle-selected frame) + data source |
| **Rain puddles**, **Snowdrift** | Sandbox (grid) | `sandbox/automaton` + weather event hooks |
| **Lyrics** | Reel (scroll) | `reel` + Spotify source |
| **Playback controls** | Control | `control` |
| **Now-playing ticker** | Reel (marquee) | `reel` + Spotify source |
| **Spectrum analyzer** | Sandbox (particles/bars) | `sandbox/particles` or `reel` |
| **Vinyl record** | Cel | `cel` (rotating frames) |
| **Beat grid** | Reel (static, highlight) | `reel` + Spotify source |
| **BPM pendulum** | Cel | `cel` (swing animation) |
| **Concrete poetry** | Cel | `cel` (shaped text as frame) |
| **Kanji study** | Cel + Reel | `cel` (main char) + `reel` (readings) |
| **Quote reveal** | Reel (reveal) | `reel` |
| **Cipher stream** | Reel (reveal) | `reel` (noise→decode mode) |
| **ASCII clock** | Reel (static) | `reel` + time source |
| **Typewriter** | Reel (reveal) | `reel` |
| **Buttons**, **Controls cluster** | Control | `control` |
| **Tamagotchi mode** | Cel + data source | `cel` (mood faces) + state machine |
| **Maze runner** | Sandbox (grid) | `sandbox/automaton` (gen) + pathfinding |
| **Fortune cookie** | Cel → Reel | `cel` (crack animation) → `reel` (reveal) |
| **Heartbeat** | Reel (waveform) | `reel` (1D trace) + activity source |
| **Thought bubbles** | Emitter + Cel | emitter + `cel` (bubble chars) |
| **Error lightning** | PostFx or Sandbox | `postfx` (grid flash) or `sandbox/particles` |
| **Cellular automaton** | Sandbox (grid) | `sandbox/automaton` |
| **Particle system** | Sandbox (particles) | `sandbox/particles` |
| **L-System** | Sandbox | `sandbox/lsystem` |
| **Boids** | Sandbox (agents) | `sandbox/boids` |
| **Wave interference** | Sandbox (field) | `sandbox/waves` |
| **Reaction-diffusion** | Sandbox | `sandbox/reaction_diffusion` |
| **Sandpile** | Sandbox (grid) | `sandbox/sandpile` |
| **Sprite debugger** | PostFx | `postfx` |
| **Glitch** | PostFx | `postfx` |
| **Boot sequence** | Reel (reveal) | `reel` |
| **Dream mode** | Scene orchestration | `scenes` (timer-driven scene cycling) |
| **Canvas replay** | PostFx | `postfx` (snapshot ring buffer overlay) |

### 3.12 Module Dependency Graph

```
sprites/
├── core.py              ← everything depends on this
│   (Sprite, SpriteRegistry)
├── behaviors.py         ← cel, sandbox
│   (Static, Drift, Wander, Patrol, Lifecycle)
├── cel.py               ← YAML creature/object definitions
├── reel.py              ← agent/source provides content, no YAML needed
├── control.py           ← depends on ClickRegionManager
├── postfx.py            ← runs post-compositing
├── system.py            ← wraps existing archetypes
├── sources.py           ← adapters, used by reel + sandbox
├── scenes.py            ← orchestration layer above all sprites
│   (SceneManager, Scene, Trigger)
└── sandbox/
    ├── base.py          ← extends Sprite
    ├── registry.py      ← engine type lookup
    ├── automaton.py     ← Numba JIT
    ├── particles.py     ← Numba JIT (generalized weather)
    ├── lsystem.py
    ├── boids.py         ← Numba JIT
    ├── waves.py
    ├── reaction_diffusion.py  ← Numba JIT
    └── sandpile.py
```

### 3.13 Revised Class Hierarchy

The old hierarchy (section 2.1) was organized by what things *are*. The implementation hierarchy is organized by *how they render*:

```
Sprite (base)
├── Cel                   — YAML-driven frame animation + behavior
├── Reel                  — text content + viewport + temporal effect
├── Sandbox               — programmable computational simulation
│   ├── AutomatonSandbox
│   ├── ParticleSandbox
│   ├── LSystemSandbox
│   ├── BoidsSandbox
│   ├── WaveSandbox
│   ├── ReactionDiffusionSandbox
│   └── SandpileSandbox
├── Control               — click region + action dispatch
├── PostFx                — post-processing on composited output
├── FaceSprite            — system wrapper (FaceArchetype)
├── WeatherSprite         — system wrapper (WeatherArchetype)
└── BarSprite             — system wrapper (ProgressArchetype)

Composition axes (not subclasses):
  Behavior                — movement/lifecycle plugins (attached to any sprite)
  DataSource              — external data adapters (feed content to any sprite)
  Emitter                 — child sprite spawning (behavior on any sprite)
```

**5 real implementation modules** (Cel, Reel, Sandbox, Control, PostFx) cover **all ~50 sprite ideas**. Everything else is config, YAML definitions, data source wiring, or scene composition. This is the leverage of the abstraction — diversity from configuration, not from class explosion.

---

## 4. YAML Sprite Definitions

Extend the existing `ElementRegistry` with new element kinds. Auto-discovered via directory naming.

### 4.1 Creature/Object Definitions

```yaml
# elements/sprites/cat.yaml
kind: sprite
name: cat
width: 5
height: 3
behavior: wander
speed: 0.15
lifetime: -1
color: 215          # ANSI warm orange

frames:
  default: |
    /\_/\
    (o.o )
     > ^ <
  walk_right: |
    /\_/\
    (o.o )
     > ^ <
  walk_left: |
     /\_/\
    ( o.o)
    > ^ <
  sleep: |
    /\_/\
    (-.- )
    zzZ

animation:
  idle: [default, default, default, default, sleep, sleep, sleep, default]
  moving: [walk_right, walk_right, walk_left, walk_left]
```

```yaml
# elements/sprites/bird.yaml
kind: sprite
name: bird
width: 3
height: 1
behavior: drift
speed: 0.5
orientation: [1, 0]    # moves right
lifetime: 80           # flies across then dies
color: 7

frames:
  up: "=v="
  down: "=^="

animation:
  flying: [up, up, down, down]
```

```yaml
# elements/sprites/firefly.yaml
kind: sprite
name: firefly
width: 1
height: 1
behavior: wander
speed: 0.1
lifetime: 40
color: 226              # bright yellow

frames:
  bright: "*"
  dim: "."
  off: " "

animation:
  default: [off, off, off, dim, bright, bright, dim, off]
```

```yaml
# elements/sprites/plant.yaml
kind: sprite
name: plant
width: 3
height: 4
behavior: lifecycle
speed: 0
lifetime: -1

phases:
  - duration: 20
    frame: seed
  - duration: 30
    frame: sprout
  - duration: -1         # -1 = stay here forever
    frame: grown

frames:
  seed: |


     .
    ---
  sprout: |

     |
    \|/
    ---
  grown: |
     @
    \|/
    \|/
    ---
```

### 4.2 Generative Art Definitions

```yaml
# elements/sprites/game_of_life.yaml
kind: sprite
name: game_of_life
sprite_type: genart
algorithm: game_of_life
width: 15
height: 10
color: 34               # green
config:
  density: 0.3           # initial random density
  alive_char: "#"
  dead_char: " "
  wrap: true
```

### 4.3 Info Widget Definitions

```yaml
# elements/sprites/clock.yaml
kind: sprite
name: clock
sprite_type: info_widget
width: 8
height: 1
source: time             # reads from StateStore "time" section
format: "{hour}:{minute}"
refresh_ticks: 30        # update every 30 ticks (10s at 3fps)
color: 244               # dim gray
```

---

## 5. Scene Definitions (VGDL Domain/Level Split)

Scenes are compositions of sprites — like VGDL levels but for the canvas.

```yaml
# elements/scenes/default.yaml
name: default
description: "Default idle scene — face, bar, ambient life"
sprites:
  - type: face
    name: face
    x: 29
    y: 5
    priority: 50
    system: true
  - type: bar
    name: bar
    x: 8
    y: 11
    priority: 80
    system: true
  - type: weather
    name: weather
    x: 0
    y: 0
    priority: 0
    system: true
  - type: button
    name: mic_toggle
    x: 39
    y: 14
    priority: 92
    config:
      label: "[M]"
      action: toggle_mic
```

```yaml
# elements/scenes/now_playing.yaml
name: now_playing
description: "Music dashboard — lyrics, controls, now-playing info"
trigger: music.is_playing
sprites:
  - type: lyrics
    name: lyrics_main
    x: 1
    y: 1
    priority: 20
    config:
      max_lines: 5
      show_translation: false
      highlight_current: true
      width: 24
  - type: controls
    name: playback
    x: 1
    y: 14
    priority: 60
    config:
      buttons: [prev, play_pause, next]
  - type: ticker
    name: track_info
    x: 1
    y: 12
    priority: 55
    config:
      source: music.track_info
      width: 25
```

```yaml
# elements/scenes/ambient_life.yaml
name: ambient_life
description: "Living world — creatures wander around the face"
sprites:
  - type: creature
    name: wanderer
    sprite_def: cat          # references elements/sprites/cat.yaml
    x: 3
    y: 10
    priority: 15
  - type: creature
    name: flyer
    sprite_def: bird
    x: -3                    # starts off-screen
    y: 2
    priority: 10
  - type: emitter
    name: fireflies
    x: 5
    y: 4
    priority: 12
    config:
      sprite_def: firefly
      rate: 0.05             # spawn probability per tick
      max_children: 4
      area: [15, 8]          # spawn area from emitter origin
```

### Scene Layering

Multiple scenes can be active simultaneously — their sprites coexist. The `default` scene is always loaded. `now_playing` activates when music starts and deactivates when it stops. `ambient_life` can be loaded by the agent or a trigger.

Scenes track which sprites they spawned, so `unload_scene("now_playing")` removes exactly those sprites.

---

## 6. Trigger System

Context triggers auto-manage sprites based on events. Declared in scene YAML or registered programmatically.

```python
@dataclass
class Trigger:
    event: str              # "music.playing", "status.idle", "time.night", etc.
    action: str             # "load_scene", "spawn", "remove", "configure"
    params: dict            # action-specific parameters
    cooldown: float = 0     # minimum seconds between activations
    last_fired: float = 0
```

### Built-in Event Sources

| Event | Source | Fires when |
|-------|--------|------------|
| `music.playing` | Spotify state | Track starts playing |
| `music.stopped` | Spotify state | Playback stops |
| `music.track_changed` | Spotify state | New track starts |
| `status.<name>` | Hook processor | Claude status changes (idle, thinking, writing, ...) |
| `status.stale` | Staleness timer | 30s of no activity |
| `time.hour.<N>` | Scheduler | Clock strikes hour N |
| `time.night` / `time.day` | Scheduler | Sunrise/sunset transitions |
| `weather.changed` | Weather service | Real weather changes |
| `timer.fired.<name>` | Timer service | Named timer fires |
| `wake_word.detected` | Wake word service | Voice activation |

### Trigger Examples

```yaml
triggers:
  - event: music.playing
    action: load_scene
    params: { scene: now_playing }

  - event: music.stopped
    action: unload_scene
    params: { scene: now_playing }

  - event: status.stale
    action: spawn
    params:
      type: genart
      name: idle_art
      x: 1
      y: 1
      config: { algorithm: random }    # pick a random algorithm
    cooldown: 300                       # at most once per 5min

  - event: time.night
    action: spawn
    params:
      type: emitter
      name: night_fireflies
      config: { sprite_def: firefly, rate: 0.03, max_children: 6 }

  - event: time.day
    action: remove
    params: { name: night_fireflies }
```

---

## 7. Rendering & Compositing

### 7.1 Core Rendering Flow

```
SceneManager.tick()
    → update all sprites (behaviors, animation, lifecycle)
    → process kill list
    → check triggers

SceneManager.render(out_chars, out_colors)
    → sort alive+visible sprites by priority
    → for each sprite in order:
        → sprite.render_to(out_chars, out_colors)
            → if transparent: only overwrite non-space cells
            → if opaque: overwrite entire bounding box (clears behind)
```

### 7.2 Sprite Rendering Methods

Each sprite renders differently based on its type:

- **Cel**: blit pre-parsed frame matrix at (x, y)
- **Reel**: word-wrap text into width, put_text per line
- **Sandbox**: blit simulation output grid (numpy array)
- **Weather**: full-grid particle rendering (Numba JIT path, existing code)
- **Face**: blit pre-computed 11x5 matrix (existing code)
- **Bar**: blit pre-computed 1xN matrix (existing code)
- **Interactive**: render label text + register click region with widget
- **Emitter**: manage child sprite lifecycle (spawn/track/cull)

### 7.3 Exclusion Zones

Opaque sprites register their bounding boxes. The weather sprite queries these to avoid rendering particles behind opaque elements (face, controls, etc.). This is the existing exclusion zone pattern generalized — any opaque sprite contributes to the exclusion set.

### 7.4 Click Regions

`Control` subclasses register click regions with the widget's `ClickRegionManager` when spawned, and deregister when killed. Click events from the widget route to the sprite's `on_click()` handler via the SceneManager.

### 7.5 Integration with Existing DisplayManager

The `DisplayManager` rendering loop stays as-is. It calls into the `SceneManager` instead of manually orchestrating individual archetypes:

```python
# Before (FrameRenderer.render_grid):
self._render_weather()
self._render_celestial()
self._render_avatar()
self._render_bar()
self._render_mic_icon()
self._render_voice_text()
return self.pipeline.to_grid()

# After (SceneManager integration):
self.scene.tick()
self.scene.render(out_chars, out_colors)
# voice_text overlay still handled separately (it's status-locked,
# not a normal sprite — or it becomes a system sprite at priority 95)
return chars_to_rows(out_chars), out_colors.tolist()
```

The existing `RenderPipeline` with its `Layer` objects may be simplified or replaced. The SceneManager handles compositing directly via priority-sorted sprite rendering onto the output arrays. If performance requires it, we can re-introduce layers for heavy sprites (weather JIT) that benefit from separate buffers.

---

## 8. MCP Canvas Tools

New tool sub-server `canvas_tools.py`, following existing patterns (`create_tool_server` from `_helpers.py`).

```python
# --- Sprite Management ---

async def canvas_spawn(
    type: Annotated[str, Field(description="Sprite type: creature, genart, text, lyrics, button, info, ticker, etc.")],
    name: Annotated[str, Field(description="Unique name for this sprite instance")],
    x: Annotated[int, Field(description="Grid column (0-based, 0=left)")],
    y: Annotated[int, Field(description="Grid row (0-based, 0=top)")],
    config: Annotated[str, Field(description="JSON config string for sprite-specific params")] = "{}",
    ctx: Context = None,
) -> str:
    """Spawn a new sprite on the canvas."""

async def canvas_remove(
    name: Annotated[str, Field(description="Sprite name to remove")],
    ctx: Context = None,
) -> str:
    """Remove a sprite from the canvas."""

async def canvas_move(
    name: Annotated[str, Field(description="Sprite name to move")],
    x: Annotated[int, Field(description="New grid column")],
    y: Annotated[int, Field(description="New grid row")],
    ctx: Context = None,
) -> str:
    """Move a sprite to a new position."""

async def canvas_configure(
    name: Annotated[str, Field(description="Sprite name to configure")],
    config: Annotated[str, Field(description="JSON config to apply")] = "{}",
    ctx: Context = None,
) -> str:
    """Update sprite configuration."""

# --- Canvas Queries ---

async def canvas_list(ctx: Context = None) -> str:
    """List all sprites with their type, position, priority, and state."""

async def canvas_snapshot(ctx: Context = None) -> str:
    """Return the current 43x17 grid as readable text.
    The agent can SEE the canvas. It's just text."""

# --- Scene Management ---

async def canvas_load_scene(
    scene: Annotated[str, Field(description="Scene name from elements/scenes/")],
    ctx: Context = None,
) -> str:
    """Load a scene definition, spawning its sprites."""

async def canvas_unload_scene(
    scene: Annotated[str, Field(description="Scene name to unload")],
    ctx: Context = None,
) -> str:
    """Remove all sprites belonging to a scene."""

async def canvas_clear(ctx: Context = None) -> str:
    """Remove all dynamic (non-system) sprites."""

# --- Quick Draw ---

async def canvas_draw(
    name: Annotated[str, Field(description="Name for this text element")],
    x: Annotated[int, Field(description="Grid column")],
    y: Annotated[int, Field(description="Grid row")],
    text: Annotated[str, Field(description="Text content (newlines for multi-line)")],
    color: Annotated[int, Field(description="ANSI-256 color code")] = 0,
    priority: Annotated[int, Field(description="Draw priority (0=back, 100=front)")] = 30,
    ctx: Context = None,
) -> str:
    """Quick-draw text at a position. Creates or updates a Reel sprite."""
```

### Tool Design Notes

- All tools follow Clarvis MCP conventions: `Annotated[type, Field(description=...)]` for every param
- No `from __future__ import annotations` (breaks Pydantic runtime resolution)
- Access daemon via `get_daemon(ctx)` → `daemon.scene_manager`
- Thread safety: SceneManager operations are called from the asyncio event loop via `run_coroutine_threadsafe` if needed, or directly if MCP handler is already async on the event loop

---

## 9. Agent Curation Model

### How the Agent Interacts with the Canvas

1. **Passive observation**: `canvas_snapshot()` returns the grid as text. The agent reads it natively — no vision model needed. It sees `╭─────────╮` and knows the face position. It sees empty space and can decide to fill it.

2. **Active curation**: The agent calls `canvas_spawn()`, `canvas_move()`, `canvas_configure()`, etc. to compose the scene. This happens during normal agent interactions — when the agent is already awake for a voice command or MCP tool call.

3. **Trigger-driven automation**: Context triggers handle the common cases automatically (music starts → show lyrics, night falls → spawn fireflies). The agent doesn't need to be awake for these.

4. **Scene presets**: `canvas_load_scene()` loads predefined compositions. The agent can say "load the music dashboard" or "load the ambient life scene."

5. **Hot-reload**: When YAML definitions change (via `clarvis reload` or file edits), the ElementRegistry notifies sprites, which rebuild their caches. New sprite definitions in `elements/sprites/` are auto-discovered.

### When Does the Agent Curate?

- **On wake (voice/chat)**: Agent can check canvas state and make changes
- **On context triggers**: Automatic, no agent involvement needed
- **On memory maintenance**: Periodic wake-ups could include canvas curation
- **On explicit request**: User says "add some fireflies" or "show me lyrics"

The agent does NOT need to be awake for the canvas to be alive. Triggers, behaviors, and animation handle autonomous visual life. The agent is the curator, not the animator.

---

## 10. Programmable Engine Architecture

### 10.1 The Core Idea: Agent as Programmer

Pre-defined algorithm classes are screensavers. The real power is that the agent **programs** the engine — providing rules, parameters, initial conditions, and character mappings as structured data via `canvas_spawn()` config. The sprite is the runtime; the agent is the programmer.

Each engine type follows the WeatherArchetype pattern internally (numpy arrays, optional Numba JIT), but accepts its program from the agent at spawn time and can be reconfigured via `canvas_configure()`.

### 10.2 Engine Interface

```python
class Sandbox(Sprite):
    """Base for agent-programmable computational sprites."""

    engine: str             # engine type name
    state: np.ndarray       # simulation state (engine-specific shape)
    char_map: dict          # state value → display character

    def configure(self, **config):
        """Agent reprograms the engine. Rebuilds state if rules change."""

    def tick(self, scene):
        """Run one simulation step."""

    def render_to(self, out_chars, out_colors):
        """Map state to characters, blit to output."""
```

### 10.3 Engine Types

**Cellular Automaton** (`engine: automaton`)
- Agent defines: `rules` (birth/survive sets, arbitrary — not just Conway's), `neighborhood` (moore/von_neumann/hex/custom offset list), `states` (number of cell states), `chars` (per-state char), `seed` (random density, named pattern, or explicit grid), `wrap` (bool), `1d` mode (scrolls downward).
- Numba JIT: yes — `_step_ca(grid, birth, survive, neighborhood_offsets)`.

**Particle System** (`engine: particles`)
- Agent defines: `emitters` (list of {x, y, rate, spread, vx, vy}), `forces` (gravity, wind, attractors), `chars` (list), `lifetime` range, `boundary` (wrap/bounce/die).
- Numba JIT: yes — reuses existing weather JIT functions with generalized params.

**L-System** (`engine: lsystem`)
- Agent defines: `axiom`, `rules` (production rules dict), `angle`, `iterations`, `chars` (turtle command → display char). Grows step by step, one iteration per N ticks.
- Numba JIT: no — string rewriting is small, turtle rendering is fast.

**Boids** (`engine: boids`)
- Agent defines: `count`, `separation`/`alignment`/`cohesion` weights, `speed`, `chars` (per-boid or direction-based), `boundary`.
- Numba JIT: yes — force accumulation over N agents.

**Wave** (`engine: waves`)
- Agent defines: `sources` (list of {x, y, frequency, amplitude, phase}), `chars` (height gradient like `" ·∙•●"`), `interference` mode (additive/max).
- Agent can dynamically add/remove wave sources via `canvas_configure()`.

**Reaction-Diffusion** (`engine: reaction_diffusion`)
- Agent defines: `feed_rate`, `kill_rate`, `diffusion_a`, `diffusion_b`, `chars` (concentration gradient).
- Numba JIT: yes — Laplacian convolution per tick.

**Sandpile** (`engine: sandpile`)
- Agent drops grains via configure(). Avalanches cascade by toppling rules. Fractal patterns.

### 10.4 What Makes This Not a Screensaver

The agent can:
1. **Invent rules** — `{"birth": [3,5,7], "survive": [1,4]}` is a CA nobody has named. The agent experiments.
2. **Reconfigure live** — `canvas_configure("myart", rules={"birth": [2,3]})` changes the rules mid-simulation. The state evolves under new physics.
3. **Compose engines** — spawn multiple engine sprites that visually overlap or complement each other.
4. **React to context** — agent changes CA rules based on mood, music genre, time of day.
5. **Direct draw + engine hybrid** — use `canvas_draw()` to paint a frame, then spawn an engine to animate from that starting state.
6. **See the result** — `canvas_snapshot()` shows the output. Agent reads it, decides if it likes it, adjusts.

### 10.5 Interactive Sprite Details

```python
class Control(Sprite):
    """Clickable element. Registers click regions with the widget."""

    label: str
    action: str             # callback identifier

    def on_spawn(self, scene):
        scene.click_manager.register(self.id, self.x, self.y, self.width, self.height)

    def on_death(self, scene):
        scene.click_manager.deregister(self.id)

    def on_click(self, scene):
        # Dispatch action (play_pause, skip, toggle_mic, custom)
```

Compound controls (⏮ ⏯ ⏭) are just multiple Controls spawned together by a scene definition. No special compound class needed — keep it flat.

### 10.6 Image-to-ASCII (Nice-to-Have)

Utility function, not a sprite type. PIL resize → grayscale → brightness-to-charset mapping. Agent calls it to create sprite frames from images (album art, icons).

---

## 11. Migration from Current Architecture

### What Changes

| Current | New |
|---------|-----|
| `FrameRenderer` manually calls 6 render methods | `SceneManager.render()` iterates sprites by priority |
| 5 fixed `Layer` objects with `LayerPriority` constants | Sprites have `priority` property, rendered onto shared output |
| `FaceArchetype`, `ProgressArchetype`, `WeatherArchetype` | `FaceSprite`, `BarSprite`, `WeatherSprite` wrapping same internals |
| Mic icon rendered inline in `_render_mic_icon()` | `ButtonSprite` instance |
| Voice text rendered inline in `_render_voice_text()` | System sprite at priority 95, or kept as special overlay |
| `RenderPipeline` compositing 5 layers | SceneManager renders sprites directly onto output arrays |
| Only click region: mic toggle | Any `Control` registers click regions |

### What Stays

| Component | Status |
|-----------|--------|
| `DisplayManager` (rendering loop, threading, freeze/wake) | Stays, calls SceneManager instead of FrameRenderer |
| `WidgetSocketServer` (frame push, click events) | Stays as-is |
| `ElementRegistry` (YAML loading, change notifications) | Extended with new element kinds (sprites, scenes) |
| `FaceArchetype` internals (pre-computed matrices, animation) | Preserved inside FaceSprite |
| `WeatherArchetype` internals (Numba JIT physics) | Preserved inside WeatherSprite |
| `ProgressArchetype` internals (percentage cache) | Preserved inside BarSprite |
| `ClickRegionManager` | Stays, now used by any Control |
| Swift widget (rendering, click handling, ASR) | No changes needed |
| MCP server architecture | Extended with canvas_tools sub-server |
| StateStore, SignalBus, AppContext | Stay as-is, triggers read from them |

### Migration Strategy

**Phase 0 — Core Infrastructure** (critical foundation):
- `sprites/core.py` — `Sprite` base class, `SpriteRegistry` (live/dead tracking, type queries)
- `sprites/behaviors.py` — `Behavior` base + `StaticBehavior`
- `sprites/scenes.py` — `SceneManager` (tick/render/spawn/remove/kill-list)
- Rendering onto numpy output arrays (priority-sorted compositing)

**Phase 1 — System Wrappers** (prove the architecture, zero visual change):
- `sprites/system.py` — `FaceSprite`, `BarSprite`, `WeatherSprite` wrapping existing archetypes
- `sprites/control.py` — `Control` + mic toggle button
- Wire `SceneManager` into `DisplayManager` (replacing `FrameRenderer`)
- Verify: exact same visual output as before

**Phase 2 — Cel + Reel + MCP** (first new content):
- `sprites/cel.py` — YAML-defined multi-frame ASCII art with animation cycles
- `sprites/reel.py` — text content with modes (STATIC, SCROLL, REVEAL, MARQUEE)
- MCP `canvas_tools.py` — spawn, remove, move, configure, list, snapshot, draw
- Scene YAML loading + default scene definition
- Sample content: ASCII clock (Reel/STATIC + TimeSource), static ASCII art (Cel)

**Phase 3 — Behaviors + Living World**:
- `WanderBehavior`, `DriftBehavior`, `PatrolBehavior`, `LifecycleBehavior`
- Emitter behavior (child sprite spawning at configurable rate)
- YAML creature definitions: cat, bird, firefly, plant (all Cel + behaviors)
- `sprites/sources.py` — `DataSource` protocol + `StateStoreSource`, `TimeSource`
- Trigger system (event → spawn/remove/load_scene actions)

**Phase 4 — Music Integration**:
- `SpotifySource` data adapter (track info, lyrics, beat position)
- Lyrics (Reel/SCROLL + SpotifySource), now-playing ticker (Reel/MARQUEE)
- Playback controls (Control group)
- Now-playing scene definition + triggers (music.playing → load, music.stopped → unload)

**Phase 5 — Programmable Engines**:
- `sprites/sandbox/base.py` — `Sandbox` (state array + step + char_map + configure)
- `sprites/sandbox/registry.py` — engine type lookup
- `sandbox/automaton.py` — cellular automaton (Numba JIT, agent-defined rules)
- `sandbox/particles.py` — particle system (generalized from weather JIT)
- `sandbox/waves.py` — wave interference

**Phase 6 — Reactive + Effects**:
- `sprites/postfx.py` — `PostFx` (post-processing: glitch, debugger overlay)
- Heartbeat (Reel waveform trace + activity source)
- Thought bubbles (emitter + Cel, triggered by status=thinking)
- Error lightning (PostFx, triggered by hook:event errors)
- Growth sprites: vine/cobweb (automaton sandbox + SignalBus event hooks)

**Phase 7 — Engine Expansion + Polish**:
- More engines: L-system, boids, reaction-diffusion, sandpile
- More creatures, scenes, and YAML definitions
- Dream mode (scene orchestration on idle timer)
- Image-to-ASCII utility
- Agent curation patterns (agent decides what to show via canvas tools)

---

## 12. Key Design Decisions

### Priority Values (Conventions, Not Constants)

No more `LayerPriority` enum. Just conventions:

| Range | Purpose | Examples |
|-------|---------|---------|
| 0-9 | Background | Weather (0) |
| 10-19 | Ambient | Creatures, emitters, genart |
| 20-29 | Content | Lyrics, feeds, info panels |
| 30-49 | Mid-ground | Text blocks, ASCII art |
| 50-59 | Focal | Face (50), ticker |
| 60-79 | UI elements | Controls, buttons |
| 80-89 | System UI | Progress bar (80) |
| 90-99 | Overlays | Mic button (92), voice text (95) |

### Opaque vs Transparent

- **Opaque** (`transparent=False`): Face, bar, controls — their bounding box fully overwrites lower content, including spaces. This creates "solid" regions that block weather/background.
- **Transparent** (`transparent=True`, default): Most sprites — only non-space characters overwrite. Background shows through gaps. Creatures, text, buttons, overlays.

### Thread Safety

- `SceneManager` operates under the `DisplayManager`'s `RLock` (same lock that currently protects `FrameRenderer`)
- MCP tool calls to SceneManager methods go through the daemon's event loop
- Trigger evaluation happens in the display thread's tick cycle
- Sprite behaviors are deterministic given current state (no async I/O in tick)

### Performance Considerations

- Pre-compute frame matrices at sprite creation (like FaceArchetype does)
- Weather and GenArt use Numba JIT for heavy computation
- Simple sprites (Reel, Cel, Control) are just `put_text` or `blit` calls — negligible cost
- SpriteRegistry.alive() caches the sorted list, invalidated on spawn/kill
- At 3 FPS with ~20 sprites, performance is not a concern
- The snapshot() MCP tool is O(W*H) — fast for 43x17

---

## 13. Open Questions (To Resolve During Implementation)

1. **RenderPipeline fate**: Do we keep it as an internal optimization (weather renders to a buffer, then composited with sprite output)? Or fully replace with direct sprite-onto-output rendering? Start with direct rendering, add buffers if performance needs it.

2. **Voice text as sprite or special case**: Voice text currently uses status-locked StateStore reads and TTS-synced character reveal. Making it a sprite adds complexity (needs to interact with the status lock system). Consider keeping it as a special overlay initially.

3. **Lyrics API**: Does Spotify's API provide synced lyrics with timestamps? If not, lyrics may need to use an external provider or display unsynced lyrics with manual scroll.

4. **Creature collision**: Should creatures avoid each other? Avoid the face? VGDL has full collision handling, but for ambient creatures, simple boundary bounce may suffice. Weather's exclusion zone pattern could be generalized.

5. **Scene persistence**: Should the current scene state persist across `clarvis restart`? Probably yes for manually curated scenes. Triggers re-evaluate on restart anyway.

6. **Hot-reload granularity**: When a sprite YAML changes, does the sprite rebuild in-place, or does it need to be killed and respawned? In-place rebuild via `_on_element_change` is cleaner.
