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

    def push_frame(self, output: dict) -> None:
        """Push frame to socket."""
        self.socket_server.push_frame(output)

    def tick(self) -> None:
        """Advance scene animation state."""
        with self._lock:
            ctx = self._build_tick_context()
            self.scene.tick(**ctx)

    def set_fps(self, fps: int) -> None:
        """Update render FPS. Takes effect on the next loop iteration."""
        self.fps = max(1, fps)

    def freeze(self) -> None:
        """Freeze rendering -- zero CPU until wake() is called."""
        self._frozen = True

    def wake(self) -> None:
        """Resume rendering from frozen state."""
        if self._frozen:
            self._frozen = False
            self._wake_event.set()

    def _build_tick_context(self) -> dict:
        """Build tick context by reading directly from StateStore.

        Uses ``peek()`` (shallow copy, no deepcopy) since we only read
        values here — never mutate the returned dicts.
        """
        ctx: dict = {}

        if self._state_store:
            # Status -- read from StateStore
            status_data = self._state_store.peek("status")
            ctx["status"] = status_data.get("status", "idle") if status_data else "idle"

            # Weather -- read from StateStore
            weather = self._state_store.peek("weather")
            ctx["weather_type"] = weather.get("widget_type", "clear") if weather else "clear"
            ctx["weather_intensity"] = weather.get("widget_intensity", 0.0) if weather else 0.0
            ctx["wind_speed"] = weather.get("wind_speed", 0.0) if weather else 0.0

            # Voice text
            voice_data = self._state_store.peek("voice_text")
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
            mic = self._state_store.peek("mic") or {}
            ctx["mic_visible"] = mic.get("visible", False)
            ctx["mic_enabled"] = mic.get("enabled", False)
            ctx["mic_style"] = mic.get("style", "bracket")
        else:
            ctx["status"] = "idle"
            ctx["weather_type"] = "clear"
            ctx["weather_intensity"] = 0.0
            ctx["wind_speed"] = 0.0

        return ctx

    def _loop(self, get_state: Callable[[], str]) -> None:
        """Display rendering loop.

        tick() acquires the lock separately, then state reads and rendering
        happen under a second lock acquisition. Uses RLock so callbacks
        can re-enter safely.

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
                # Call get_state for side effects (e.g. testing mode writes to StateStore)
                get_state()
                ctx = self._build_tick_context()
                status = ctx["status"]
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

    def start(self, get_state: Callable[[], str], state_store: "StateStore | None" = None) -> None:
        """Start the display loop.

        Args:
            get_state: Callable returning status string (for side effects)
            state_store: StateStore for reading display state
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
