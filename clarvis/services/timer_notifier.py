"""Timer notification handler — display flash + sound + optional voice."""

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..core.context import AppContext
    from ..display.display_manager import DisplayManager

logger = logging.getLogger(__name__)


class TimerNotifier:
    """Subscribes to ``timer:fired`` and handles UI notification + optional voice."""

    def __init__(
        self,
        ctx: "AppContext",
        display: "DisplayManager",
        voice_orchestrator_provider: Callable,
    ):
        self._ctx = ctx
        self._display = display
        self._get_voice = voice_orchestrator_provider
        ctx.bus.on("timer:fired", self._on_fired)

    def _on_fired(self, signal: str, *, name: str, label: str, wake_clarvis: bool = False, **kw) -> None:
        self._flash_and_sound(name, label)
        if wake_clarvis:
            self._voice_notify(name, label)

    def _flash_and_sound(self, name: str, label: str) -> None:
        from ..display.audio import play_system_sound

        self._display.set_status("activated")

        def _revert() -> None:
            current = self._ctx.state.get("status")
            current_status = current.get("status", "idle") if current else "idle"
            if current_status == "activated":
                self._display.set_status("idle")

        self._ctx.loop.call_later(2.0, _revert)
        self._ctx.loop.create_task(play_system_sound("Glass"))

    def _voice_notify(self, name: str, label: str) -> None:
        orchestrator = self._get_voice()
        if not orchestrator:
            return

        display_name = label or name
        prompt = f"Timer '{display_name}' just fired."
        if label and label != name:
            prompt = f"Timer '{name}' just fired. Label: {label}"
        self._ctx.loop.create_task(orchestrator.notify(prompt))
