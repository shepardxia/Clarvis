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


class TestSchedulerRegistration:
    def test_register_task(self, loop):
        s = Scheduler(loop)
        s.register("t1", lambda: None, active_interval=10, idle_interval=60)
        assert "t1" in s._tasks

    def test_duplicate_name_raises(self, loop):
        s = Scheduler(loop)
        s.register("t1", lambda: None, active_interval=10, idle_interval=60)
        with pytest.raises(ValueError, match="already registered"):
            s.register("t1", lambda: None, active_interval=5, idle_interval=30)


class TestSchedulerLifecycle:
    def test_start_stop(self, loop):
        s = Scheduler(loop)
        s.register("t1", lambda: None, active_interval=10, idle_interval=60)
        s.start()
        assert s._running
        s.stop()
        assert not s._running

    def test_stop_cancels_handles(self, loop):
        s = Scheduler(loop)
        s.register("t1", lambda: None, active_interval=10, idle_interval=60)
        s.start()
        # Give the loop a moment to schedule
        time.sleep(0.05)
        s.stop()
        assert s._tasks["t1"].handle is None or s._tasks["t1"].handle.cancelled()

    def test_double_start_is_idempotent(self, loop):
        s = Scheduler(loop)
        s.register("t1", lambda: None, active_interval=10, idle_interval=60)
        s.start()
        s.start()  # Should not raise
        s.stop()


class TestSchedulerExecution:
    def test_inline_task_fires(self, loop):
        """Non-blocking task should fire within its interval."""
        results = []
        s = Scheduler(loop)
        s.register("t1", lambda: results.append(1), active_interval=0.05, idle_interval=1)
        s.start()
        time.sleep(0.2)
        s.stop()
        assert len(results) >= 2

    def test_blocking_task_fires(self, loop):
        """Blocking task should run in executor and still fire."""
        results = []

        def slow_task():
            time.sleep(0.01)
            results.append(1)

        s = Scheduler(loop)
        s.register("t1", slow_task, active_interval=0.05, idle_interval=1, blocking=True)
        s.start()
        time.sleep(0.3)
        s.stop()
        assert len(results) >= 2

    def test_task_exception_does_not_kill_scheduler(self, loop):
        """A failing task should be caught and rescheduled."""
        call_count = []

        def flaky():
            call_count.append(1)
            if len(call_count) == 1:
                raise RuntimeError("boom")

        s = Scheduler(loop)
        s.register("flaky", flaky, active_interval=0.05, idle_interval=1)
        s.start()
        time.sleep(0.2)
        s.stop()
        # Should have been called multiple times despite the first failure
        assert len(call_count) >= 2


class TestSchedulerModes:
    def test_initial_mode_is_active(self, loop):
        s = Scheduler(loop)
        assert s.mode == "active"

    def test_set_mode_changes_mode(self, loop):
        s = Scheduler(loop)
        s.register("t1", lambda: None, active_interval=10, idle_interval=60)
        s.start()
        s.set_mode("idle")
        time.sleep(0.05)  # Let call_soon_threadsafe propagate
        assert s.mode == "idle"
        s.stop()

    def test_set_same_mode_is_noop(self, loop):
        """Setting the same mode should not trigger callbacks."""
        calls = []
        s = Scheduler(loop)
        s.on_mode_change(lambda m: calls.append(m))
        s.register("t1", lambda: None, active_interval=10, idle_interval=60)
        s.start()
        s.set_mode("active")  # Already active
        time.sleep(0.05)
        assert len(calls) == 0
        s.stop()

    def test_mode_change_callback(self, loop):
        """Mode change should notify registered callbacks."""
        calls = []
        s = Scheduler(loop)
        s.on_mode_change(lambda m: calls.append(m))
        s.register("t1", lambda: None, active_interval=10, idle_interval=60)
        s.start()
        s.set_mode("idle")
        time.sleep(0.05)
        assert calls == ["idle"]
        s.set_mode("active")
        time.sleep(0.05)
        assert calls == ["idle", "active"]
        s.stop()

    def test_idle_mode_uses_idle_interval(self, loop):
        """Tasks should fire at idle_interval cadence in idle mode."""
        results = []
        s = Scheduler(loop)
        # active: 0.02s, idle: 0.5s — in idle mode we should see far fewer fires
        s.register("t1", lambda: results.append(1), active_interval=0.02, idle_interval=0.5)
        s.start()
        s.set_mode("idle")
        time.sleep(0.1)
        idle_count = len(results)
        s.stop()
        # In 0.1s with 0.5s interval, we should see at most 1 fire
        assert idle_count <= 1

    def test_active_mode_resumes_fast_cadence(self, loop):
        """Switching back to active should resume fast firing."""
        results = []
        s = Scheduler(loop)
        s.register("t1", lambda: results.append(1), active_interval=0.03, idle_interval=5)
        s.start()
        s.set_mode("idle")
        time.sleep(0.05)
        before = len(results)
        s.set_mode("active")
        time.sleep(0.15)
        after = len(results)
        s.stop()
        # Should have gained several results after switching back to active
        assert after - before >= 2
