"""
Widget frame renderer - orchestrates archetypes to generate complete ASCII frames.

Uses the layered RenderPipeline for compositing:
- Layer 0: Weather particles (transparent)
- Layer 50: Avatar face (overwrites)
- Layer 80: Progress bar (transparent)
- Layer 90: Whimsy verb (transparent)
"""

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

    def _recalculate_layout(self):
        """Calculate element positions using proportional math."""
        w, h = self.width, self.height

        margin_x = int(w * self.MARGIN_RATIO)
        margin_y = int(h * self.MARGIN_RATIO)

        content_w = w - 2 * margin_x
        content_h = h - 2 * margin_y

        avatar_x_centered = margin_x + (content_w - self.AVATAR_WIDTH) // 2

        bar_gap = max(1, int(h * self.BAR_GAP_RATIO))
        total_content_h = self.AVATAR_HEIGHT + bar_gap + 1

        content_start_y = margin_y + (content_h - total_content_h) // 2

        avatar_y_centered = content_start_y
        bar_y_centered = content_start_y + self.AVATAR_HEIGHT + bar_gap

        self.bar_width = max(self.AVATAR_WIDTH, min(int(w * self.BAR_WIDTH_RATIO), w - 2 * margin_x))
        bar_x_centered = margin_x + (content_w - self.bar_width) // 2

        self.avatar_x = avatar_x_centered + self.avatar_x_offset
        self.avatar_y = avatar_y_centered + self.avatar_y_offset
        self.bar_x = bar_x_centered + self.bar_x_offset
        self.bar_y = bar_y_centered + self.bar_y_offset

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

    def render(self, context_percent: float = 0, whimsy_verb: Optional[str] = None) -> str:
        """Render complete frame (plain text)."""
        self._render_weather()
        self._render_avatar()
        self._render_bar(context_percent)
        self._render_verb(whimsy_verb)
        return self.pipeline.to_string()

    def render_colored(self, context_percent: float = 0, whimsy_verb: Optional[str] = None) -> str:
        """Render complete frame with ANSI colors."""
        self._render_weather()
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
