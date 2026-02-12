#!/usr/bin/env python3
"""Background daemon for Clarvis - handles status processing and data refreshes.

CentralHubDaemon is the orchestration layer that wires together:
- HookProcessor: translates Claude Code hook events into semantic statuses
- CommandHandlers: IPC request handlers for MCP server communication
- DisplayManager: FPS-limited rendering loop
- RefreshManager: periodic weather/location/time updates
- Scheduler: unified periodic task runner (replaces scattered polling threads)
- StateStore: single source of truth for all state
"""

from __future__ import annotations

import asyncio
import atexit
import fcntl
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from .core.command_handlers import CommandHandlers
from .core.display_manager import DisplayManager
from .core.hook_processor import HookProcessor
from .core.ipc import DaemonServer
from .core.refresh_manager import RefreshManager
from .core.scheduler import Scheduler
from .core.session_tracker import SessionTracker
from .core.signals import SignalBus
from .core.state import StateStore, get_state_store
from .services.context_accumulator import ContextAccumulator, extract_project_from_slug
from .services.timer_service import TimerService
from .widget.click_regions import ClickRegion, ClickRegionManager
from .widget.config import get_config
from .widget.renderer import FrameRenderer
from .widget.socket_server import WidgetSocketServer, get_socket_server

logger = logging.getLogger(__name__)


