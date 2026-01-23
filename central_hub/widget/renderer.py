"""
Widget frame renderer - generates complete ASCII frames for display.

Uses the layered RenderPipeline for compositing:
- Layer 0: Weather particles (transparent)
- Layer 50: Avatar face (overwrites)
- Layer 80: Progress bar (transparent)
"""

import random
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from .pipeline import RenderPipeline, Layer


# =============================================================================
# Color Constants (ANSI 256)
# =============================================================================

COLORS = {
    "gray": 8,
    "white": 15,
    "yellow": 11,
    "green": 10,
    "cyan": 14,
    "blue": 12,
    "magenta": 13,
}

STATUS_COLORS = {
    "idle": COLORS["gray"],
    "resting": COLORS["gray"],
    "thinking": COLORS["yellow"],
    "running": COLORS["green"],
    "executing": COLORS["green"],
    "awaiting": COLORS["blue"],
    "reading": COLORS["cyan"],
    "writing": COLORS["cyan"],
    "reviewing": COLORS["magenta"],
    "offline": COLORS["gray"],
}


# =============================================================================
# Animation Keyframes - Maps status to (eyes, mouth) sequences
# =============================================================================

ANIMATION_KEYFRAMES = {
    "idle": [
        ("dots", "neutral"),
        ("dots", "neutral"),
        ("normal", "neutral"),
        ("dots", "neutral"),
    ],
    "resting": [
        ("sleepy", "flat"),
        ("closed", "flat"),
        ("sleepy", "flat"),
        ("closed", "flat"),
    ],
    "thinking": [
        ("looking_l", "think"),
        ("normal", "think"),
        ("looking_r", "think"),
        ("normal", "think"),
    ],
    "running": [
        ("wide", "smile"),
        ("normal", "smile"),
        ("wide", "open"),
        ("normal", "smile"),
    ],
    "executing": [
        ("wide", "open"),
        ("normal", "open"),
        ("wide", "smile"),
        ("normal", "open"),
    ],
    "awaiting": [
        ("normal", "dots"),
        ("looking_l", "dots"),
        ("normal", "dots"),
        ("looking_r", "dots"),
    ],
    "reading": [
        ("normal", "open"),
        ("looking_l", "open"),
        ("normal", "open"),
        ("looking_r", "open"),
    ],
    "writing": [
        ("normal", "think"),
        ("wide", "think"),
        ("normal", "flat"),
        ("wide", "think"),
    ],
    "reviewing": [
        ("looking_l", "think"),
        ("normal", "think"),
        ("looking_r", "think"),
        ("normal", "think"),
    ],
    "offline": [
        ("closed", "flat"),
        ("closed", "flat"),
    ],
}

DEFAULT_KEYFRAMES = [("normal", "neutral"), ("normal", "neutral")]


# =============================================================================
# Face Parts
# =============================================================================

EYES = {
    "normal": "o",
    "dots": ".",
    "closed": "-",
    "wide": "O",
    "sleepy": "_",
    "looking_l": "o",
    "looking_r": "o",
}

EYE_POSITIONS = {
    "normal": (3, 1, 3),
    "dots": (3, 1, 3),
    "closed": (3, 1, 3),
    "wide": (3, 1, 3),
    "sleepy": (3, 1, 3),
    "looking_l": (2, 1, 4),
    "looking_r": (4, 1, 2),
}

MOUTHS = {
    "neutral": "~",
    "smile": "u",
    "open": "o",
    "flat": "-",
    "dots": ".",
    "think": "~",
}

BORDERS = {
    "idle": "-",
    "resting": "-",
    "thinking": "~",
    "running": "=",
    "executing": "=",
    "awaiting": ".",
    "reading": ".",
    "writing": "-",
    "reviewing": "~",
    "offline": ".",
}

