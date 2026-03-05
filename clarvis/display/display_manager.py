"""Manages display rendering and frame output."""

import threading
import time
from typing import TYPE_CHECKING, Callable

from .colors import StatusColors

if TYPE_CHECKING:
    from ..core.state import StateStore
    from .socket_server import WidgetSocketServer
    from .sprites.scenes import SceneManager


class DisplayManager:
    """Manages display rendering loop and frame output."""

    def __init__(
        self,
        scene: "SceneManager",
        socket_server: "WidgetSocketServer",
        fps: int = 2,
    ):
        self.scene = scene
        self.socket_server = socket_server
        self.fps = fps

        self._lock = threading.RLock()
        self._running = False
        self._frozen = False
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_store: "StateStore | None" = None

        # Cached state for tick context
        self._status = "idle"
        self._weather_type = "clear"
        self._weather_intensity = 0.0
        self._wind_speed = 0.0

    def push_frame(self, output: dict) -> None:
        """Push frame to socket."""
        self.socket_server.push_frame(output)

    def tick(self) -> None:
        """Advance scene animation state."""
        with self._lock:
            ctx = self._build_tick_context()
            self.scene.tick(**ctx)

    def set_status(self, status: str) -> None:
        """Update status for next tick context."""
        with self._lock:
            self._status = status

    def set_weather(self, weather_type: str, intensity: float, wind_speed: float) -> None:
        """Update weather for next tick context."""
        with self._lock:
            self._weather_type = weather_type
            self._weather_intensity = intensity
            self._wind_speed = wind_speed

    def set_fps(self, fps: int) -> None:
        """Update render FPS. Takes effect on the next loop iteration."""
        self.fps = max(1, fps)

    def freeze(self) -> None:
        """Freeze rendering — zero CPU until wake() is called."""
        self._frozen = True

    def wake(self) -> None:
        """Resume rendering from frozen state."""
        if self._frozen:
            self._frozen = False
            self._wake_event.set()

    def _build_tick_context(self) -> dict:
        """Build tick context from state store and cached values."""
        ctx = {
            "status": self._status,
            "context_percent": 0.0,
            "weather_type": self._weather_type,
            "weather_intensity": self._weather_intensity,
            "wind_speed": self._wind_speed,
        }

        if self._state_store:
            # Voice text
            voice_data = self._state_store.get("voice_text")
            if voice_data and voice_data.get("active"):
                full_text = voice_data.get("full_text", "")
                tts_started = voice_data.get("tts_started_at", 0)
                tts_speed = voice_data.get("tts_speed", 150)
                streaming = voice_data.get("streaming", False)

                if streaming or tts_started <= 0:
                    reveal_chars = len(full_text)
                else:
                    elapsed = time.time() - tts_started
                    elapsed = max(0, elapsed - 0.25)
                    chars_per_sec = tts_speed * 5.0 / 60.0
                    target_chars = min(int(elapsed * chars_per_sec), len(full_text))
                    if target_chars < len(full_text):
                        space_idx = full_text.rfind(" ", 0, target_chars + 1)
                        reveal_chars = space_idx + 1 if space_idx > 0 else target_chars
                    else:
                        reveal_chars = len(full_text)

                ctx["voice_text"] = full_text
                ctx["reveal_chars"] = reveal_chars

            # Mic state
            mic = self._state_store.get("mic") or {}
            ctx["mic_visible"] = mic.get("visible", False)
            ctx["mic_enabled"] = mic.get("enabled", False)
            ctx["mic_style"] = mic.get("style", "bracket")

        return ctx

    def _loop(self, get_state: Callable[[], tuple[str, float]]) -> None:
        """Display rendering loop.

        tick() acquires the lock separately, then state reads and rendering
        happen under a second lock acquisition. Uses RLock so callbacks
        (e.g., testing-mode set_status/set_weather) can re-enter safely.

        When frozen, the thread sleeps on an Event with zero CPU cost.
        wake() resumes rendering instantly.
        """
        while self._running:
            # Frozen: sleep until wake() is called
            if self._frozen:
                self._wake_event.wait(timeout=5.0)
                self._wake_event.clear()
                continue

            interval = 1.0 / self.fps
            start = time.time()

            with self._lock:
                status, context_percent = get_state()
                self._status = status
                ctx = self._build_tick_context()
                ctx["context_percent"] = context_percent
                self.scene.tick(**ctx)
                color_def = StatusColors.get(status)
                rows, cell_colors = self.scene.to_grid()
                output = {
                    "rows": rows,
                    "cell_colors": cell_colors,
                    "theme_color": list(color_def.rgb),
                }
            self.push_frame(output)

            elapsed = time.time() - start
            sleep_time = max(0, interval - elapsed)
            time.sleep(sleep_time)

    def start(self, get_state: Callable[[], tuple[str, float]], state_store: "StateStore | None" = None) -> None:
        """Start the display loop.

        Args:
            get_state: Callable returning (status, context_percent)
            state_store: Optional StateStore for voice text reveal calculation
        """
        if self._thread is not None and self._thread.is_alive():
            return

        self._state_store = state_store
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
        self._wake_event.set()  # Unblock if frozen
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
