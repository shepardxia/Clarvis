"""Named timer service with persistence and recurring support."""

import asyncio
import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clarvis.core.context import AppContext

import pytimeparse2 as pytimeparse

from ..core.persistence import json_load_safe, json_save_atomic

logger = logging.getLogger(__name__)


def parse_duration(s: str) -> float:
    """Parse a human-readable duration string into seconds.

    Accepted formats:
        "5m"       -> 300.0
        "1h30m"    -> 5400.0
        "90s"      -> 90.0
        "1h"       -> 3600.0
        "45"       -> 45.0   (raw number = seconds)
        "2h30m15s" -> 9015.0

    Raises:
        ValueError: If the string cannot be parsed.
    """
    s = s.strip()
    if not s:
        raise ValueError(f"Invalid duration: {s!r}")

    result = pytimeparse.parse(s)
    if result is None or result <= 0:
        raise ValueError(f"Invalid duration: {s!r}")
    return float(result)


@dataclass
class Timer:
    """A named timer."""

    name: str
    duration: float
    fire_at: float
    recurring: bool
    created_at: float
    label: str
    wake_clarvis: bool


class TimerService:
    """Manages named one-shot and recurring timers.

    Timers are scheduled on the daemon's asyncio event loop via
    ``loop.call_later`` and persisted to ``~/.clarvis/timers.json``
    so they survive restarts.
    """

    def __init__(
        self,
        ctx: "AppContext",
        state_file: str = "~/.clarvis/timers.json",
    ) -> None:
        self._bus = ctx.bus
        self._loop = ctx.loop
        self._state_file = Path(state_file).expanduser()
        self._timers: dict[str, Timer] = {}
        self._handles: dict[str, asyncio.TimerHandle] = {}
        self._lock = threading.Lock()

    def set_timer(
        self,
        name: str,
        duration: float,
        recurring: bool = False,
        label: str = "",
        wake_clarvis: bool = False,
    ) -> Timer:
        """Create or replace a named timer.

        May be called from any thread. The underlying ``loop.call_later``
        is scheduled via ``call_soon_threadsafe``.
        """
        now = time.time()
        timer = Timer(
            name=name,
            duration=duration,
            fire_at=now + duration,
            recurring=recurring,
            created_at=now,
            label=label,
            wake_clarvis=wake_clarvis,
        )

        with self._lock:
            # Cancel existing timer with the same name
            self._cancel_handle(name)
            self._timers[name] = timer
            self._persist()

        # Schedule on event loop (thread-safe)
        self._loop.call_soon_threadsafe(self._schedule, name, duration)
        logger.info("Timer set: %s (%.1fs, recurring=%s)", name, duration, recurring)
        return timer

    def cancel(self, name: str) -> bool:
        """Cancel a timer by name. Returns True if it existed."""
        with self._lock:
            if name not in self._timers:
                return False
            self._cancel_handle(name)
            del self._timers[name]
            self._persist()
            logger.info("Timer cancelled: %s", name)
            return True

    def list_timers(self) -> list[dict]:
        """List all active timers with remaining time."""
        now = time.time()
        result = []
        with self._lock:
            for t in self._timers.values():
                result.append(
                    {
                        "name": t.name,
                        "label": t.label,
                        "duration": t.duration,
                        "remaining": max(0.0, t.fire_at - now),
                        "recurring": t.recurring,
                        "wake_clarvis": t.wake_clarvis,
                        "created_at": datetime.fromtimestamp(t.created_at, tz=timezone.utc).isoformat(),
                    }
                )
        return result

    def start(self) -> None:
        """Load persisted timers and schedule them.

        Must be called from the event loop thread (or wrapped in
        ``call_soon_threadsafe``).
        """
        self._load()
        now = time.time()
        with self._lock:
            for name, timer in list(self._timers.items()):
                remaining = timer.fire_at - now
                if remaining <= 0:
                    self._loop.call_soon_threadsafe(self._fire, name)
                else:
                    self._schedule(name, remaining)
        logger.info("TimerService started, %d timer(s) loaded", len(self._timers))

    def stop(self) -> None:
        """Cancel all handles and persist state."""
        with self._lock:
            for name in list(self._handles):
                self._cancel_handle(name)
            self._persist()
        logger.info("TimerService stopped")

    def _fire(self, name: str) -> None:
        """Called on the event loop when a timer expires."""
        with self._lock:
            timer = self._timers.get(name)
            if timer is None:
                return
            # Remove handle reference (it has already fired)
            self._handles.pop(name, None)

        self._bus.emit(
            "timer:fired",
            name=timer.name,
            label=timer.label,
            recurring=timer.recurring,
            duration=timer.duration,
            wake_clarvis=timer.wake_clarvis,
        )
        logger.info("Timer fired: %s", name)

        with self._lock:
            if timer.recurring:
                timer.fire_at = time.time() + timer.duration
                self._schedule(name, timer.duration)
            else:
                self._timers.pop(name, None)
            self._persist()

    def _schedule(self, name: str, delay: float) -> None:
        """Schedule a ``call_later`` handle. Must be called on the event loop.

        Caller must hold ``_lock`` — writes to ``_handles``.
        """
        handle = self._loop.call_later(delay, self._fire, name)
        self._handles[name] = handle

    def _cancel_handle(self, name: str) -> None:
        """Cancel an asyncio handle if it exists. Caller must hold ``_lock``."""
        handle = self._handles.pop(name, None)
        if handle is not None:
            handle.cancel()

    def _persist(self) -> None:
        """Save active timers to disk. Caller must hold ``_lock``."""
        data = [asdict(t) for t in self._timers.values()]
        json_save_atomic(self._state_file, data)

    def _load(self) -> None:
        """Load timers from disk. Graceful on missing/corrupt file."""
        raw = json_load_safe(self._state_file)
        if raw is None:
            return
        with self._lock:
            for entry in raw:
                wake = entry.get("wake_clarvis", False)
                timer = Timer(
                    name=entry["name"],
                    duration=entry["duration"],
                    fire_at=entry["fire_at"],
                    recurring=entry["recurring"],
                    created_at=entry["created_at"],
                    label=entry["label"],
                    wake_clarvis=wake,
                )
                self._timers[timer.name] = timer
        logger.info("Loaded %d timer(s) from %s", len(self._timers), self._state_file)
