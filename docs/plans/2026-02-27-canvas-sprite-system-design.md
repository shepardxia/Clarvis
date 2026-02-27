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

## 2. Sprite Type Hierarchy

```
Sprite (base)
│
├── AsciiArtSprite          — Multi-line ASCII art from YAML or agent-provided
│                              Supports multiple named frames for animation
│
├── TextBlockSprite         — Agent-written text, auto-wraps to width
│                              source: "static" (agent sets text) or "data" (auto-updates)
│
├── InfoWidgetSprite        — Auto-updating data display
│                              Sources: clock, weather, git_status, system_stats
│                              Polls StateStore or runs shell commands periodically
│
├── GenArtSprite            — Algorithmic generation (Numba JIT where beneficial)
│                              Algorithms: game_of_life, rule_110, langton_ant,
│                              diamond_square, lissajous, matrix_rain, mandelbrot_zoom
│
├── LyricsSprite            — Spotify-synced lyrics with optional translation
│                              Syncs with track position, highlights current line
│                              ScrollBehavior for smooth transitions
│
├── TickerSprite            — Horizontal scrolling marquee text
│                              For now-playing info, notifications, RSS
│
├── FeedSprite              — Vertical scrolling feed
│                              For git log, notifications, chat history
│
├── InteractiveSprite       — Clickable element (registers click region with widget)
│   ├── ButtonSprite        — Single clickable button with label
│   └── ControlsSprite      — Playback control cluster (⏮ ⏯ ⏭)
│
├── CreatureSprite          — Living ASCII creature with behavior
│                              Appearance: YAML-defined multi-frame ASCII art
│                              Behavior: wander, patrol, drift, lifecycle
│                              Examples: cat, bird, fish, butterfly, firefly
│
├── EmitterSprite           — Particle spawner (mini weather effects)
│                              Spawns short-lived child sprites (sparkles, notes, drops)
│
├── WeatherSprite           — Wraps existing WeatherArchetype
│                              Full-grid coverage, Numba JIT particle physics
│                              Exclusion zones from other opaque sprites
│
├── FaceSprite              — Wraps existing FaceArchetype
│                              Status-driven animation, pre-computed frame matrices
│                              Default position: right-center, but repositionable
│
└── BarSprite               — Wraps existing ProgressArchetype
                               Context window progress bar
                               Default position: below face, but repositionable
```

### System vs Dynamic Sprites

- **System sprites** (face, bar, weather): auto-created at startup, survive `clear()`, have special internal machinery (Numba JIT, pre-computed matrices, status-driven state). Marked with `system: bool = True`.
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

## 9. Specialized Sprite Details

### 9.1 GenArtSprite (Numba JIT)

Follows the WeatherArchetype pattern: numpy arrays for state, `@njit(cache=True)` for computation, Python bridge for rendering.

```python
class GenArtSprite(Sprite):
    """Algorithmic generative art. Numba JIT where beneficial."""

    algorithm: str          # "game_of_life", "rule_110", "langton_ant", etc.
    grid: np.ndarray        # 2D uint8 array (algorithm state)
    chars: np.ndarray       # 2D uint32 array (rendered characters)

    # Algorithm-specific config (dumped onto self via kwargs)
    density: float = 0.3
    alive_char: str = "#"
    dead_char: str = " "
    wrap: bool = True
```

**Algorithms to implement (start with 2-3, add more over time):**

| Algorithm | JIT? | Description |
|-----------|------|-------------|
| `game_of_life` | Yes | Conway's Game of Life — classic emergent patterns |
| `rule_110` | Yes | 1D cellular automaton scrolling downward |
| `langton_ant` | Yes | Turing-complete ant on a grid |
| `matrix_rain` | No | Falling green characters (column-based, simple Python) |
| `mandelbrot_zoom` | Yes | Slow zoom into Mandelbrot set, mapped to ASCII density |
| `lissajous` | No | Lissajous curve drawing, parameters slowly drift |
| `diamond_square` | No | Terrain heightmap → ASCII elevation characters |

