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

```
Sprite (base)
├── InteractiveSprite       — Registers click regions, handles on_click
├── WeatherSprite           — Wraps WeatherArchetype (Numba JIT particle physics)
├── FaceSprite              — Wraps FaceArchetype (pre-computed status animation)
└── BarSprite               — Wraps ProgressArchetype (context bar)
```

Most sprite diversity comes from **configuration**, not subclassing. A `Sprite` with `behavior: wander` and creature frames IS a creature. A `Sprite` with `engine: automaton` and agent-defined rules IS generative art. The base `Sprite` + its behavior + its rendering config determines what it is.

### 2.2 System Sprites

Auto-created at startup, survive `clear()`, special internal machinery.

- **WeatherSprite** — Numba JIT particle physics, full-grid, exclusion zones
- **FaceSprite** — pre-computed numpy matrices, status-driven animation
- **BarSprite** — percentage-cached progress bar
- **MicButton** — InteractiveSprite, toggle wake word listening

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

**Sorting Visualizer** (`engine: sorter`)
Agent provides an array. Sprite animates the chosen algorithm step by step (bubble, merge, quick, heap). Bar chart visualization.

### 2.4 Reactive / Data-Driven Sprites

Sprites that breathe with Claude's activity and real-world context:

- **Heartbeat** — EKG trace pulsing with activity rate. Flatlines during idle, spikes during intense tool use, arrhythmia on errors. Configurable chars (`─╲╱─`).
- **Token river** — actual characters from what Claude is processing, flowing like a stream. Speed = thinking intensity. The river IS the content.
- **Thought bubbles** — `○◯` float upward from the face when thinking, containing word fragments. Pop and vanish at the top. Spawn rate = thinking intensity.
- **Error lightning** — test failures / errors crack lightning across the grid. Afterglow traces fade over several frames. Triggered by `hook:event` errors.
- **Code rain** — identifiers and symbols from the *actual file being edited* falling vertically. Not generic Matrix green — real code from the session.
- **Dependency constellation** — files as stars, imports as dim connecting lines. Grows during session. Agent can highlight clusters.
- **Git bonsai** — commit graph as a growing tree. Branches are literal branches. Merges weave. New commits add leaves. Persistent across sessions.
- **Memory web** — knowledge graph entities as floating labeled nodes, edges pulse when recalled. Agent highlights clusters via configure().
- **Word cloud** — words from recent conversations at sizes proportional to frequency. Drifts slowly. Frequent words grow, rare words shrink.
- **Conversation depth** — abstract side-bar showing context depth. Not the progress bar — a core sample showing geological layers of the conversation.

### 2.5 Living World Sprites

The face lives in a world with life, physics, and ecology:

- **Creatures** (YAML-defined) — cat, bird, fish, butterfly, firefly, spider, snake, frog. Multi-frame ASCII art + behavior (wander, patrol, drift, lifecycle). Agent spawns them.
- **Ecosystem** — predator/prey dynamics. Rabbits multiply, foxes chase them, grass grows. Population oscillates. Agent defines species and rules via configure().
- **Vine/ivy** — grows along grid edges frame by frame. Tendrils branch, creep, flower. Gets trimmed when sprites spawn nearby. Regrows over idle time.
- **Campfire** — flickering particle flame with rising sparks and curling smoke. Warmth glow radius.
- **Aquarium** — fish swimming, bubbles rising, seaweed swaying. The face becomes underwater.
- **Ant highway** — ants following pheromone trails between agent-placed food sources. Trail intensity visualized.
- **Bioluminescent deep** — dark grid with glowing creatures pulsing. Jellyfish, anglerfish. Agent defines species.
- **Shadow** — face casts a shadow whose angle tracks sun/moon position. Lengthens at dawn/dusk.
- **Rain puddles** — water pools at bottom during real rain weather. Ripples from new drops. Evaporates when cleared.
- **Snowdrift** — snow accumulates against the face and bottom during snow. Melts when weather changes.
- **Cobwebs** — form in unused corners over idle time. Cleared by activity. Spread if idle for hours.
- **Coral reef** — fractal growth structures. Fish dart between branches. Agent defines growth rules.
- **Wind chimes** — decorative hanging elements, sway amplitude = real wind speed.
- **Moss** — cellular automaton that spreads across empty space. Displaced by other sprites spawning.
- **Tidal pool** — water level oscillates with sine wave. Creatures appear at low tide.

### 2.6 Music-Reactive Sprites

Beyond lyrics — sprites that feel the music:

- **Lyrics** — Spotify-synced, current line highlighted, optional translation, scrolling context.
- **Playback controls** — ⏮ ⏯ ⏭ as clickable InteractiveSprites. Show track progress.
- **Now-playing ticker** — horizontal marquee: "Artist — Track Name".
- **Spectrum analyzer** — frequency bars bouncing. Agent defines bar count, char gradient, color.
- **Piano roll** — horizontal note bars scrolling left, melody structure visible.
- **Vinyl record** — spinning `(( o ))` with track name. RPM synced to BPM.
- **Beat grid** — 16-step drum pattern, highlighting current beat position.
- **Sound ribbon** — continuous waveform flowing across grid.
- **Genre landscape** — abstract terrain shifting with genre (jagged=metal, smooth=jazz, chaotic=experimental).
- **BPM pendulum** — visual metronome ticking at song tempo.

### 2.7 Typography / Text Art Sprites

- **Concrete poetry** — text shaped like its subject. A poem about rain shaped like rain.
- **Kanji study** — large decorative character with readings and meaning. Agent picks.
- **Quote reveal** — text appears character by character, hangs, dissolves. Agent picks quotes.
- **Cipher stream** — encrypted-looking noise slowly decoding to a message. Agent sets message.
- **Graffiti** — stylized ASCII lettering appearing, aging, overwritten.
- **Rosetta stone** — same word in multiple writing systems.
- **ASCII clock** — large decorative clock. Styles: seven-segment, dot-matrix, binary, sundial.
- **Typewriter** — text appearing with mechanical cadence. Carriage return animation.

### 2.8 Interactive / Playful Sprites

- **Buttons** — any clickable element. Label + click region + action callback.
- **Controls cluster** — group of buttons (playback, volume, settings).
- **Tamagotchi mode** — the face IS a pet. Happiness tracks interaction frequency. Gets hungry when ignored. Agent defines mood rules.
- **Maze runner** — procedural maze with a dot solving it. Agent defines parameters.
- **Mini snake** — tiny autonomous snake game. Agent can influence direction.
- **Etch-a-sketch** — agent moves cursor to draw. Persists until "shaken."
- **Fortune cookie** — cracks open with animation, reveals agent-written wisdom.
- **Progress quest** — fake RPG leveling up from real coding activity. Pure comedy.
- **Dice roller** — animated dice roll for decision-making. Agent triggers.

### 2.9 Meta / Self-Referential Sprites

- **Sprite debugger** — semi-transparent overlay showing all bounding boxes, priorities, ages.
- **Canvas replay** — tiny filmstrip of recent canvas states. Session time-lapse.
- **Dream mode** — during long idle, face "sleeps" and "dreams" — surreal sprite compositions cycle.
- **Boot sequence** — retro POST/boot animation on startup before normal scene loads.
- **Glitch** — intentional visual artifacts (shifted rows, corrupted chars, color noise). Aesthetic chaos.
- **Horoscope** — daily zodiac reading for the project. Completely fabricated by agent.

### System vs Dynamic Sprites

- **System sprites** (face, bar, weather, mic): auto-created at startup, survive `clear()`, special internal machinery. `system: bool = True`.
- **Dynamic sprites** (everything else): created by agent, triggers, or scene definitions. Removed by `clear()`.

---

## 3. YAML Sprite Definitions

Extend the existing `ElementRegistry` with new element kinds. Auto-discovered via directory naming.

### 3.1 Creature/Object Definitions

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

### 3.2 Generative Art Definitions

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

### 3.3 Info Widget Definitions

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

## 4. Scene Definitions (VGDL Domain/Level Split)

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

## 5. Trigger System

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

## 6. Rendering & Compositing

### 6.1 Core Rendering Flow

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

### 6.2 Sprite Rendering Methods

Each sprite renders differently based on its type:

- **AsciiArt/Creature**: blit pre-parsed frame matrix at (x, y)
- **TextBlock**: word-wrap text into width, put_text per line
- **GenArt**: blit algorithm output grid (numpy array)
- **Weather**: full-grid particle rendering (Numba JIT path, existing code)
- **Face**: blit pre-computed 11x5 matrix (existing code)
- **Bar**: blit pre-computed 1xN matrix (existing code)
- **Interactive**: render label text + register click region with widget
- **Emitter**: manage child sprite lifecycle (spawn/track/cull)

### 6.3 Exclusion Zones

Opaque sprites register their bounding boxes. The weather sprite queries these to avoid rendering particles behind opaque elements (face, controls, etc.). This is the existing exclusion zone pattern generalized — any opaque sprite contributes to the exclusion set.