SUBSTRATES = {
    "idle": " .  .  . ",
    "resting": " .  .  . ",
    "thinking": " * . * . ",
    "running": " * o * o ",
    "executing": " > > > > ",
    "awaiting": " . . . . ",
    "reading": " > . . . ",
    "writing": " # # # # ",
    "reviewing": " * . * . ",
    "offline": "   . .   ",
}


# =============================================================================
# Weather Shapes
# =============================================================================

@dataclass
class Shape:
    """Multi-character pattern for weather particles."""
    pattern: tuple[str, ...]  # Immutable for hashability
    width: int
    height: int

    @classmethod
    def parse(cls, text: str) -> "Shape":
        """Parse text into a shape. Each line becomes a row.

        Use \\n to separate rows in multi-line shapes.
        Example: " ~ \\n~~~" renders as:
           ~
          ~~~
        """
        if not text:
            raise ValueError("Shape text cannot be empty")
        pattern = tuple(text.split("\n"))
        height = len(pattern)
        width = max(len(line) for line in pattern)
        return cls(pattern=pattern, width=width, height=height)


# Shape library - define shapes as text, parsed on demand
SHAPE_LIBRARY = {
    # Snow particles (1x1)
    "snow_star": "*",
    "snow_plus": "+",
    "snow_x": "x",
    "snow_dot": ".",
    "snow_o": "o",
    # Rain particles (1x1)
    "rain_drop": "|",
    "rain_bang": "!",
    "rain_colon": ":",
    "rain_tick": "'",
    "rain_comma": ",",
    # Wind particles (1x1)
    "wind_tilde": "~",
    "wind_dash": "-",
    "wind_tick": "'",
    "wind_back": "`",
    "wind_arrow": ">",
    "wind_paren": ")",
    "wind_slash": "/",
    # Fog/cloud single chars
    "fog_dot": ".",
    "fog_tilde": "~",
    "fog_dash": "-",
    # Multi-char clouds
    "cloud_small": " ~ \n~~~",
    "cloud_medium": " ~~~ \n~~~~~\n ~~~ ",
    "cloud_wisp": "~-~",
    "cloud_puff": " ~ \n~~~\n ~ ",
    # Multi-char fog patches
    "fog_patch": ". .\n . ",
    "fog_bank": "...\n. .",
}

@lru_cache(maxsize=None)
def get_shape(name: str) -> Shape:
    """Load shape from library by name, with caching."""
    if name not in SHAPE_LIBRARY:
        raise KeyError(f"Unknown shape: {name}")
    return Shape.parse(SHAPE_LIBRARY[name])


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    shape: Shape
    age: int = 0
    lifetime: int = 100


@dataclass
class BoundingBox:
    """Rectangle exclusion zone."""
    x: int
    y: int
    w: int
    h: int

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


