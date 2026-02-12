"""Signal bus — lightweight named-event pub/sub.

Signal naming convention: 'category:event'
  e.g., 'timer:fired', 'playback:queue_empty', 'playback:stopped'
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class SignalBus:
    """Named event pub/sub. Thread-safe, asyncio-aware.

    Listeners are sync callables that receive (signal, **data).
    If called from the event loop thread, listeners run inline.
    If called from another thread, delivery is scheduled via call_soon_threadsafe.
    Exceptions in one listener don't block others.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._listeners: dict[str, list[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def on(self, signal: str, callback: Callable[..., Any]) -> None:
        """Subscribe to a named signal. Callback receives (signal, **data)."""
        with self._lock:
            self._listeners[signal].append(callback)

    def off(self, signal: str, callback: Callable) -> None:
        """Unsubscribe a callback from a signal."""
        with self._lock:
            try:
                self._listeners[signal].remove(callback)
            except ValueError:
                pass

    def emit(self, signal: str, **data) -> None:
        """Fire a signal to all listeners. Thread-safe.

        If on the event loop thread: calls listeners inline.
        If on another thread: schedules via call_soon_threadsafe.
        """
        with self._lock:
            callbacks = list(self._listeners.get(signal, []))
        if not callbacks:
            return

        # Check if we're on the event loop thread
        try:
            running = asyncio.get_running_loop()
            on_loop = running is self._loop
        except RuntimeError:
            on_loop = False

        if on_loop:
            self._deliver(signal, callbacks, data)
        else:
            self._loop.call_soon_threadsafe(self._deliver, signal, callbacks, data)

    def _deliver(self, signal: str, callbacks: list[Callable], data: dict) -> None:
        """Call each listener, catching exceptions per-listener."""
        for cb in callbacks:
            try:
                cb(signal, **data)
            except Exception:
                logger.exception("Signal listener error for %r", signal)