### 9.2 LyricsSprite

Syncs with Spotify's current playback position.

```python
class LyricsSprite(Sprite):
    """Spotify-synced lyrics display."""

    lyrics_lines: list[LyricLine]   # (timestamp_ms, text, translation?)
    current_index: int
    show_translation: bool
    highlight_current: bool
    max_lines: int

    def tick(self, scene):
        # Query current Spotify position (via daemon's SpotifySession)
        # Advance current_index to match
        # ScrollBehavior handles smooth transitions

    def render(self, layer):
        # Show current line highlighted + surrounding context lines
        # Translation below current line if enabled
```

**Lyrics data source**: The clautify `SpotifySession` can fetch lyrics via Spotify's API. The LyricsSprite queries the session for current track lyrics on track change, then syncs display to playback position. Cache lyrics per track to avoid repeated API calls.

### 9.3 InteractiveSprite (Buttons & Controls)

```python
class InteractiveSprite(Sprite):
    """Clickable element. Registers click regions with the widget."""

    label: str              # display text
    action: str             # action identifier ("play_pause", "skip", "toggle_mic")

    def on_spawn(self, scene):
        # Register click region with ClickRegionManager
        scene.click_manager.register(self.id, self.x, self.y, self.width, self.height)

    def on_death(self, scene):
        # Deregister click region
        scene.click_manager.deregister(self.id)

    def on_click(self, scene):
        # Execute action (via daemon reference)
        # e.g., "play_pause" → daemon.spotify_session.run("play") or .run("pause")
```

**ControlsSprite**: A compound sprite that creates multiple ButtonSprites for playback controls:
```
 ⏮  ⏯  ⏭
```
Each button is its own click region.

### 9.4 CreatureSprite

Generic YAML-defined creature with behavior.

```python
class CreatureSprite(Sprite):
    """Living ASCII creature. Appearance from YAML, behavior from type."""

    sprite_def: str         # references elements/sprites/{name}.yaml
    frames: dict[str, np.ndarray]  # pre-parsed frame matrices
    current_frame: str
    animation_state: str    # "idle", "moving"
    frame_index: int

    def tick(self, scene):
        super().tick(scene)  # behavior updates position
        # Determine animation state based on movement
        # Advance frame_index

    def render(self, layer):
        # Blit current frame matrix at (x, y)
```

### 9.5 EmitterSprite (VGDL SpawnPoint Analog)

Periodically spawns child sprites within an area.

```python
class EmitterSprite(Sprite):
    """Particle spawner. VGDL SpawnPoint pattern."""

    sprite_def: str         # child sprite type (e.g., "firefly")
    rate: float             # spawn probability per tick
    max_children: int       # maximum alive children
    area: tuple[int, int]   # spawn area (w, h) from emitter origin
    children: list[str]     # IDs of spawned children (tracked for lifecycle)

    def tick(self, scene):
        # Cull dead children from tracking list
        # If len(children) < max_children and random() < rate:
        #     spawn child at random position within area
```

### 9.6 Image-to-ASCII (Nice-to-Have, Future)

A utility function, not a sprite type. Converts images to ASCII art that can be used as sprite frames.

```python
def image_to_ascii(image_path: str, width: int, height: int,
                   charset: str = " .:-=+*#%@") -> str:
    """Convert image to ASCII art string."""
    # PIL resize → grayscale → map pixel brightness to charset
    # Return multi-line string suitable for AsciiArtSprite frames
```

Could be used by the agent: "fetch album art, convert to ASCII, spawn as sprite." Or by the LyricsSprite to show album art alongside lyrics.

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

**Phase 5 — Generative Art**:
- `GenArtSprite` base with algorithm dispatch
- Game of Life (Numba JIT)
- Matrix rain
- Rule 110
- More algorithms as desired

**Phase 6 — Polish & Extras**:
- `FeedSprite` (git log, notifications)
- Image-to-ASCII utility
- More creatures and scene definitions
- Agent curation patterns (agent decides what to show)
- Scene rotation (cycle through ambient scenes)

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