### 6.4 Click Regions

`InteractiveSprite` subclasses register click regions with the widget's `ClickRegionManager` when spawned, and deregister when killed. Click events from the widget route to the sprite's `on_click()` handler via the SceneManager.

### 6.5 Integration with Existing DisplayManager

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

## 7. MCP Canvas Tools

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
    """Quick-draw text at a position. Creates or updates a TextBlock sprite."""
```

### Tool Design Notes

- All tools follow Clarvis MCP conventions: `Annotated[type, Field(description=...)]` for every param
- No `from __future__ import annotations` (breaks Pydantic runtime resolution)
- Access daemon via `get_daemon(ctx)` → `daemon.scene_manager`
- Thread safety: SceneManager operations are called from the asyncio event loop via `run_coroutine_threadsafe` if needed, or directly if MCP handler is already async on the event loop

---

## 8. Agent Curation Model

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

## 9. Programmable Engine Architecture

### 9.1 The Core Idea: Agent as Programmer

Pre-defined algorithm classes are screensavers. The real power is that the agent **programs** the engine — providing rules, parameters, initial conditions, and character mappings as structured data via `canvas_spawn()` config. The sprite is the runtime; the agent is the programmer.

Each engine type follows the WeatherArchetype pattern internally (numpy arrays, optional Numba JIT), but accepts its program from the agent at spawn time and can be reconfigured via `canvas_configure()`.

### 9.2 Engine Interface

```python
class EngineSprite(Sprite):
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

### 9.3 Engine Types

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

**Sorting Visualizer** (`engine: sorter`)
- Agent provides: `values` (array), `algorithm` (bubble/merge/quick/heap), `chars` (bar chars). Steps one comparison per tick.

### 9.4 What Makes This Not a Screensaver

The agent can:
1. **Invent rules** — `{"birth": [3,5,7], "survive": [1,4]}` is a CA nobody has named. The agent experiments.
2. **Reconfigure live** — `canvas_configure("myart", rules={"birth": [2,3]})` changes the rules mid-simulation. The state evolves under new physics.
3. **Compose engines** — spawn multiple engine sprites that visually overlap or complement each other.
4. **React to context** — agent changes CA rules based on mood, music genre, time of day.
5. **Direct draw + engine hybrid** — use `canvas_draw()` to paint a frame, then spawn an engine to animate from that starting state.
6. **See the result** — `canvas_snapshot()` shows the output. Agent reads it, decides if it likes it, adjusts.

### 9.5 Interactive Sprite Details

