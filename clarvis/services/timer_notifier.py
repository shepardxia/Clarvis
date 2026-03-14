"""Timer notification handler — display flash + sound."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.context import AppContext

logger = logging.getLogger(__name__)


class TimerNotifier:
    """Subscribes to ``timer:fired`` and handles UI notification (flash + sound)."""

    def __init__(self, ctx: "AppContext"):
        self._ctx = ctx
        ctx.bus.on("timer:fired", self._on_fired)

    def _on_fired(self, signal: str, *, name: str, label: str, **kw) -> None:
        self._flash_and_sound(name, label)

    def _flash_and_sound(self, name: str, label: str) -> None:
        from ..display.audio import play_system_sound

        self._ctx.state.update("status", {"status": "activated"}, force=True)

        def _revert() -> None:
            current = self._ctx.state.get("status")
            current_status = current.get("status", "idle") if current else "idle"
            if current_status == "activated":
                self._ctx.state.update("status", {"status": "idle"})

        self._ctx.loop.call_later(2.0, _revert)
        self._ctx.loop.create_task(play_system_sound("Glass"))
