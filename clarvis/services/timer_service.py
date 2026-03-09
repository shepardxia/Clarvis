"""Named timer service with persistence and recurring support."""

import asyncio
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clarvis.core.context import AppContext

import pytimeparse2 as pytimeparse

from clarvis.core.paths import CLARVIS_HOME

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


_SIMPLE_TIME_RE = re.compile(
    r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$",
    re.IGNORECASE,
)

_24H_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_time(s: str) -> float:
    """Parse an absolute time string into seconds-until-fire.

    Accepted formats:
        "2026-03-07T15:00"      -> ISO datetime
        "2026-03-07T15:00:00"   -> ISO datetime with seconds
        "3pm"                   -> today (or tomorrow if past)
        "3:30pm"                -> today (or tomorrow if past)
        "3:30 PM"               -> today (or tomorrow if past)
        "15:00"                 -> 24h time, today (or tomorrow if past)

    Returns seconds until the target time.
    Raises ValueError if unparseable or if an ISO date is in the past.
    """
    s = s.strip()
    if not s:
        raise ValueError(f"Invalid time: {s!r}")

    now = datetime.now()

    # Try ISO format first
    if "T" in s or (len(s) >= 10 and s[4:5] == "-"):
        try:
            target = datetime.fromisoformat(s)
        except ValueError:
            raise ValueError(f"Invalid time: {s!r}")
        delta = (target - now).total_seconds()
        if delta <= 0:
            raise ValueError(f"Time is in the past: {s!r}")
        return delta

    # Try simple time-of-day: "3pm", "3:30pm", "3:30 PM"
    m = _SIMPLE_TIME_RE.match(s)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        ampm = m.group(3).lower()
        if hour < 1 or hour > 12:
            raise ValueError(f"Invalid time: {s!r}")
        if ampm == "am":
            hour = 0 if hour == 12 else hour
        else:
            hour = hour if hour == 12 else hour + 12
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    # Try 24h format: "15:00"
    m = _24H_TIME_RE.match(s)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        if hour > 23 or minute > 59:
            raise ValueError(f"Invalid time: {s!r}")
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    raise ValueError(f"Invalid time: {s!r}")


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
        state_file: Path | None = None,
    ) -> None:
        self._bus = ctx.bus
        self._loop = ctx.loop
        self._state_file = state_file if state_file else CLARVIS_HOME / "timers.json"
        self._timers: dict[str, Timer] = {}
        self._handles: dict[str, asyncio.TimerHandle] = {}
        self._lock = threading.Lock()
        self._dirty = False

    def set_timer(
        self,
        name: str,
        duration: float,
        recurring: bool = False,
        label: str = "",
        wake_clarvis: bool = False,
        at: float | None = None,
    ) -> Timer:
        """Create or replace a named timer.

        May be called from any thread. The underlying ``loop.call_later``
        is scheduled via ``call_soon_threadsafe``.

        If *at* is provided (seconds-until-fire from an absolute time),
        it is used instead of *duration* for scheduling.
        """
        delay = at if at is not None else duration
        now = time.time()
        timer = Timer(
            name=name,
            duration=delay,
            fire_at=now + delay,
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
        self._loop.call_soon_threadsafe(self._schedule, name, delay)
        logger.info("Timer set: %s (%.1fs, recurring=%s)", name, delay, recurring)
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
            # Flush directly on stop (bypass debounce)
            data = [asdict(t) for t in self._timers.values()]
            self._dirty = False
        json_save_atomic(self._state_file, data)
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
        """Schedule a ``call_later`` handle.

        Must be called on the event loop thread (event loop callbacks are
        serialized, so no additional locking is needed for ``_handles``).
        """
        handle = self._loop.call_later(delay, self._fire, name)
        self._handles[name] = handle

    def _cancel_handle(self, name: str) -> None:
        """Cancel an asyncio handle if it exists. Caller must hold ``_lock``."""
        handle = self._handles.pop(name, None)
        if handle is not None:
            handle.cancel()

    def _persist(self) -> None:
        """Mark dirty and schedule a flush. Caller must hold ``_lock``."""
        if not self._dirty:
            self._dirty = True
            self._loop.call_soon_threadsafe(self._flush_persist)

    def _flush_persist(self) -> None:
        """Actually write timers to disk (runs on event loop)."""
        with self._lock:
            if not self._dirty:
                return
            data = [asdict(t) for t in self._timers.values()]
            self._dirty = False
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