```python
class InteractiveSprite(Sprite):
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

Compound controls (⏮ ⏯ ⏭) are just multiple InteractiveSprites spawned together by a scene definition. No special ControlsSprite needed — keep it flat.

### 9.6 Image-to-ASCII (Nice-to-Have)

Utility function, not a sprite type. PIL resize → grayscale → brightness-to-charset mapping. Agent calls it to create sprite frames from images (album art, icons).

---

## 10. Migration from Current Architecture

### What Changes

| Current | New |
|---------|-----|
| `FrameRenderer` manually calls 6 render methods | `SceneManager.render()` iterates sprites by priority |
| 5 fixed `Layer` objects with `LayerPriority` constants | Sprites have `priority` property, rendered onto shared output |
| `FaceArchetype`, `ProgressArchetype`, `WeatherArchetype` | `FaceSprite`, `BarSprite`, `WeatherSprite` wrapping same internals |
| Mic icon rendered inline in `_render_mic_icon()` | `ButtonSprite` instance |
| Voice text rendered inline in `_render_voice_text()` | System sprite at priority 95, or kept as special overlay |
| `RenderPipeline` compositing 5 layers | SceneManager renders sprites directly onto output arrays |
| Only click region: mic toggle | Any `InteractiveSprite` registers click regions |

### What Stays

| Component | Status |
|-----------|--------|
| `DisplayManager` (rendering loop, threading, freeze/wake) | Stays, calls SceneManager instead of FrameRenderer |
| `WidgetSocketServer` (frame push, click events) | Stays as-is |
| `ElementRegistry` (YAML loading, change notifications) | Extended with new element kinds (sprites, scenes) |
| `FaceArchetype` internals (pre-computed matrices, animation) | Preserved inside FaceSprite |
| `WeatherArchetype` internals (Numba JIT physics) | Preserved inside WeatherSprite |
| `ProgressArchetype` internals (percentage cache) | Preserved inside BarSprite |
| `ClickRegionManager` | Stays, now used by any InteractiveSprite |
| Swift widget (rendering, click handling, ASR) | No changes needed |
| MCP server architecture | Extended with canvas_tools sub-server |
| StateStore, SignalBus, AppContext | Stay as-is, triggers read from them |

### Migration Strategy

**Phase 0 — Infrastructure** (this is the critical foundation):
- Implement `Sprite` base class with full interface
- Implement `Behavior` base + `StaticBehavior`
- Implement `SpriteRegistry` with live/dead tracking
- Implement `SceneManager` with tick/render/spawn/remove
- Implement rendering onto numpy output arrays (bypassing or wrapping `RenderPipeline`)

**Phase 1 — Wrap Existing**:
- `FaceSprite` wrapping `FaceArchetype`
- `BarSprite` wrapping `ProgressArchetype`
- `WeatherSprite` wrapping `WeatherArchetype`
- `ButtonSprite` for mic toggle (replaces `_render_mic_icon()`)
- System sprite for voice text overlay
- Wire `SceneManager` into `DisplayManager` (replacing `FrameRenderer`)
- Verify: exact same visual output as before

**Phase 2 — Static Content**:
- `AsciiArtSprite` — YAML-defined static/animated ASCII art
- `TextBlockSprite` — agent-written text
- `InfoWidgetSprite` — clock, weather summary
- MCP `canvas_tools.py` — spawn, remove, move, list, snapshot, draw
- Scene definition loading from YAML
- Default scene with face + bar + weather + mic

**Phase 3 — Living World**:
- `WanderBehavior`, `DriftBehavior`, `PatrolBehavior`
- `CreatureSprite` with YAML-defined creatures
- `EmitterSprite` (fireflies, sparkles)
- `LifecycleBehavior` (plants, effects)
- Trigger system (auto-spawn based on context events)
- Sample creatures: cat, bird, firefly, plant

**Phase 4 — Music Integration**:
- `LyricsSprite` with Spotify sync
- `ControlsSprite` (playback buttons with click regions)
- `TickerSprite` for now-playing info
- Now-playing scene definition
- Triggers: music.playing → load scene, music.stopped → unload

**Phase 5 — Programmable Engines**:
- `EngineSprite` base with config-driven programming model
- Cellular automaton engine (Numba JIT, agent-defined rules)
- Particle engine (generalized from weather JIT)
- Wave engine
- Agent programs engines via canvas_spawn config — NOT pre-defined algorithms

**Phase 6 — Reactive & Data-Driven**:
- Heartbeat (activity rate), thought bubbles, error lightning
- Code rain (from actual session content)
- Token river, word cloud
- Data-source integration (StateStore, hook events, git)

**Phase 7 — Polish & Expansion**:
- More engines (L-system, boids, reaction-diffusion, sandpile)
- Image-to-ASCII utility
- More creatures and scene definitions
- Agent curation patterns (agent decides what to show)
- Scene rotation (cycle through ambient scenes)
- Feed sprite (git log, notifications)

---

## 11. Key Design Decisions

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
- Simple sprites (TextBlock, AsciiArt, Button) are just `put_text` or `blit` calls — negligible cost
- SpriteRegistry.alive() caches the sorted list, invalidated on spawn/kill
- At 3 FPS with ~20 sprites, performance is not a concern
- The snapshot() MCP tool is O(W*H) — fast for 43x17

---

## 12. Open Questions (To Resolve During Implementation)

1. **RenderPipeline fate**: Do we keep it as an internal optimization (weather renders to a buffer, then composited with sprite output)? Or fully replace with direct sprite-onto-output rendering? Start with direct rendering, add buffers if performance needs it.

2. **Voice text as sprite or special case**: Voice text currently uses status-locked StateStore reads and TTS-synced character reveal. Making it a sprite adds complexity (needs to interact with the status lock system). Consider keeping it as a special overlay initially.

3. **Lyrics API**: Does Spotify's API provide synced lyrics with timestamps? If not, lyrics may need to use an external provider or display unsynced lyrics with manual scroll.

4. **Creature collision**: Should creatures avoid each other? Avoid the face? VGDL has full collision handling, but for ambient creatures, simple boundary bounce may suffice. Weather's exclusion zone pattern could be generalized.

5. **Scene persistence**: Should the current scene state persist across `clarvis restart`? Probably yes for manually curated scenes. Triggers re-evaluate on restart anyway.

6. **Hot-reload granularity**: When a sprite YAML changes, does the sprite rebuild in-place, or does it need to be killed and respawned? In-place rebuild via `_on_element_change` is cleaner.
