"""Unified periodic task scheduler running on the asyncio event loop.

Replaces scattered polling threads (RefreshManager, ConfigWatcher, staleness
checks, persist debounce) with a single scheduler that supports active/idle
mode transitions.  Tasks registered with two intervals are rescheduled
atomically when mode changes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

Mode = str  # "active" | "idle"


class _Task:
    """Internal representation of a registered periodic task."""

    __slots__ = (
        "name",
        "callback",
        "active_interval",
        "idle_interval",
        "blocking",
        "handle",
    )

    def __init__(
        self,
        name: str,
        callback: Callable,
        active_interval: float,
        idle_interval: float,
        blocking: bool,
    ):
        self.name = name
        self.callback = callback
        self.active_interval = active_interval
        self.idle_interval = idle_interval
        self.blocking = blocking
        self.handle: Optional[asyncio.TimerHandle] = None

    def interval_for(self, mode: Mode) -> float:
        return self.active_interval if mode == "active" else self.idle_interval


class Scheduler:
    """Unified periodic task runner in the asyncio event loop.

    Usage::

        scheduler = Scheduler(loop)
        scheduler.register("refresh", refresh_all, active_interval=30, idle_interval=300, blocking=True)
        scheduler.register("staleness", check_staleness, active_interval=5, idle_interval=30)
        scheduler.start()
        ...
        scheduler.set_mode("idle")   # reschedules all tasks at idle cadence
        ...
        scheduler.stop()
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._tasks: dict[str, _Task] = {}
        self._mode: Mode = "active"
        self._running = False
        self._mode_callbacks: list[Callable[[Mode], None]] = []

    @property
    def mode(self) -> Mode:
        return self._mode

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        callback: Callable,
        active_interval: float,
        idle_interval: float,
        blocking: bool = False,
    ) -> None:
        """Register a periodic task.

        Args:
            name: Unique task name.
            callback: Callable to invoke periodically. For blocking tasks,
                this is run via ``run_in_executor``.
            active_interval: Seconds between invocations in active mode.
            idle_interval: Seconds between invocations in idle mode.
            blocking: If True, run callback in the default executor (thread pool).
        """
        if name in self._tasks:
            raise ValueError(f"Task '{name}' already registered")
        self._tasks[name] = _Task(name, callback, active_interval, idle_interval, blocking)

    def on_mode_change(self, callback: Callable[[Mode], None]) -> None:
        """Register a listener notified on mode transitions."""
        self._mode_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start all registered tasks at the current mode's cadence.

        Thread-safe: schedules initial timers on the event loop.
        """
        if self._running:
            return
        self._running = True
        self._loop.call_soon_threadsafe(self._start_all)

    def _start_all(self) -> None:
        """Schedule all tasks (must be called on the event loop thread)."""
        for task in self._tasks.values():
            self._schedule(task)
        logger.info("Scheduler started in %s mode with %d tasks", self._mode, len(self._tasks))

    def stop(self) -> None:
        """Cancel all scheduled tasks."""
        self._running = False
        for task in self._tasks.values():
            if task.handle is not None:
                task.handle.cancel()
                task.handle = None
        logger.info("Scheduler stopped")

    # ------------------------------------------------------------------
    # Mode transitions
    # ------------------------------------------------------------------

    def set_mode(self, mode: Mode) -> None:
        """Switch mode and reschedule all tasks. Thread-safe."""
        if mode == self._mode:
            return
        self._loop.call_soon_threadsafe(self._apply_mode, mode)

    def _apply_mode(self, mode: Mode) -> None:
        """Apply mode change on the event loop thread."""
        if mode == self._mode:
            return
        old = self._mode
        self._mode = mode
        logger.info("Scheduler mode: %s → %s", old, mode)

        if self._running:
            for task in self._tasks.values():
                if task.handle is not None:
                    task.handle.cancel()
                self._schedule(task)

        for cb in self._mode_callbacks:
            try:
                cb(mode)
            except Exception:
                logger.exception("Mode change callback failed")

    # ------------------------------------------------------------------
    # Internal scheduling
    # ------------------------------------------------------------------

    def _schedule(self, task: _Task) -> None:
        """Schedule the next invocation of *task*."""
        interval = task.interval_for(self._mode)
        task.handle = self._loop.call_later(interval, self._fire, task)

    def _fire(self, task: _Task) -> None:
        """Timer callback — run the task and reschedule."""
        if not self._running:
            return

        if task.blocking:
            self._loop.run_in_executor(None, self._run_blocking, task)
        else:
            try:
                task.callback()
            except Exception:
                logger.exception("Scheduler task '%s' failed", task.name)
            self._schedule(task)

    def _run_blocking(self, task: _Task) -> None:
        """Execute a blocking task in the thread pool, then reschedule on the loop."""
        try:
            task.callback()
        except Exception:
            logger.exception("Scheduler blocking task '%s' failed", task.name)
        # Reschedule on the event loop thread
        if self._running:
            self._loop.call_soon_threadsafe(self._schedule, task)
