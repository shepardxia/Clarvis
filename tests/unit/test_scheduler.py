"""Tests for the unified Scheduler."""

import asyncio
import threading
import time

import pytest

from clarvis.core.scheduler import Scheduler


@pytest.fixture
def loop():
    """Create and run an event loop in a background thread."""
    _loop = asyncio.new_event_loop()
    t = threading.Thread(target=_loop.run_forever, daemon=True)
    t.start()
    yield _loop
    _loop.call_soon_threadsafe(_loop.stop)
    t.join(timeout=2)
    _loop.close()


def test_register_and_duplicate(loop):
    s = Scheduler(loop)
    s.register("t1", lambda: None, active_interval=10, idle_interval=60)
    assert "t1" in s._tasks
    with pytest.raises(ValueError, match="already registered"):
        s.register("t1", lambda: None, active_interval=5, idle_interval=30)


def test_lifecycle(loop):
    s = Scheduler(loop)
    s.register("t1", lambda: None, active_interval=10, idle_interval=60)
    s.start()
    assert s._running
    s.start()  # idempotent
    assert s._running
    time.sleep(0.05)
    s.stop()
    assert not s._running
    assert s._tasks["t1"].handle is None or s._tasks["t1"].handle.cancelled()


def test_inline_task_fires(loop):
    results = []
    s = Scheduler(loop)
    s.register("t1", lambda: results.append(1), active_interval=0.05, idle_interval=1)
    s.start()
    time.sleep(0.2)
    s.stop()
    assert len(results) >= 2


def test_blocking_task_fires(loop):
    results = []

    def slow():
        time.sleep(0.01)
        results.append(1)

    s = Scheduler(loop)
    s.register("t1", slow, active_interval=0.05, idle_interval=1, blocking=True)
    s.start()
    time.sleep(0.3)
    s.stop()
    assert len(results) >= 2


def test_exception_doesnt_kill_scheduler(loop):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")

    s = Scheduler(loop)
    s.register("flaky", flaky, active_interval=0.05, idle_interval=1)
    s.start()
    time.sleep(0.2)
    s.stop()
    assert len(calls) >= 2


def test_mode_lifecycle(loop):
    mode_changes = []
    s = Scheduler(loop)
    s.on_mode_change(lambda m: mode_changes.append(m))
    s.register("t1", lambda: None, active_interval=10, idle_interval=60)

    assert s.mode == "active"
    s.start()
    s.set_mode("active")  # same mode — noop
    time.sleep(0.05)
    assert mode_changes == []

    s.set_mode("idle")
    time.sleep(0.05)
    assert s.mode == "idle"
    assert mode_changes == ["idle"]

    s.set_mode("active")
    time.sleep(0.05)
    assert mode_changes == ["idle", "active"]
    s.stop()


def test_idle_vs_active_cadence(loop):
    results = []
    s = Scheduler(loop)
    s.register("t1", lambda: results.append(1), active_interval=0.02, idle_interval=0.5)
    s.start()

    # Idle: 0.5s interval → at most 1 fire in 0.1s
    s.set_mode("idle")
    time.sleep(0.1)
    idle_count = len(results)
    assert idle_count <= 1

    # Active: 0.02s interval → several fires in 0.15s
    results.clear()
    s.set_mode("active")
    time.sleep(0.15)
    s.stop()
    assert len(results) >= 2
