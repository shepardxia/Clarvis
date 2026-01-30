"""
Widget frame renderer - orchestrates archetypes to generate complete ASCII frames.

Uses the layered RenderPipeline for compositing:
- Layer 0: Weather particles (transparent)
- Layer 50: Avatar face (overwrites)
- Layer 80: Progress bar (transparent)
- Layer 90: Whimsy verb (transparent)
"""

from datetime import datetime
from typing import Optional

from .pipeline import RenderPipeline
from ..elements.registry import ElementRegistry
from ..archetypes import FaceArchetype, WeatherArchetype, ProgressArchetype
from ..archetypes.weather import BoundingBox
from ..core.colors import ANSI_COLORS as COLORS, get_status_ansi


class FrameRenderer:
    """Renders complete widget frames using layered pipeline and archetypes."""

    # Base dimensions (reference grid)
    BASE_WIDTH = 18
    BASE_HEIGHT = 10

    # Avatar fixed dimensions
    AVATAR_WIDTH = 11
    AVATAR_HEIGHT = 5

    # Layout ratios
    MARGIN_RATIO = 0.15
    BAR_WIDTH_RATIO = 0.65
    BAR_GAP_RATIO = 0.1

    # Celestial bodies (sun: 6am-8pm, moon: 8pm-6am)
    SUN_ART = ["\\|/", "-o-", "/|\\"]
    MOON_ART = [" _ ", "(') ", " ~ "]
    CELESTIAL_WIDTH = 3
    CELESTIAL_HEIGHT = 3

    def __init__(self, width: int = 18, height: int = 10,
                 avatar_x_offset: int = 0, avatar_y_offset: int = 0,
                 bar_x_offset: int = 0, bar_y_offset: int = 0):
        self.width = width
        self.height = height

        # Store offsets
        self.avatar_x_offset = avatar_x_offset
        self.avatar_y_offset = avatar_y_offset
        self.bar_x_offset = bar_x_offset
        self.bar_y_offset = bar_y_offset

        # Element registry with hot-reload
        self.registry = ElementRegistry()
        self.registry.load_all()
        self.registry.start_watching()

        # Pipeline with layers
        self.pipeline = RenderPipeline(width, height)
        self.weather_layer = self.pipeline.add_layer("weather", priority=0)
        self.avatar_layer = self.pipeline.add_layer("avatar", priority=50)
        self.bar_layer = self.pipeline.add_layer("bar", priority=80)
        self.verb_layer = self.pipeline.add_layer("verb", priority=90)

        # Calculate layout
        self._recalculate_layout()

        # Initialize archetypes
        self.face = FaceArchetype(self.registry)
        self.weather = WeatherArchetype(self.registry, self.width, self.height)
        self.progress = ProgressArchetype(self.registry, self.bar_width)

        # Animation state
        self.current_status = "idle"
        self.current_color = get_status_ansi().get("idle", COLORS["gray"])
        
        # Pre-warm all caches for instant runtime performance
        self.prewarm_caches()

    def prewarm_caches(self) -> dict:
        """Pre-warm all archetype caches for instant runtime performance.
        
        Call at startup to avoid computation during rendering.
        Returns combined stats from all archetypes.
        """
        stats = {
            'face': self.face.prewarm_cache(),
            'progress': self.progress.prewarm_cache(),
            'weather': self.weather.prewarm_shapes(),
        }
        return stats

    def cache_stats(self) -> dict:
        """Return combined cache statistics from all archetypes."""
        return {
            'face': self.face.cache_stats(),
            'progress': self.progress.cache_stats(),
            'weather': self.weather.cache_stats(),
        }

    def _recalculate_layout(self):
        """Calculate element positions - simple centering."""
        w, h = self.width, self.height

        # Content dimensions
        bar_gap = 1
        total_content_h = self.AVATAR_HEIGHT + bar_gap + 1  # avatar + gap + bar

        # Center vertically in full grid
        content_start_y = (h - total_content_h) // 2

        # Center horizontally
        avatar_x_centered = (w - self.AVATAR_WIDTH) // 2

        # Bar width and centering
        self.bar_width = max(self.AVATAR_WIDTH, min(int(w * self.BAR_WIDTH_RATIO), w - 4))
        bar_x_centered = (w - self.bar_width) // 2

        # Final positions with offsets
        self.avatar_x = avatar_x_centered + self.avatar_x_offset
        self.avatar_y = content_start_y + self.avatar_y_offset
        self.bar_x = bar_x_centered + self.bar_x_offset
        self.bar_y = content_start_y + self.AVATAR_HEIGHT + bar_gap + self.bar_y_offset

    def set_status(self, status: str):
        """Set current status."""
        if status != self.current_status:
            self.current_status = status
            self.current_color = get_status_ansi().get(status, COLORS["gray"])
            self.face.set_status(status)

    def set_weather(self, weather_type: str, intensity: float = 0.6, wind_speed: float = 0.0):
        """Set weather type and intensity."""
        self.weather.set_weather(weather_type, intensity, wind_speed)

    def tick(self):
        """Advance animation state."""
        self.face.tick()
        self.weather.tick()

    def _render_weather(self):
        """Render weather layer."""
        self.weather_layer.clear()
        avatar_box = BoundingBox(
            x=self.avatar_x,
            y=self.avatar_y,
            w=self.AVATAR_WIDTH,
            h=self.AVATAR_HEIGHT
        )
        self.weather.set_exclusion_zones([avatar_box])
        self.weather.render(self.weather_layer, color=COLORS["white"])

    def _render_celestial(self, hour: Optional[int] = None):
        """Render sun or moon based on time of day, arcing across the top."""
        # Only render if there's room above avatar
        if self.avatar_y < self.CELESTIAL_HEIGHT + 1:
            return

        if hour is None:
            hour = datetime.now().hour

        # Determine which celestial body and calculate position
        # Sun: 6am-8pm (hours 6-20), Moon: 8pm-6am (hours 20-24, 0-6)
        margin = 1
        available_width = self.width - 2 * margin - self.CELESTIAL_WIDTH

        if 6 <= hour < 20:
            # Daytime: sun arcs from left to right
            art = self.SUN_ART
            progress = (hour - 6) / 14  # 14 hours of daylight
            color = COLORS["yellow"]
        else:
            # Nighttime: moon arcs from left to right
            art = self.MOON_ART
            # Normalize: 20->0, 21->1, ..., 24->4, 0->4, 1->5, ..., 6->10
            if hour >= 20:
                night_hour = hour - 20
            else:
                night_hour = hour + 4
            progress = night_hour / 10  # 10 hours of night
            color = COLORS["white"]

        x = margin + int(progress * available_width)
        y = 0  # Top of screen

        # Render art lines
        for i, line in enumerate(art):
            if y + i < self.height:
                self.weather_layer.put_text(x, y + i, line, color)

    def _render_avatar(self):
        """Render avatar layer."""
        self.avatar_layer.clear()
        self.face.render(self.avatar_layer, x=self.avatar_x, y=self.avatar_y, color=0)

    def _render_bar(self, context_percent: float):
        """Render progress bar layer."""
        self.bar_layer.clear()
        self.progress.render(
            self.bar_layer,
            x=self.bar_x,
            y=self.bar_y,
            percent=context_percent,
            color=COLORS["gray"]
        )

    def _render_verb(self, verb: Optional[str]):
        """Render whimsy verb below the progress bar."""
        self.verb_layer.clear()
        if not verb:
            return

        display_verb = f"{verb.lower()}..."
        verb_y = self.bar_y + 2
        verb_x = self.bar_x + (self.bar_width - len(display_verb)) // 2
        verb_x = max(0, verb_x)

        self.verb_layer.put_text(verb_x, verb_y, display_verb, 249)

    def render(self, context_percent: float = 0, whimsy_verb: Optional[str] = None, hour: Optional[int] = None) -> str:
        """Render complete frame (plain text)."""
        self._render_weather()
        self._render_celestial(hour)
        self._render_avatar()
        self._render_bar(context_percent)
        self._render_verb(whimsy_verb)
        return self.pipeline.to_string()

    def render_colored(self, context_percent: float = 0, whimsy_verb: Optional[str] = None, hour: Optional[int] = None) -> str:
        """Render complete frame with ANSI colors."""
        self._render_weather()
        self._render_celestial(hour)
        self._render_avatar()
        self._render_bar(context_percent)
        self._render_verb(whimsy_verb)
        return self.pipeline.to_ansi()


# =============================================================================
# Test
# =============================================================================

if __name__ == "__main__":
    import time

    renderer = FrameRenderer(width=18, height=10)
    renderer.set_status("running")
    renderer.set_weather("clear", 0.0)

    print("\033[2J\033[H")
    print("Pipeline Renderer Demo (Ctrl+C to stop)\n")

    try:
        ctx = 0
        hour = 6  # Start at sunrise
        for _ in range(100):
            renderer.tick()
            frame = renderer.render(context_percent=ctx, hour=hour)

            print("\033[3;0H")
            print(frame)
            body = "sun" if 6 <= hour < 20 else "moon"
            print(f"\nStatus: {renderer.current_status}  Hour: {hour:02d}:00  ({body})")

            ctx = (ctx + 1) % 100
            hour = (hour + 1) % 24
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass

    print("\nDone!")
