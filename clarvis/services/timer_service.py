"""Named timer service with persistence and recurring support."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clarvis.core.signals import SignalBus

logger = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


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

    # Raw numeric value -> seconds
    try:
        val = float(s)
    except ValueError:
        pass  # Not a plain number -- fall through to pattern match
    else:
        if val <= 0:
            raise ValueError(f"Invalid duration: {s!r}")
        return val

    m = _DURATION_RE.match(s.lower())
    if not m or not any(m.groups()):
        raise ValueError(f"Invalid duration: {s!r}")

    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    total = hours * 3600 + minutes * 60 + seconds
    if total == 0:
        raise ValueError(f"Invalid duration: {s!r}")
    return float(total)


@dataclass
class Timer:
    """A named timer."""

    name: str
    duration: float
    fire_at: float
    recurring: bool
    created_at: float
    label: str
    trigger: str  # "simple" or "voice"


class TimerService:
    """Manages named one-shot and recurring timers.

    Timers are scheduled on the daemon's asyncio event loop via
    ``loop.call_later`` and persisted to ``~/.clarvis/timers.json``
    so they survive restarts.
    """

    def __init__(
        self,
        bus: SignalBus,
        loop: asyncio.AbstractEventLoop,
        state_file: str = "~/.clarvis/timers.json",
    ) -> None:
        self._bus = bus
        self._loop = loop
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
        trigger: str = "simple",
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
            trigger=trigger,
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
                        "trigger": t.trigger,
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
            trigger=timer.trigger,
        )
        logger.info("Timer fired: %s", name)

        reschedule_delay = None
        with self._lock:
            if timer.recurring:
                timer.fire_at = time.time() + timer.duration
                self._persist()
                reschedule_delay = timer.duration
            else:
                self._timers.pop(name, None)
                self._persist()

        # Schedule outside lock — _schedule writes _handles on the event loop
        if reschedule_delay is not None:
            self._schedule(name, reschedule_delay)

    def _schedule(self, name: str, delay: float) -> None:
        """Schedule a ``call_later`` handle. Must be called on the event loop.

        Does NOT acquire ``_lock`` — callers must handle synchronization.
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
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            data = [asdict(t) for t in self._timers.values()]
            tmp = self._state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(self._state_file)
        except OSError:
            logger.warning("Failed to persist timers", exc_info=True)

    def _load(self) -> None:
        """Load timers from disk. Graceful on missing/corrupt file."""
        if not self._state_file.exists():
            return
        try:
            raw = json.loads(self._state_file.read_text())
            with self._lock:
                for entry in raw:
                    timer = Timer(
                        name=entry["name"],
                        duration=entry["duration"],
                        fire_at=entry["fire_at"],
                        recurring=entry["recurring"],
                        created_at=entry["created_at"],
                        label=entry["label"],
                        trigger=entry.get("trigger", "simple"),
                    )
                    self._timers[timer.name] = timer
            logger.info("Loaded %d timer(s) from %s", len(self._timers), self._state_file)
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("Corrupt timers file %s, starting empty", self._state_file, exc_info=True)