class WeatherSystem:
    """Manages weather particle spawning and physics."""

    # At intensity 1.0, spawn up to this many particles
    MAX_PARTICLES_BASE = 25

    # Ambient cloud settings
    AMBIENT_CLOUD_SHAPES = ["cloud_small", "cloud_wisp", "cloud_puff"]
    AMBIENT_MAX_CLOUDS = 3
    AMBIENT_SPAWN_RATE = 0.03
    AMBIENT_SPAWN_ZONE = 0.35  # Spawn in upper 35% of display

    # Shape names for each weather type (can repeat for weighting)
    SHAPES = {
        "snow": ["snow_star", "snow_plus", "snow_x", "snow_dot", "snow_o"],
        "rain": ["rain_drop", "rain_drop", "rain_colon", "rain_tick", "rain_comma"],
        "cloudy": ["cloud_small", "cloud_wisp", "cloud_puff", "fog_tilde"],
        "fog": ["fog_patch", "fog_bank", "fog_dot", "fog_tilde"],
        "windy": ["wind_tilde", "wind_dash", "wind_tick", "wind_arrow", "wind_slash"],
    }

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.particles: list[Particle] = []
        self.ambient_clouds: list[Particle] = []
        self.weather_type: Optional[str] = None
        self.intensity = 0.0
        self.exclusion_zones: list[BoundingBox] = []

    def set_exclusion_zones(self, zones: list[BoundingBox]):
        """Set bounding boxes where particles should not render."""
        self.exclusion_zones = zones

    def set_weather(self, weather_type: str, intensity: float = 0.6):
        if weather_type != self.weather_type:
            self.weather_type = weather_type
            self.particles.clear()
        self.intensity = intensity

    def _is_alive(self, p: Particle) -> bool:
        """Check if particle is still on screen (any part visible)."""
        if p.age >= p.lifetime:
            return False
        # Check if any part of shape could be visible
        return (p.y + p.shape.height > -1 and
                p.y < self.height + 1 and
                p.x + p.shape.width > -1 and
                p.x < self.width + 1)

    def _is_cloud_visible(self, p: Particle) -> bool:
        """Check if cloud is still on screen (persists until out of frame)."""
        return (p.x < self.width + 1 and
                p.x + p.shape.width > -1 and
                p.y < self.height + 1 and
                p.y + p.shape.height > -1)

    def _tick_ambient_clouds(self):
        """Update and spawn ambient background clouds."""
        # Update existing ambient clouds - persist until out of frame
        alive = []
        for p in self.ambient_clouds:
            p.x += p.vx
            p.y += p.vy
            if self._is_cloud_visible(p):
                alive.append(p)
        self.ambient_clouds = alive

        # Spawn new ambient clouds (unless we have active cloudy/fog weather)
        if self.weather_type in ("cloudy", "fog"):
            return  # Let main weather handle clouds

        if (len(self.ambient_clouds) < self.AMBIENT_MAX_CLOUDS and
                random.random() < self.AMBIENT_SPAWN_RATE):
            shape_name = random.choice(self.AMBIENT_CLOUD_SHAPES)
            shape = get_shape(shape_name)
            max_y = int(self.height * self.AMBIENT_SPAWN_ZONE)
            p = Particle(
                x=random.uniform(-shape.width * 2, -shape.width),  # Start off-screen left
                y=random.uniform(0, max_y),  # Upper portion only
                vx=random.uniform(0.08, 0.15),  # Faster rightward drift
                vy=random.uniform(-0.02, 0.02),  # Some vertical drift
                shape=shape,
                lifetime=999999,  # Effectively infinite - removed by position check
            )
            self.ambient_clouds.append(p)

    def tick(self):
        # Always tick ambient clouds
        self._tick_ambient_clouds()

        if not self.weather_type or self.weather_type not in self.SHAPES:
            return

        # Update existing particles
        alive = []
        for p in self.particles:
            p.x += p.vx
            p.y += p.vy
            p.age += 1
            if self._is_alive(p):
                alive.append(p)
        self.particles = alive

        # Spawn new particles
        max_particles = int(self.intensity * self.MAX_PARTICLES_BASE)
        spawn_rate = self.intensity * 0.5

        if len(self.particles) < max_particles and random.random() < spawn_rate:
            shape_names = self.SHAPES[self.weather_type]
            shape_name = random.choice(shape_names)
            shape = get_shape(shape_name)

            if self.weather_type == "snow":
                p = Particle(
                    x=random.uniform(0, self.width),
                    y=random.uniform(-shape.height, 0),
                    vx=random.uniform(-0.1, 0.1),
                    vy=random.uniform(0.15, 0.35),
                    shape=shape,
                    lifetime=random.randint(40, 100),
                )
            elif self.weather_type == "rain":
                p = Particle(
                    x=random.uniform(0, self.width),
                    y=random.uniform(-shape.height, 0),
                    vx=random.uniform(-0.03, 0.03),
                    vy=random.uniform(0.5, 0.9),
                    shape=shape,
                    lifetime=random.randint(20, 50),
                )
            elif self.weather_type == "windy":
                p = Particle(
                    x=random.uniform(-shape.width, 0),
                    y=random.uniform(0, self.height),
                    vx=random.uniform(0.4, 0.8),
                    vy=random.uniform(-0.1, 0.1),
                    shape=shape,
                    lifetime=random.randint(30, 60),
                )
            else:  # cloudy, fog
                p = Particle(
                    x=random.uniform(0, self.width),
                    y=random.uniform(0, self.height),
                    vx=random.uniform(-0.05, 0.05),
                    vy=random.uniform(-0.03, 0.03),
                    shape=shape,
                    lifetime=random.randint(60, 150),
                )
            self.particles.append(p)

    def _render_particle(self, layer: Layer, p: Particle, color: int):
        """Render a single particle to a layer."""
        px, py = int(p.x), int(p.y)
        for row_idx, row in enumerate(p.shape.pattern):
            for col_idx, char in enumerate(row):
                if char == " ":
                    continue  # transparent
                cx, cy = px + col_idx, py + row_idx
                if any(zone.contains(cx, cy) for zone in self.exclusion_zones):
                    continue
                layer.put(cx, cy, char, color)

    def render(self, layer: Layer, color: int = 8):
        """Render particles to a layer, respecting exclusion zones."""
        # Render ambient clouds first (behind weather particles)
        for p in self.ambient_clouds:
            self._render_particle(layer, p, color)
        # Render weather particles
        for p in self.particles:
            self._render_particle(layer, p, color)