class PidLock:
    """Ensures only one daemon instance runs at a time using PID file locking.

    Features:
    - Atomic locking with fcntl.flock()
    - Stale PID detection (handles crashed processes)
    - Signal handler registration for cleanup
    - Context manager support
    """

    DEFAULT_PID_FILE = Path("/tmp/clarvis-daemon.pid")

    def __init__(self, pid_file: Path = None):
        self.pid_file = pid_file or self.DEFAULT_PID_FILE
        self._lock_fd: Optional[int] = None
        self._original_handlers: dict = {}

    def acquire(self) -> bool:
        """Attempt to acquire the daemon lock.

        Returns:
            True if lock acquired, False if another instance is running.
        """
        if self.pid_file.exists():
            try:
                old_pid = int(self.pid_file.read_text().strip())
                os.kill(old_pid, 0)
            except (ValueError, ProcessLookupError, PermissionError):
                try:
                    self.pid_file.unlink()
                except OSError:
                    pass

        try:
            self._lock_fd = os.open(str(self.pid_file), os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as e:
            print(f"Error: Cannot create PID file {self.pid_file}: {e}", file=sys.stderr)
            return False

        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            os.close(self._lock_fd)
            self._lock_fd = None
            try:
                existing_pid = self.pid_file.read_text().strip()
                print(f"Error: Daemon already running (PID {existing_pid})", file=sys.stderr)
            except Exception:
                print("Error: Daemon already running", file=sys.stderr)
            return False

        os.ftruncate(self._lock_fd, 0)
        os.write(self._lock_fd, f"{os.getpid()}\n".encode())
        os.fsync(self._lock_fd)

        self._register_signal_handlers()
        atexit.register(self.release)
        return True

    def release(self) -> None:
        """Release the daemon lock and clean up."""
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

        try:
            self.pid_file.unlink()
        except OSError:
            pass

        for sig, handler in self._original_handlers.items():
            signal.signal(sig, handler)
        self._original_handlers.clear()

    def _register_signal_handlers(self) -> None:
        """Register signal handlers for graceful cleanup."""

        def cleanup_handler(signum, frame):
            self.release()
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

        for sig in (signal.SIGTERM, signal.SIGINT):
            self._original_handlers[sig] = signal.signal(sig, cleanup_handler)

    def __enter__(self) -> "PidLock":
        if not self.acquire():
            raise RuntimeError("Failed to acquire daemon lock")
        return self

    def __exit__(self, *args) -> None:
        self.release()


# Global lock instance for daemon
_daemon_lock: Optional[PidLock] = None


class CentralHubDaemon:
    """Background daemon for Clarvis - uses StateStore as single source of truth.

    Orchestrates hook processing, command handling, display rendering,
    and background services. Delegates domain logic to focused modules:

    - HookProcessor: event classification, staleness, context building
    - CommandHandlers: IPC request handlers for MCP server
    - DisplayManager: rendering loop
    - RefreshManager: data refresh (passive, driven by Scheduler)
    - Scheduler: unified periodic tasks (replaces RefreshManager thread,
      ConfigWatcher thread, staleness polling, and persist debounce timers)
    """

    def __init__(
        self,
        refresh_interval: int = 30,
        display_fps: int = None,
        state_store: StateStore = None,
        socket_server: WidgetSocketServer = None,
    ):
        self.refresh_interval = refresh_interval

        config = get_config()
        self.display_fps = display_fps if display_fps is not None else config.display.fps

        # Core state
        self.state = state_store or get_state_store()
        self.session_tracker = SessionTracker(self.state)
        self.command_server = DaemonServer()
        self.token_usage_service = None
        self.wake_word_service = None
        self.voice_agent = None
        self.voice_orchestrator = None
        self.context_accumulator = ContextAccumulator()

        # Memory service (optional — requires cognee)
        self.memory_service = None
        if config.memory.enabled:
            try:
                from .services.cognee_memory import CogneeMemoryService

                self.memory_service = CogneeMemoryService()
            except ImportError:
                logger.info("cognee not installed — memory disabled")
        # Home project path — only stage sessions from this project
        self._home_project = Path(__file__).resolve().parents[2]
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._mcp_task: Optional[asyncio.Task] = None
        self.scheduler: Optional[Scheduler] = None
        self.timer_service: Optional[TimerService] = None
        self.bus: Optional[SignalBus] = None

        self.running = False

        # Display manager with pre-warmed renderer
        renderer = FrameRenderer(
            width=config.display.grid_width,
            height=config.display.grid_height,
            avatar_x_offset=config.display.avatar_x_offset,
            avatar_y_offset=config.display.avatar_y_offset,
            bar_x_offset=config.display.bar_x_offset,
            bar_y_offset=config.display.bar_y_offset,
        )
        self.socket_server = socket_server or get_socket_server()
        self.click_manager = ClickRegionManager(self.socket_server)
        self.display = DisplayManager(
            renderer=renderer,
            socket_server=self.socket_server,
            fps=self.display_fps,
        )

        # Whimsy verb manager (optional — requires anthropic)
        self.whimsy = None
        try:
            from .services.whimsy_verb import WhimsyManager

            self.whimsy = WhimsyManager(
                context_provider=lambda: self.hook_processor.get_rich_context(),
            )
        except ImportError:
            logger.info("anthropic not installed — whimsy verbs disabled")

        # Refresh manager (passive — Scheduler drives it)
        self.refresh = RefreshManager(
            state=self.state,
            display_manager=self.display,
        )

        # Hook processor (event classification, staleness, context)
        self.hook_processor = HookProcessor(
            state=self.state,
            session_tracker=self.session_tracker,
        )

        # Command handlers (IPC request handlers for MCP server)
        self.commands = CommandHandlers(
            state=self.state,
            session_tracker=self.session_tracker,
            refresh=self.refresh,
            whimsy=self.whimsy,
            command_server=self.command_server,
            token_usage_service_provider=lambda: self.token_usage_service,
            voice_orchestrator_provider=lambda: self.voice_orchestrator,
        )

    # --- Hook event processing (delegated to HookProcessor) ---

    def process_hook_event(self, raw_data: dict) -> dict:
        """Process raw hook event into status/color based on tool_name."""
        return self.hook_processor.process_hook_event(raw_data)

    def _handle_hook_event(self, **raw_data) -> dict:
        """Process a hook event received via IPC (replaces file-based watcher)."""
        # Stash transcript_path for whimsy context
        tp = raw_data.get("transcript_path")
        if tp:
            self.hook_processor.last_transcript_path = tp

        processed = self.process_hook_event(raw_data)
        self.state.update("status", processed)

        if processed.get("session_id") == self.session_tracker.displayed_id and not self.state.status_locked:
            self.display.set_status(processed.get("status", "idle"))

        event = raw_data.get("hook_event_name")
        if event:
            self.whimsy.maybe_generate(event)
        self.session_tracker.cleanup_stale()

        # Stage completed sessions for memory check-in (home project only)
        if event == "Stop" and tp and self.context_accumulator:
            slug = Path(tp).parent.name
            _, project_path = extract_project_from_slug(slug)
            if Path(project_path).resolve() == self._home_project:
                session_id = raw_data.get("session_id", "unknown")
                self.context_accumulator.stage_session(session_id, tp)

        if event != "Stop" and self.scheduler:
            self.scheduler.set_mode("active")

    # --- Staleness check (called by Scheduler) ---

    def _check_staleness(self) -> None:
        """Check for stale status and reset to idle + switch to idle mode."""
        stale_reset = self.hook_processor.check_status_staleness()
        if stale_reset and not self.state.status_locked:
            self.display.set_status("idle")
            if self.scheduler:
                self.scheduler.set_mode("idle")

    # --- Health check (called by Scheduler) ---

    def _check_health(self) -> None:
        """Restart display thread if it died unexpectedly."""
        if self.display._thread and not self.display._thread.is_alive():
            self.display.start(self._get_display_state, state_store=self.state)

    # --- Mode transitions ---

    def _on_mode_change(self, mode: str) -> None:
        """Handle scheduler mode transitions — adjust display FPS."""
        if mode == "active":
            self.display.set_fps(self.display_fps)
        else:
            self.display.set_fps(1)

    # --- Display state ---

    def _get_display_state(self) -> tuple[str, float, str | None]:
        """Get current display state for rendering.

        Returns:
            Tuple of (status, context_percent, whimsy_verb)
        """
        config = get_config()

        if config.testing.enabled:
            self.display.set_status(config.testing.status)
            self.display.set_weather(
                config.testing.weather, config.testing.weather_intensity, config.testing.wind_speed
            )
            return config.testing.status, config.testing.context_percent, self.whimsy.current_verb

        status = self.state.get("status")
        context_percent = status.get("context_percent", 0) if status else 0
        display_status = status.get("status", "idle") if status else "idle"
        return display_status, context_percent, self.whimsy.current_verb

    # --- Voice pipeline ---

    def _init_voice_pipeline(self) -> None:
        """Initialize voice agent + orchestrator with the captured event loop.

        Called from run() after self._event_loop is set, so both
        components receive the loop for consistent thread-to-async bridging.
        """
        config = get_config()
        needs_voice = (
            config.wake_word.enabled
            and config.voice.enabled
            and self.wake_word_service is not None
            and self._event_loop is not None
        )
        if not needs_voice:
            return

        from .services.voice_agent import VoiceAgent
        from .services.voice_orchestrator import VoiceCommandOrchestrator

        self.voice_agent = VoiceAgent(
            event_loop=self._event_loop,
            model=config.voice.model,
            max_thinking_tokens=config.voice.max_thinking_tokens,
            idle_timeout=config.voice.idle_timeout,
        )
        self.voice_orchestrator = VoiceCommandOrchestrator(
            event_loop=self._event_loop,
            socket_server=self.socket_server,
            voice_agent=self.voice_agent,
            state_store=self.state,
            wake_word_service=self.wake_word_service,
            tts_voice=config.voice.tts_voice,
            tts_speed=config.voice.tts_speed,
            tts_enabled=config.voice.tts_enabled,
            asr_timeout=config.voice.asr_timeout,
            asr_language=config.voice.asr_language,
            silence_timeout=config.voice.silence_timeout,
            text_linger=config.voice.text_linger,
        )
        # Register mic toggle region
        self._register_mic_region()
        print("[Daemon] Voice command pipeline initialized", flush=True)

    def _handle_widget_message(self, message: dict) -> None:
        """General dispatcher for messages from the widget.

        Routes ``region_click`` to the click manager (on the event loop
        for thread safety), everything else to the voice orchestrator.
        """
        method = message.get("method")
        if method == "region_click":
            region_id = message.get("params", {}).get("id", "")
            if self._event_loop:
                self._event_loop.call_soon_threadsafe(self.click_manager.handle_click, region_id)
        elif self.voice_orchestrator:
            self.voice_orchestrator.handle_widget_message(message)

    def _register_mic_region(self) -> None:
        """Register the mic-toggle click region and update state."""
        row, col, width = self.display.renderer.mic_icon_position()
        region = ClickRegion("mic_toggle", row=row, col=col, width=width, height=1)
        self.click_manager.register(region, self._toggle_voice)
        self.state.update(
            "mic",
            {
                "visible": True,
                "enabled": self.wake_word_service is not None and self.wake_word_service.is_running,
                "style": "bracket",
            },
        )

    def _toggle_voice(self) -> None:
        """Toggle wake word listening on/off (click handler for mic region).

        Uses pause/resume (not stop/start) so the detector stays alive
        and the voice orchestrator's reference remains valid.
        When toggling off, also cancels any active voice pipeline.
        """
        if not self.wake_word_service:
            return
        if self.wake_word_service.is_running:
            # Cancel active voice pipeline before pausing detection
            if self.voice_orchestrator:
                self.voice_orchestrator.cancel()
            self.wake_word_service.pause()
            self.state.update("mic", {"visible": True, "enabled": False, "style": "bracket"})
            print("[Daemon] Voice disabled (mic toggled off)", flush=True)
        else:
            self.wake_word_service.resume()
            self.state.update("mic", {"visible": True, "enabled": True, "style": "bracket"})
            print("[Daemon] Voice enabled (mic toggled on)", flush=True)

    def _on_wake_word_detected(self) -> None:
        """Handle wake word detection -- trigger voice command pipeline.

        Called from nanobuddy's detector thread, NOT the asyncio event loop.
        """
        print("[Daemon] Wake word detected", flush=True)

        if self.voice_orchestrator and self._event_loop:
            future = asyncio.run_coroutine_threadsafe(
                self.voice_orchestrator.on_wake_word(),
                self._event_loop,
            )

            def _on_done(f):
                exc = f.exception()
                if exc:
                    import traceback

                    print(f"[Daemon] on_wake_word failed: {exc}", flush=True)
                    traceback.print_exception(type(exc), exc, exc.__traceback__)

            future.add_done_callback(_on_done)
            return

        # Fallback when voice pipeline is not initialized: brief activation flash.
        self.display.set_status("activated")

        def revert_after_delay() -> None:
            time.sleep(2.0)
            current = self.state.get("status")
            current_status = current.get("status", "idle") if current else "idle"
            if current_status == "activated":
                self.display.set_status("awaiting")

        threading.Thread(target=revert_after_delay, daemon=True).start()

    # --- Timer notifications ---

    def _on_timer_fired(self, signal: str, *, name: str, label: str, trigger: str, **kw) -> None:
        """Handle timer:fired signal — dispatch based on trigger type."""
        if trigger == "voice":
            self._timer_voice(name, label)
        else:
            self._timer_simple(name, label)

    def _timer_simple(self, name: str, label: str) -> None:
        """Flash the widget to 'activated' and play a notification sound."""
        self.display.set_status("activated")

        def _revert() -> None:
            current = self.state.get("status")
            current_status = current.get("status", "idle") if current else "idle"
            if current_status == "activated":
                self.display.set_status("idle")

        self._event_loop.call_later(2.0, _revert)

        async def _play_sound() -> None:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "afplay",
                    "/System/Library/Sounds/Glass.aiff",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            except Exception:
                pass

        self._event_loop.create_task(_play_sound())

    def _timer_voice(self, name: str, label: str) -> None:
        """Wake the voice assistant to announce a fired timer."""
        if not self.voice_orchestrator:
            self._timer_simple(name, label)
            return

        display_name = label or name
        prompt = f"Timer '{display_name}' just fired."
        if label and label != name:
            prompt = f"Timer '{name}' just fired. Label: {label}"
        self._event_loop.create_task(self.voice_orchestrator.notify(prompt))

    # --- Lifecycle ---

    def start(self) -> None:
        """Start the daemon."""
        if self.running:
            return

        self.running = True

        # IPC command server
        self.commands.register_all()
        self.command_server.register("hook_event", self._handle_hook_event)
        self.command_server.start()

        # Widget socket server
        self.socket_server.start()
        self.socket_server.on_message(self._handle_widget_message)
        self.socket_server.on_connect(self.click_manager.push_regions)

        # Token usage service (optional — requires anthropic)
        config = get_config()
        if config.token_usage.enabled:
            try:
                from .services.token_usage import TokenUsageService

                self.token_usage_service = TokenUsageService(poll_interval=config.token_usage.poll_interval)
                self.token_usage_service.start()
            except ImportError:
                logger.info("requests not installed — token usage disabled")

        # Wake word service (optional — requires nanobuddy)
        if config.wake_word.enabled:
            try:
                from .services.wake_word import WakeWordService

                self.wake_word_service = WakeWordService(
                    state_store=self.state,
                    config=config.wake_word,
                    on_detected=self._on_wake_word_detected,
                )
                ww = config.wake_word
                print(f"[Daemon] Starting wake word: model={ww.model} threshold={ww.threshold}", flush=True)
                self.wake_word_service.start()
            except ImportError:
                logger.info("nanobuddy not installed — wake word disabled")

        # Display rendering
        self.display.start(self._get_display_state, state_store=self.state)

        # Initial data refresh (blocking, runs once before Scheduler takes over)
        self.refresh.refresh_all()

    def _start_scheduler(self) -> None:
        """Set up and start the unified Scheduler on the event loop.

        Called from run() after the event loop is captured.
        """
        self.scheduler = Scheduler(self._event_loop)

        # Periodic data refresh (blocking HTTP I/O → executor)
        self.scheduler.register(
            "refresh",
            self.refresh.refresh_all,
            active_interval=self.refresh_interval,
            idle_interval=300,
            blocking=True,
        )

        # Staleness check (cheap, inline)
        self.scheduler.register(
            "staleness",
            self._check_staleness,
            active_interval=5,
            idle_interval=30,
        )

        # Health check — restart display thread if died (cheap, inline)
        self.scheduler.register(
            "health",
            self._check_health,
            active_interval=10,
            idle_interval=30,
        )

        # Thinking feed — poll transcript files for new thinking blocks
        from .services.thinking_feed import get_session_manager

        session_mgr = get_session_manager()
        self.scheduler.register(
            "thinking_feed",
            session_mgr.poll_sessions,
            active_interval=5,
            idle_interval=30,
            blocking=True,
        )

        # FPS adjustment on mode change
        self.scheduler.on_mode_change(self._on_mode_change)

        # Timer service
        self.bus = SignalBus(self._event_loop)
        self.timer_service = TimerService(
            bus=self.bus,
            loop=self._event_loop,
        )
        self.timer_service.start()
        self.bus.on("timer:fired", self._on_timer_fired)

        self.scheduler.start()

    def stop(self) -> None:
        """Stop the daemon."""
        if not self.running:
            return

        self.running = False
        # Kill any in-flight TTS immediately
        if self.voice_orchestrator:
            self.voice_orchestrator._kill_tts()
        # Shut down voice agent — needs the event loop still running
        if self.voice_agent and self._event_loop:
            future = asyncio.run_coroutine_threadsafe(self.voice_agent.shutdown(), self._event_loop)
            try:
                future.result(timeout=5.0)
            except Exception:
                pass  # Best-effort — daemon is exiting anyway

        if self.timer_service:
            self.timer_service.stop()

        if self.scheduler:
            self.scheduler.stop()

        self.display.stop()
        self.socket_server.stop()
        self.command_server.stop()

        if self.token_usage_service:
            self.token_usage_service.stop()

        if self.wake_word_service:
            self.wake_word_service.stop()

        # Stop embedded MCP server
        if self._mcp_task:
            self._mcp_task.cancel()

        # Stop memory service
        if self.memory_service and self.memory_service._ready and self._event_loop:
            try:
                future = asyncio.run_coroutine_threadsafe(self.memory_service.stop(), self._event_loop)
                future.result(timeout=5.0)
            except Exception:
                pass  # Best-effort — daemon is exiting anyway

    async def run(self) -> None:
        """Run the daemon until interrupted."""
        self._event_loop = asyncio.get_running_loop()
        self.start()
        self._start_scheduler()
        self._init_voice_pipeline()

        # Start memory service (fire-and-forget)
        config = get_config()
        if self.memory_service is not None and config.memory.enabled:
            asyncio.create_task(self.memory_service._safe_start(config.memory.to_dict()))

        # Start embedded MCP servers (standard + memory-enabled)
        from .server import run_embedded

        self._mcp_task = asyncio.create_task(run_embedded(self, port=7777, memory_port=7778))
        print("[Daemon] MCP :7777 (standard) :7778 (memory)", flush=True)

        try:
            # Event-driven — sleep indefinitely, all work happens via
            # callbacks (scheduler timers, IPC handlers).
            while self.running:
                await asyncio.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()


def main():
    """Entry point for daemon mode."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(name)s %(levelname)s: %(message)s")
    global _daemon_lock

    if len(sys.argv) > 1 and sys.argv[1] == "--refresh":
        daemon = CentralHubDaemon()
        daemon.refresh.refresh_all()
    else:
        _daemon_lock = PidLock()
        if not _daemon_lock.acquire():
            sys.exit(1)

        try:
            daemon = CentralHubDaemon()
            asyncio.run(daemon.run())
        finally:
            _daemon_lock.release()


if __name__ == "__main__":
    main()
