"""Manages display rendering and frame output."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .colors import StatusColors

if TYPE_CHECKING:
    from ..widget.renderer import FrameRenderer
    from ..widget.socket_server import WidgetSocketServer


class DisplayManager:
    """Manages display rendering loop and frame output."""

    BORDER_STYLES = {
        "running": {"width": 3, "pulse": True},
        "thinking": {"width": 3, "pulse": True},
        "awaiting": {"width": 2, "pulse": True},
        "activated": {"width": 4, "pulse": True},  # Wake word detected - prominent pulse
        "resting": {"width": 1, "pulse": False},
        "idle": {"width": 1, "pulse": False},
        "offline": {"width": 1, "pulse": False},
    }

    def __init__(
        self,
        renderer: FrameRenderer,
        socket_server: WidgetSocketServer,
        output_file: Path,
        fps: int = 2,
    ):
        self.renderer = renderer
        self.socket_server = socket_server
        self.output_file = output_file
        self.fps = fps

        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def render_frame(
        self,
        status: str,
        context_percent: float,
        whimsy_verb: Optional[str] = None,
    ) -> dict:
        """Render a single frame and return the output dict."""
        with self._lock:
            # Get RGB color from theme
            color_def = StatusColors.get(status)
            display_color = list(color_def.rgb)

            frame = self.renderer.render_colored(context_percent, whimsy_verb)
            border = self.BORDER_STYLES.get(status, {"width": 1, "pulse": False})

            return {
                "frame": frame,
                "color": display_color,
                "status": status,
                "border_width": border["width"],
                "border_pulse": border["pulse"],
                "context_percent": context_percent,
                "whimsy_verb": whimsy_verb,
                "timestamp": time.time(),
            }

    def push_frame(self, output: dict) -> None:
        """Push frame to socket and file."""
        self.socket_server.push_frame(output)

        # Write to file (backward compatibility)
        temp_file = self.output_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(output))
        temp_file.rename(self.output_file)

    def tick(self) -> None:
        """Advance renderer animation state."""
        with self._lock:
            self.renderer.tick()

    def set_status(self, status: str) -> None:
        """Update renderer status."""
        with self._lock:
            self.renderer.set_status(status)

    def set_weather(self, weather_type: str, intensity: float, wind_speed: float) -> None:
        """Update renderer weather."""
        with self._lock:
            self.renderer.set_weather(weather_type, intensity, wind_speed)

    def _loop(self, get_state: callable) -> None:
        """Display rendering loop."""
        interval = 1.0 / self.fps

        while self._running:
            start = time.time()

            self.tick()
            status, context_percent, whimsy_verb = get_state()
            output = self.render_frame(status, context_percent, whimsy_verb)
            self.push_frame(output)

            elapsed = time.time() - start
            sleep_time = max(0, interval - elapsed)
            time.sleep(sleep_time)

    def start(self, get_state: callable) -> None:
        """Start the display loop.
        
        Args:
            get_state: Callable returning (status, context_percent, whimsy_verb)
        """
        if self._thread is not None and self._thread.is_alive():
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            args=(get_state,),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the display loop."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
