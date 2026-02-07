"""
Widget frame renderer - orchestrates archetypes to generate complete ASCII frames.

Uses the layered RenderPipeline for compositing:
- Layer 0: Weather particles (transparent)
- Layer 50: Avatar face (overwrites)
- Layer 80: Progress bar (transparent)
- Layer 90: Whimsy verb (transparent)
- Layer 92: Mic icon (transparent)
- Layer 95: Voice text overlay (transparent)
"""

from datetime import datetime
from typing import Optional

from ..archetypes import FaceArchetype, ProgressArchetype, WeatherArchetype
from ..archetypes.weather import BoundingBox
from ..core.colors import StatusColors
from ..elements.registry import ElementRegistry
from .pipeline import RenderPipeline


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

    def __init__(
        self,
        width: int = 18,
        height: int = 10,
        avatar_x_offset: int = 0,
        avatar_y_offset: int = 0,
        bar_x_offset: int = 0,
        bar_y_offset: int = 0,
    ):
        self.width = width
        self.height = height

        # Store offsets
        self.avatar_x_offset = avatar_x_offset
        self.avatar_y_offset = avatar_y_offset
        self.bar_x_offset = bar_x_offset
        self.bar_y_offset = bar_y_offset

        # Element registry
        self.registry = ElementRegistry()
        self.registry.load_all()

        # Pipeline with layers
        self.pipeline = RenderPipeline(width, height)
        self.weather_layer = self.pipeline.add_layer("weather", priority=0)
        self.avatar_layer = self.pipeline.add_layer("avatar", priority=50)
        self.bar_layer = self.pipeline.add_layer("bar", priority=80)
        self.verb_layer = self.pipeline.add_layer("verb", priority=90)
        self.mic_layer = self.pipeline.add_layer("mic_icon", priority=92, transparent=True)
        self.text_layer = self.pipeline.add_layer("voice_text", priority=95, transparent=True)

        # Voice text state
        self._voice_text = ""
        self._voice_reveal_chars = 0
        self._voice_active = False

        # Mic icon state
        self._mic_visible = False
        self._mic_enabled = False
        self._mic_style = "bracket"  # "bracket" or "dot"

        # Calculate layout
        w, h = self.width, self.height
        bar_gap = 1
        total_content_h = self.AVATAR_HEIGHT + bar_gap + 1
        content_start_y = (h - total_content_h) // 2
        avatar_x_centered = (w - self.AVATAR_WIDTH) // 2
        self.bar_width = max(self.AVATAR_WIDTH, min(int(w * self.BAR_WIDTH_RATIO), w - 4))
        bar_x_centered = (w - self.bar_width) // 2
        self.avatar_x = avatar_x_centered + self.avatar_x_offset
        self.avatar_y = content_start_y + self.avatar_y_offset
        self.bar_x = bar_x_centered + self.bar_x_offset
        self.bar_y = content_start_y + self.AVATAR_HEIGHT + bar_gap + self.bar_y_offset

        # Initialize archetypes
        self.face = FaceArchetype(self.registry)
        self.weather = WeatherArchetype(self.registry, self.width, self.height)
        self.progress = ProgressArchetype(self.registry, self.bar_width)

        # Animation state
        self.current_status = "idle"

        # Pre-warm all caches
        self.face.prewarm_cache()
        self.progress.prewarm_cache()
        self.weather.prewarm_shapes()

    def set_status(self, status: str):
        """Set current status."""
        if status != self.current_status:
            self.current_status = status
            self.face.set_status(status)

    def set_weather(self, weather_type: str, intensity: float = 0.6, wind_speed: float = 0.0):
        """Set weather type and intensity."""
        self.weather.set_weather(weather_type, intensity, wind_speed)

    # Voice text display
    TEXT_X_MARGIN = 2
    TEXT_Y_START = 1
    TEXT_MAX_ROWS = 8

    def set_voice_text(self, text: str, reveal_chars: int) -> None:
        """Set voice text and how many characters to reveal."""
        self._voice_text = text
        self._voice_reveal_chars = reveal_chars
        self._voice_active = bool(text)

    def clear_voice_text(self) -> None:
        """Clear voice text display."""
        self._voice_text = ""
        self._voice_reveal_chars = 0
        self._voice_active = False

    # Mic icon display
    MIC_ICONS = {
        "bracket": {"on": "[M]", "off": "[\u00b7]"},
        "dot": {"on": "\u25c9", "off": "\u25cb"},
    }
    MIC_COLOR_OFF = 240  # dim gray

    def set_mic_state(self, visible: bool, enabled: bool, style: str = "bracket") -> None:
        """Update mic icon state for next render."""
        self._mic_visible = visible
        self._mic_enabled = enabled
        self._mic_style = style if style in self.MIC_ICONS else "bracket"

    def mic_icon_position(self) -> tuple[int, int, int]:
        """Return (row, col, width) for the current mic icon style.

        Positioned on the verb row (bar_y + 2), right-aligned, so it stays
        within the visible window area regardless of grid height.
        """
        icons = self.MIC_ICONS.get(self._mic_style, self.MIC_ICONS["bracket"])
        icon = icons["on"]
        icon_w = len(icon)
        row = self.bar_y + 2
        col = self.width - icon_w
        return row, col, icon_w

    def tick(self):
        """Advance animation state."""
        self.face.tick()
        self.weather.tick()

    def _render_weather(self):
        """Render weather layer."""
        self.weather_layer.clear()
        avatar_box = BoundingBox(x=self.avatar_x, y=self.avatar_y, w=self.AVATAR_WIDTH, h=self.AVATAR_HEIGHT)
        self.weather.set_exclusion_zones([avatar_box])
        self.weather.render(self.weather_layer, color=15)

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
            color = 220  # yellow — theme-independent
        else:
            # Nighttime: moon arcs from left to right
            art = self.MOON_ART
            # Normalize: 20->0, 21->1, ..., 24->4, 0->4, 1->5, ..., 6->10
            if hour >= 20:
                night_hour = hour - 20
            else:
                night_hour = hour + 4
            progress = night_hour / 10  # 10 hours of night
            color = 15

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
            color=StatusColors.get("idle").ansi,
        )

    def _render_mic_icon(self):
        """Render mic toggle icon at bottom-right of grid."""
        self.mic_layer.clear()
        if not self._mic_visible:
            return
        icons = self.MIC_ICONS.get(self._mic_style, self.MIC_ICONS["bracket"])
        icon = icons["on"] if self._mic_enabled else icons["off"]
        color = 0 if self._mic_enabled else self.MIC_COLOR_OFF
        row, col, _ = self.mic_icon_position()
        self.mic_layer.put_text(col, row, icon, color)

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

    def _render_voice_text(self):
        """Render voice response text with word-wrap and character reveal."""
        self.text_layer.clear()
        if not self._voice_active or not self._voice_text:
            return

        revealed = self._voice_text[: self._voice_reveal_chars]
        if not revealed:
            return

        text_width = self.width - (2 * self.TEXT_X_MARGIN)
        lines = self._word_wrap(revealed, text_width)

        # Tail-scroll: show last N lines if text exceeds available rows
        if len(lines) > self.TEXT_MAX_ROWS:
            lines = lines[-self.TEXT_MAX_ROWS :]

        for row_idx, line in enumerate(lines):
            y = self.TEXT_Y_START + row_idx
            if y >= self.height:
                break
            self.text_layer.put_text(self.TEXT_X_MARGIN, y, line, 255)

    @staticmethod
    def _word_wrap(text: str, width: int) -> list[str]:
        """Word-wrap text to fit within width columns."""
        words = text.split(" ")
        lines: list[str] = []
        current = ""

        for word in words:
            if len(word) > width:
                if current:
                    lines.append(current)
                    current = ""
                while len(word) > width:
                    lines.append(word[:width])
                    word = word[width:]
                current = word
                continue

            test = f"{current} {word}" if current else word
            if len(test) <= width:
                current = test
            else:
                lines.append(current)
                current = word

        if current:
            lines.append(current)
        return lines

    def render_grid(
        self,
        context_percent: float = 0,
        whimsy_verb: Optional[str] = None,
        hour: Optional[int] = None,
    ) -> tuple[list[str], list[list[int]]]:
        """Render complete frame and return structured grid data.

        Returns:
            (rows, cell_colors) — rows is a list of strings (one per grid row),
            cell_colors is a 2D list of ANSI 256 color codes per cell.
        """
        self._render_weather()
        self._render_celestial(hour)
        self._render_avatar()
        self._render_bar(context_percent)
        self._render_mic_icon()
        if not self._voice_active:
            self._render_verb(whimsy_verb)
        self._render_voice_text()
        return self.pipeline.to_grid()