# =============================================================================
# Frame Renderer (uses RenderPipeline)
# =============================================================================

class FrameRenderer:
    """Renders complete widget frames using layered pipeline."""

    # Base dimensions (reference grid)
    BASE_WIDTH = 18
    BASE_HEIGHT = 10

    # Avatar fixed dimensions
    AVATAR_WIDTH = 11
    AVATAR_HEIGHT = 5

    # Layout ratios (relative to base grid)
    MARGIN_RATIO = 0.15        # 15% margin on each side
    BAR_WIDTH_RATIO = 0.65     # Bar is 65% of grid width
    CONTENT_HEIGHT_RATIO = 0.7 # Content uses 70% of height
    BAR_GAP_RATIO = 0.1        # Gap between avatar and bar

    def __init__(self, width: int = 18, height: int = 10):
        self.width = width
        self.height = height

        # Pipeline with layers
        self.pipeline = RenderPipeline(width, height)
        self.weather_layer = self.pipeline.add_layer("weather", priority=0)
        self.avatar_layer = self.pipeline.add_layer("avatar", priority=50)
        self.bar_layer = self.pipeline.add_layer("bar", priority=80)

        # Auto-calculate layout
        self._recalculate_layout()

    def _recalculate_layout(self):
        """Calculate element positions using proportional math."""
        w, h = self.width, self.height

        # Scale factor relative to base
        scale_x = w / self.BASE_WIDTH
        scale_y = h / self.BASE_HEIGHT

        # Margins (proportional to grid size)
        margin_x = int(w * self.MARGIN_RATIO)
        margin_y = int(h * self.MARGIN_RATIO)

        # Content area
        content_w = w - 2 * margin_x
        content_h = h - 2 * margin_y

        # Avatar stays fixed size, centered in content area
        self.avatar_x = margin_x + (content_w - self.AVATAR_WIDTH) // 2

        # Vertical layout: avatar + gap + bar within content area
        bar_gap = max(1, int(h * self.BAR_GAP_RATIO))
        total_content_h = self.AVATAR_HEIGHT + bar_gap + 1  # 1 for bar height

        # Center content block vertically
        content_start_y = margin_y + (content_h - total_content_h) // 2

        self.avatar_y = content_start_y
        self.bar_y = content_start_y + self.AVATAR_HEIGHT + bar_gap

        # Bar width scales with grid (clamped to reasonable bounds)
        self.bar_width = max(self.AVATAR_WIDTH, min(int(w * self.BAR_WIDTH_RATIO), w - 2 * margin_x))
        self.bar_x = margin_x + (content_w - self.bar_width) // 2

        # Weather system
        self.weather = WeatherSystem(self.width, self.height)

        # Animation state
        self.keyframe_index = 0
        self.current_status = "idle"
        self.current_keyframes = ANIMATION_KEYFRAMES.get("idle", DEFAULT_KEYFRAMES)
        self.current_color = STATUS_COLORS.get("idle", COLORS["gray"])

    def set_status(self, status: str):
        if status != self.current_status:
            self.current_status = status
            self.current_keyframes = ANIMATION_KEYFRAMES.get(status, DEFAULT_KEYFRAMES)
            self.current_color = STATUS_COLORS.get(status, COLORS["gray"])
            self.keyframe_index = 0

    def set_weather(self, weather_type: str, intensity: float = 0.6):
        self.weather.set_weather(weather_type, intensity)

    def tick(self):
        """Advance animation state."""
        if self.current_keyframes:
            self.keyframe_index = (self.keyframe_index + 1) % len(self.current_keyframes)
        self.weather.tick()

    def _render_weather(self):
        """Render weather layer."""
        self.weather_layer.clear()
        # Set exclusion zone for avatar bounding box
        avatar_box = BoundingBox(
            x=self.avatar_x,
            y=self.avatar_y,
            w=self.AVATAR_WIDTH,
            h=self.AVATAR_HEIGHT
        )
        self.weather.set_exclusion_zones([avatar_box])
        self.weather.render(self.weather_layer, color=COLORS["white"])

    def _render_avatar(self):
        """Render avatar layer."""
        self.avatar_layer.clear()

        eyes, mouth = self.current_keyframes[self.keyframe_index]
        eye_char = EYES.get(eyes, "o")
        l, g, r = EYE_POSITIONS.get(eyes, (3, 1, 3))
        mouth_char = MOUTHS.get(mouth, "~")
        border = BORDERS.get(self.current_status, "-")
        substrate = SUBSTRATES.get(self.current_status, " .  .  . ")

        x, y = self.avatar_x, self.avatar_y
        color = self.current_color

        # Build face lines
        lines = [
            f"+{border * 9}+",
            f"|{' ' * l}{eye_char}{' ' * g}{eye_char}{' ' * r}|",
            f"|    {mouth_char}    |",
            f"|{substrate}|",
            f"+{border * 9}+",
        ]

        for dy, line in enumerate(lines):
            self.avatar_layer.put_text(x, y + dy, line, color)

    def _render_bar(self, context_percent: float):
        """Render progress bar layer."""
        self.bar_layer.clear()

        filled = int(context_percent / 100 * self.bar_width)
        for i in range(self.bar_width):
            if i < filled:
                self.bar_layer.put(self.bar_x + i, self.bar_y, '#', self.current_color)
            else:
                self.bar_layer.put(self.bar_x + i, self.bar_y, '-', COLORS["gray"])

    def render(self, context_percent: float = 0) -> str:
        """Render complete frame."""
        self._render_weather()
        self._render_avatar()
        self._render_bar(context_percent)
        return self.pipeline.to_string()

    def render_colored(self, context_percent: float = 0) -> str:
        """Render complete frame with ANSI colors."""
        self._render_weather()
        self._render_avatar()
        self._render_bar(context_percent)
        return self.pipeline.to_ansi()


# =============================================================================
# Test
# =============================================================================

if __name__ == "__main__":
    import time
    import sys

    renderer = FrameRenderer(width=18, height=10)
    renderer.set_status("running")
    renderer.set_weather("snow", 1.0)

    print("\033[2J\033[H")
    print("Pipeline Renderer Demo (Ctrl+C to stop)\n")

    try:
        ctx = 0
        for _ in range(100):
            renderer.tick()
            frame = renderer.render(context_percent=ctx)

            print("\033[3;0H")
            print(frame)
            print(f"\nStatus: {renderer.current_status}  Context: {ctx:.0f}%")

            ctx = (ctx + 1) % 100
            time.sleep(0.15)
    except KeyboardInterrupt:
        pass

    print("\nDone!")
