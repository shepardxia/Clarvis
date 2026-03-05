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

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from filelock import FileLock, Timeout

from .core.command_handlers import CommandHandlers
from .core.context import AppContext
from .core.ipc import DaemonServer
from .core.persistence import json_load_safe
from .core.scheduler import Scheduler
from .core.signals import SignalBus
from .core.state import StateStore, get_state_store
from .display.click_regions import ClickRegion, ClickRegionManager
from .display.config import CONFIG_PATH, get_config
from .display.display_manager import DisplayManager
from .display.refresh_manager import RefreshManager
from .display.socket_server import WidgetSocketServer, get_socket_server
from .display.sprites.system import MicControl, build_default_scene
from .hooks.hook_processor import HookProcessor
from .services.context_accumulator import ContextAccumulator
from .services.session_tracker import SessionTracker
from .services.timer_service import TimerService

logger = logging.getLogger(__name__)

STALENESS_TIMEOUT_SECONDS = 30


class PidLock:
    """Ensures only one daemon instance runs at a time using filelock."""

    DEFAULT_PID_FILE = Path("/tmp/clarvis-daemon.pid")

    def __init__(self, pid_file: Path = None):
        self.pid_file = pid_file or self.DEFAULT_PID_FILE
        self._lock = FileLock(str(self.pid_file) + ".lock")

    def acquire(self) -> bool:
        """Attempt to acquire the daemon lock.

        Returns:
            True if lock acquired, False if another instance is running.
        """
        try:
            self._lock.acquire(timeout=0)
            self.pid_file.write_text(f"{os.getpid()}\n")
            return True
        except Timeout:
            try:
                pid = self.pid_file.read_text().strip()
                logger.error("Daemon already running (PID %s)", pid)
            except Exception:
                logger.error("Daemon already running")
            return False

    def release(self) -> None:
        """Release the daemon lock and clean up."""
        try:
            self.pid_file.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            self._lock.release()
        except Exception:
            pass

    def __enter__(self) -> "PidLock":
        if not self.acquire():
            raise RuntimeError("Failed to acquire daemon lock")
        return self

    def __exit__(self, *args) -> None:
        self.release()


# Global lock instance for daemon
_daemon_lock: PidLock | None = None


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
        self.wake_word_service = None
        self._agents = {}  # str -> Agent, populated by _init_agents / _init_channel_manager
        self._force_new = False  # Set from CLARVIS_NEW_CONVERSATION env var
        self.voice_agent = None
        self.voice_orchestrator = None
        self.channel_manager = None
        self.context_accumulator = None
        self.memory_maintenance = None
        self._wakeup_manager = None
        self._owned_services: list = []  # services with no other refs (prevent GC)

        # Memory backends (optional — requires hindsight + cognee)
        self.hindsight_store = None  # HindsightStore (Level 2 interface)
        self.hindsight_backend = None  # Compat alias — points to hindsight_store
        self.memory_store = None  # Compat alias — used by mcp/memory_tools.py
        self.cognee_backend = None
        self.document_watcher = None
        self.transcript_reader = None
        if config.memory.enabled:
            try:
                from .memory.store import HindsightStore

                h_cfg = config.memory.hindsight
                self.hindsight_store = HindsightStore(
                    db_url=h_cfg.db_url,
                    banks={name: {"visibility": dc.visibility} for name, dc in h_cfg.banks.items()},
                )
                self.hindsight_backend = self.hindsight_store  # Compat alias for mcp/server.py
                self.memory_store = self.hindsight_store  # Compat alias for mcp/memory_tools.py
            except ImportError:
                logger.info("hindsight not installed — conversational memory disabled")

            try:
                from .agent.memory.cognee_backend import CogneeBackend

                c_cfg = config.memory.cognee
                self.cognee_backend = CogneeBackend(
                    db_host=c_cfg.db_host,
                    db_port=c_cfg.db_port,
                    db_name=c_cfg.db_name,
                    db_username=c_cfg.db_username,
                    db_password=c_cfg.db_password,
                    graph_path=c_cfg.graph_path,
                    llm_provider=c_cfg.llm_provider,
                    llm_model=c_cfg.llm_model,
                    llm_api_key=c_cfg.llm_api_key,
                )
            except ImportError:
                logger.info("cognee not installed — knowledge graph disabled")

            # TranscriptReader — reads session transcripts on demand for retain
            try:
                from .agent.memory.transcript_reader import TranscriptReader

                data_dir = Path(config.memory.data_dir).expanduser()
                self.transcript_reader = TranscriptReader(
                    watermark_path=data_dir / "session_watcher_state.json",
                )
            except ImportError:
                pass

            if self.cognee_backend is not None:
                try:
                    from .agent.memory.document_watcher import DocumentWatcher

                    d_cfg = config.memory.documents
                    self.document_watcher = DocumentWatcher(
                        watch_dir=Path(d_cfg.watch_dir),
                        cognee_backend=self.cognee_backend,
                        hash_store_path=Path(d_cfg.hash_store_path),
                        poll_interval=d_cfg.poll_interval,
                    )
                except ImportError:
                    logger.info("document_watcher deps not available")
        # Home project slug — only stage sessions from this project.
        # Encode path the same way Claude Code names its projects/ dirs:
        # replace "." → "-", then "/" → "-".
        _home_path = str(Path.home() / ".clarvis" / "home")
        self._home_slug = _home_path.replace(".", "-").replace("/", "-")
        self.ctx: AppContext | None = None
        self._mcp_task: asyncio.Task | None = None
        self._staleness_handle: asyncio.TimerHandle | None = None
        self.scheduler: Scheduler | None = None
        self.timer_service: TimerService | None = None
        self.bus: SignalBus | None = None

        self.running = False
        self._stopped = False
        self._shutdown_event: asyncio.Event | None = None

        # Display manager with sprite scene
        scene = build_default_scene(
            width=config.display.grid_width,
            height=config.display.grid_height,
            avatar_x_offset=config.display.avatar_x_offset,
            avatar_y_offset=config.display.avatar_y_offset,
            bar_x_offset=config.display.bar_x_offset,
            bar_y_offset=config.display.bar_y_offset,
            mic_x_offset=config.display.mic_x_offset,
            mic_y_offset=config.display.mic_y_offset,
        )
        self.socket_server = socket_server or get_socket_server()
        self.click_manager = ClickRegionManager(self.socket_server)
        self.display = DisplayManager(
            scene=scene,
            socket_server=self.socket_server,
            fps=self.display_fps,
        )

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
        # CommandHandlers created in run() after AppContext is available
        self.commands = None

    # --- Hook event processing (delegated to HookProcessor) ---

    def process_hook_event(self, raw_data: dict) -> dict:
        """Process raw hook event into status/color based on tool_name."""
        return self.hook_processor.process_hook_event(raw_data)

    def _handle_hook_event(self, **raw_data) -> dict:
        """Process a hook event received via IPC (replaces file-based watcher)."""
        tp = raw_data.get("transcript_path")
        processed = self.process_hook_event(raw_data)
        self.state.update("status", processed)

        if processed.get("session_id") == self.session_tracker.displayed_id and not self.state.status_locked:
            self.display.set_status(processed.get("status", "idle"))

        event = raw_data.get("hook_event_name")
        self.session_tracker.cleanup_stale()

        if event and event != "Stop":
            self._reset_staleness_timer()

        # Enriched signal — services self-subscribe for side effects
        if self.bus:
            session_id = raw_data.get("session_id", "unknown")
            self.bus.emit(
                "hook:event",
                event_name=event,
                session_id=session_id,
                transcript_path=tp,  # may be None
            )

    # --- Staleness timer (signal-driven, replaces polling) ---

    def _reset_staleness_timer(self) -> None:
        """Reset the 30s staleness timer. Called from IPC thread on each hook event."""
        if not self.ctx:
            return

        def _reset():
            if self._staleness_handle is not None:
                self._staleness_handle.cancel()
            self._staleness_handle = self.ctx.loop.call_later(STALENESS_TIMEOUT_SECONDS, self._go_stale)

        self.ctx.loop.call_soon_threadsafe(_reset)

    def _go_stale(self) -> None:
        """Fire once after 30s of silence — reset status to idle."""
        stale_reset = self.hook_processor.check_status_staleness(STALENESS_TIMEOUT_SECONDS)
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
            self.display.wake()
            self.display.set_fps(self.display_fps)
        else:
            self.display.set_fps(1)
            mic = self.state.get("mic") or {}
            if not mic.get("enabled"):
                self.display.freeze()

    # --- Display state ---

    def _get_display_state(self) -> tuple[str, float]:
        """Get current display state for rendering.

        Returns:
            Tuple of (status, context_percent)
        """
        config = self.ctx.config

        if config.testing.enabled:
            self.display.set_status(config.testing.status)
            self.display.set_weather(
                config.testing.weather, config.testing.weather_intensity, config.testing.wind_speed
            )
            return config.testing.status, config.testing.context_percent

        status = self.state.get("status")
        context_percent = status.get("context_percent", 0) if status else 0
        display_status = status.get("status", "idle") if status else "idle"
        return display_status, context_percent

    # --- Voice pipeline ---

    def _init_agents(self) -> None:
        """Create the master (voice/terminal) Agent.

        Called from run() after AppContext is set.  The master agent
        serves voice and ``clarvis chat``.  Online channels get a shared
        agent in ``_init_channel_manager()``.
        """
        if self.ctx is None:
            return

        config = self.ctx.config
        self._force_new = bool(os.environ.pop("CLARVIS_NEW_CONVERSATION", None))

        # Read channels config early — needed by both voice gate and _init_channel_manager
        raw_config = json_load_safe(CONFIG_PATH) or {}
        self._channels_config = raw_config.get("channels") or {}
        has_channels = any(ch.get("enabled") for ch in self._channels_config.values() if isinstance(ch, dict))

        if not config.voice.enabled and not has_channels:
            return

        # Main Clarvis agent — shared by voice and terminal chat
        if config.voice.enabled:
            from .channels.agent_factory import create_master_agent

            agent = create_master_agent(
                event_loop=self.ctx.loop,
                model=config.voice.model,
                max_thinking_tokens=config.voice.max_thinking_tokens,
                force_new=self._force_new,
                mcp_port=config.mcp.home_port,
            )
            self._agents["voice"] = agent
            self.voice_agent = agent

    def _init_voice_pipeline(self) -> None:
        """Initialize voice orchestrator with the captured event loop.

        Called from run() after AppContext and voice agent are set.
        The voice agent is already a self-contained Agent created in
        ``_init_agents()``.
        """
        config = self.ctx.config
        needs_voice = (
            config.voice.wake_word.enabled
            and config.voice.enabled
            and self.wake_word_service is not None
            and self.voice_agent is not None
        )
        if not needs_voice:
            return

        from .channels.voice.asr import WidgetASRBackend
        from .channels.voice.orchestrator import VoiceCommandOrchestrator

        asr_backend = WidgetASRBackend(
            event_loop=self.ctx.loop,
            socket_server=self.socket_server,
        )

        self.voice_orchestrator = VoiceCommandOrchestrator(
            event_loop=self.ctx.loop,
            socket_server=self.socket_server,
            voice_agent=self.voice_agent,
            state_store=self.state,
            wake_word_service=self.wake_word_service,
            asr_backend=asr_backend,
            bus=self.bus,
            tts_voice=config.voice.tts_voice,
            tts_speed=config.voice.tts_speed,
            tts_enabled=config.voice.tts_enabled,
            asr_timeout=config.voice.asr_timeout,
            asr_language=config.voice.asr_language,
            silence_timeout=config.voice.silence_timeout,
            text_linger=config.voice.text_linger,
        )
        self.voice_orchestrator.memory_service = self.hindsight_store
        # Orchestrator now self-subscribes to wake_word signals via bus;
        # remove the daemon fallback so both don't fire.
        if self.bus:
            self.bus.off("wake_word:detected", self._fallback_wake_word)

        # Register mic toggle region
        self._register_mic_region()
        logger.info("Voice command pipeline initialized")

    def _init_wakeup(self) -> None:
        """Wire WakeupManager for autonomous context-rich prompts.

        Only active when backend is 'pi' and wakeup is enabled.
        Called from run() after agents are created.
        """
        config = self.ctx.config
        if config.channels.agent_backend != "pi":
            return
        if not config.channels.wakeup.enabled:
            return

        voice_agent = self._agents.get("voice")
        if not voice_agent:
            return

        from .services.wakeup import WakeupManager

        # Lazy Spotify session getter (same as MCP tools use)
        def _get_spotify_session():
            try:
                from .mcp.spotify_tools import _default_get_session

                return _default_get_session()
            except Exception:
                return None

        self._wakeup_manager = WakeupManager(
            agent=voice_agent,
            state_store=self.state,
            memory_service=self.hindsight_store,
            get_spotify_session=_get_spotify_session,
        )

        # Register pulse wakeup with scheduler
        pulse_secs = config.channels.wakeup.pulse_interval_minutes * 60
        self.scheduler.register(
            "wakeup_pulse",
            lambda: asyncio.create_task(self._wakeup_manager.on_pulse()),
            active_interval=pulse_secs,
            idle_interval=pulse_secs * 2,
        )

        # Subscribe to timer:fired for wake_clarvis timers
        self.bus.on(
            "timer:fired", lambda sig, **kw: asyncio.create_task(self._wakeup_manager.on_timer_fired(sig, **kw))
        )

        logger.info(
            "WakeupManager active (pulse=%dm)",
            config.channels.wakeup.pulse_interval_minutes,
        )

    async def _init_channel_manager(self) -> None:
        """Initialize online channels with a single shared agent.

        All online channels (Discord, Telegram, etc.) share one agent at
        ``~/.clarvis/channels/`` with serialized access.  The master agent
        (voice + terminal) is set up separately in ``_init_agents()``.
        """
        channels_config = getattr(self, "_channels_config", None) or {}
        if not any(ch.get("enabled") for ch in channels_config.values() if isinstance(ch, dict)):
            return

        config = self.ctx.config

        try:
            from .channels.agent_factory import create_channel_agent
            from .channels.manager import ChannelManager
            from .channels.registry import UserRegistry
            from .channels.state import ChannelState
            from .mcp.server import CHANNEL_DEFAULTS

            # Determine MCP port and tools config for shared channel agent
            # Merge order: CHANNEL_DEFAULTS ← channels.tools ← per-channel tools
            tools_cfg = dict(CHANNEL_DEFAULTS)
            if config.channels.tools:
                tools_cfg.update(config.channels.tools)
            for ch_cfg in channels_config.values():
                if not isinstance(ch_cfg, dict):
                    continue
                if ch_cfg.get("enabled"):
                    tools_cfg.update(ch_cfg.get("tools", {}))
            ch_port = config.mcp.channel_port
            self._channel_ports = [(tools_cfg, ch_port)]

            # Single shared agent for all online channels
            channel_agent = create_channel_agent(
                event_loop=self.ctx.loop,
                model=config.channels.model or config.voice.model,
                max_thinking_tokens=config.channels.max_thinking_tokens or config.voice.max_thinking_tokens,
                force_new=self._force_new,
                mcp_port=ch_port,
            )
            self._agents["channels"] = channel_agent

            registry = UserRegistry(admin_user_ids=config.channels.admin_user_ids)
            state = ChannelState()

            self.channel_manager = ChannelManager(
                agent=channel_agent,
                channels_config=channels_config,
                registry=registry,
                state=state,
                memory_service=self.hindsight_store,
            )
            await self.channel_manager.start()

            # Bind voice channel to orchestrator for outbound TTS
            if self.voice_orchestrator and self.channel_manager.voice_channel:
                self.channel_manager.voice_channel.set_orchestrator(self.voice_orchestrator)

            enabled = self.channel_manager.enabled_channels
            logger.info("Channels: %s", ", ".join(enabled))
        except Exception:
            logger.exception("Failed to start channel service")

    def _handle_widget_message(self, message: dict) -> None:
        """General dispatcher for messages from the widget.

        Routes ``region_click`` to the click manager (on the event loop
        for thread safety), everything else to the voice orchestrator.
        """
        method = message.get("method")
        if method == "region_click":
            region_id = message.get("params", {}).get("id", "")
            if self.ctx:
                self.ctx.loop.call_soon_threadsafe(self.click_manager.handle_click, region_id)
        elif self.voice_orchestrator:
            self.voice_orchestrator.handle_widget_message(message)

    def _register_mic_region(self) -> None:
        """Register the mic-toggle click region and update state."""
        mic_sprites = self.display.scene.registry.by_type(MicControl)
        if mic_sprites:
            row, col, w, h = mic_sprites[0].click_region()
            region = ClickRegion("mic_toggle", row=row, col=col, width=w, height=h)
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
            logger.info("Voice disabled (mic toggled off)")
            # Freeze display if already in idle mode
            if self.scheduler and self.scheduler.mode == "idle":
                self.display.freeze()
        else:
            self.wake_word_service.resume()
            self.state.update("mic", {"visible": True, "enabled": True, "style": "bracket"})
            logger.info("Voice enabled (mic toggled on)")
            # Wake display if frozen
            self.display.wake()

    def _fallback_wake_word(self, signal: str, **kw) -> None:
        """Brief activation flash when voice pipeline is not active."""
        self.display.set_status("activated")

        def _revert() -> None:
            current = self.state.get("status")
            current_status = current.get("status", "idle") if current else "idle"
            if current_status == "activated":
                self.display.set_status("awaiting")

        if self.ctx:
            self.ctx.loop.call_later(2.0, _revert)

    # --- Lifecycle ---

    async def start(self) -> None:
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

        # Memory backends (start — heavy imports run in executor)
        if self.hindsight_store is not None:
            try:
                await self.hindsight_store.start()
                logger.info("HindsightStore started")
            except Exception:
                logger.exception("Failed to start HindsightStore")
                self.hindsight_store = None
                self.hindsight_backend = None  # Keep compat aliases in sync
                self.memory_store = None

        if self.cognee_backend is not None:
            try:
                await self.cognee_backend.start()
                logger.info("CogneeBackend started")
            except Exception:
                logger.exception("Failed to start Cognee backend")
                self.cognee_backend = None

        if self.document_watcher is not None:
            try:
                await self.document_watcher.start()
                logger.info("DocumentWatcher started")
            except Exception:
                logger.exception("Failed to start document watcher")
                self.document_watcher = None

        # Wake word service (optional — requires nanobuddy)
        config = self.ctx.config
        if config.voice.wake_word.enabled:
            try:
                from .services.wake_word import WakeWordService

                self.wake_word_service = WakeWordService(
                    state_store=self.state,
                    config=config.voice.wake_word,
                    bus=self.bus,
                )
                ww = config.voice.wake_word
                logger.info("Starting wake word: model=%s threshold=%s rate=%s", ww.model, ww.threshold, ww.sample_rate)
                self.wake_word_service.start()
                # Fallback wake word handler — brief activation flash when voice
                # pipeline is not initialized.  Overridden by
                # VoiceCommandOrchestrator's own subscription when voice is active.
                self.bus.on("wake_word:detected", self._fallback_wake_word)
            except ImportError:
                logger.info("nanobuddy not installed — wake word disabled")

        # Display rendering
        self.display.start(self._get_display_state, state_store=self.state)

        # Initial data refresh (fire-and-forget — Scheduler retries on 30s cadence)
        self.ctx.loop.run_in_executor(None, self.refresh.refresh_all)

    def _start_scheduler(self) -> None:
        """Set up and start the unified Scheduler on the event loop.

        Called from run() after the event loop is captured.
        """
        self.scheduler = Scheduler(self.ctx)

        # Periodic data refresh (blocking HTTP I/O → executor)
        self.scheduler.register(
            "refresh",
            self.refresh.refresh_all,
            active_interval=self.refresh_interval,
            idle_interval=300,
            blocking=True,
        )

        # Health check — restart display thread if died (cheap, inline)
        self.scheduler.register(
            "health",
            self._check_health,
            active_interval=10,
            idle_interval=30,
        )

        # FPS adjustment on mode change
        self.scheduler.on_mode_change(self._on_mode_change)

        # Timer service
        self.timer_service = TimerService(ctx=self.ctx)
        self.timer_service.start()

        from .services.timer_notifier import TimerNotifier

        self._owned_services.append(
            TimerNotifier(
                ctx=self.ctx,
                display=self.display,
                voice_orchestrator_provider=lambda: self.voice_orchestrator,
            )
        )

        # Memory maintenance — periodic reflect (retains internally)
        if self.memory_maintenance is not None:
            self.scheduler.register(
                "memory_maintenance",
                lambda: asyncio.create_task(self.memory_maintenance.maintenance_tick()),
                active_interval=900,  # 15 min when active
                idle_interval=3600,  # 60 min when idle
            )

        self.scheduler.start()

    async def stop(self) -> None:
        """Stop the daemon."""
        if self._stopped:
            return

        self._stopped = True
        self.running = False
        # Kill any in-flight TTS immediately
        if self.voice_orchestrator:
            self.voice_orchestrator._kill_tts()
        # Shut down all agents — we're inside the event loop, so await directly
        for agent in self._agents.values():
            try:
                await asyncio.wait_for(agent.shutdown(), timeout=5.0)
            except Exception:
                pass  # Best-effort — daemon is exiting anyway
        # Stop channel manager
        if self.channel_manager:
            try:
                await asyncio.wait_for(self.channel_manager.stop(), timeout=5.0)
            except Exception:
                pass

        if self._staleness_handle is not None:
            self._staleness_handle.cancel()
            self._staleness_handle = None

        if self.timer_service:
            self.timer_service.stop()

        if self.scheduler:
            self.scheduler.stop()

        self.display.stop()
        self.socket_server.stop()
        self.command_server.stop()

        if self.wake_word_service:
            self.wake_word_service.stop()

        # Stop embedded MCP server
        if self._mcp_task:
            self._mcp_task.cancel()

        # Stop memory backends
        if self.document_watcher is not None:
            try:
                await asyncio.wait_for(self.document_watcher.stop(), timeout=5.0)
            except Exception:
                pass

        if self.hindsight_store is not None and self.hindsight_store.ready:
            try:
                await asyncio.wait_for(self.hindsight_store.stop(), timeout=5.0)
            except Exception:
                pass

        if self.cognee_backend is not None and self.cognee_backend.ready:
            try:
                await asyncio.wait_for(self.cognee_backend.stop(), timeout=5.0)
            except Exception:
                pass

    async def run(self) -> None:
        """Run the daemon until interrupted."""
        loop = asyncio.get_running_loop()
        self.bus = SignalBus(loop)
        self.ctx = AppContext(
            loop=loop,
            bus=self.bus,
            state=self.state,
            config=get_config(),
        )
        self._shutdown_event = asyncio.Event()

        # Services that need AppContext — create here, before start()
        self.context_accumulator = ContextAccumulator(
            ctx=self.ctx,
            home_slug=self._home_slug,
        )

        # Memory maintenance — automated retain + reflect (requires memory enabled)
        if self.hindsight_store is not None and self.transcript_reader is not None:
            from .channels.agent_factory import create_master_agent
            from .services.memory_maintenance import MemoryMaintenanceService

            self.memory_maintenance = MemoryMaintenanceService(
                ctx=self.ctx,
                store=self.hindsight_store,
                context_accumulator=self.context_accumulator,
                transcript_reader=self.transcript_reader,
                agent_factory=lambda: create_master_agent(event_loop=self.ctx.loop, force_new=True),
            )

        self.commands = CommandHandlers(
            ctx=self.ctx,
            session_tracker=self.session_tracker,
            refresh=self.refresh,
            command_server=self.command_server,
            services={
                "voice": lambda: self.voice_orchestrator,
                "memory": lambda: self.hindsight_store,
                "cognee": lambda: self.cognee_backend,
                "agents": lambda: self._agents,
                "maintenance": lambda: self.memory_maintenance,
            },
        )

        logger.info("Starting daemon services…")
        await self.start()
        logger.info("Daemon services started")
        self._start_scheduler()

        self._init_agents()
        self._init_voice_pipeline()
        self._init_wakeup()

        # Start channel manager (chat channels, gated behind channels extra)
        await self._init_channel_manager()

        # Start embedded MCP servers — must be listening BEFORE eager-connect,
        # otherwise CLI subprocesses hang trying to reach their MCP port.
        from .mcp.server import run_embedded

        channel_ports = getattr(self, "_channel_ports", None)
        voice_tools = self.ctx.config.voice.tools or None
        mcp_ready = asyncio.Event()
        mcp_error: list[BaseException] = []

        def _on_mcp_done(task: asyncio.Task) -> None:
            exc = task.exception() if not task.cancelled() else None
            if exc is not None:
                logger.error("MCP server task crashed: %s: %s", type(exc).__name__, exc)
                mcp_error.append(exc)
                mcp_ready.set()  # unblock the wait

        logger.info("Starting MCP servers…")
        mcp_cfg = self.ctx.config.mcp
        self._mcp_task = asyncio.create_task(
            run_embedded(
                self,
                port=mcp_cfg.standard_port,
                memory_port=mcp_cfg.home_port,
                channel_ports=channel_ports,
                voice_tools_override=voice_tools,
                ready=mcp_ready,
            )
        )
        self._mcp_task.add_done_callback(_on_mcp_done)

        try:
            await asyncio.wait_for(mcp_ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.error("MCP servers failed to bind within 10s — check for port conflicts")
            raise RuntimeError("MCP server startup timed out")

        if mcp_error:
            raise RuntimeError(f"MCP server failed to start: {mcp_error[0]}")

        port_info = f":{mcp_cfg.standard_port} :{mcp_cfg.home_port}"
        for _, cp in channel_ports or []:
            port_info += f" :{cp}"
        logger.info("MCP ports ready: %s", port_info)

        # Eager-connect agents — MCP servers are listening, CLI won't hang
        if self._agents:
            agent_names = list(self._agents.keys())
            logger.info("Connecting agents: %s", ", ".join(agent_names))
            results = await asyncio.gather(
                *(agent.connect_eager() for agent in self._agents.values()),
                return_exceptions=True,
            )
            for name, result in zip(agent_names, results):
                if isinstance(result, Exception):
                    logger.warning("Agent %s eager-connect raised: %s", name, result)
                else:
                    logger.info("Agent %s eager-connect done", name)
            logger.info("All agent connect_eager() calls completed")

        logger.info("Daemon startup complete")
        try:
            await self._shutdown_event.wait()
        except KeyboardInterrupt:
            pass
        finally:
            await self.stop()


def main():
    """Entry point for daemon mode."""
    from .core.env import load_dotenv
    from .core.log import setup_logging

    load_dotenv()  # .env → os.environ before anything reads env vars
    setup_logging(Path("logs"))
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

            def _handle_term(sig: int, frame: object) -> None:
                logger.info("Received signal %s, shutting down…", signal.Signals(sig).name)
                daemon.running = False
                loop = daemon.ctx.loop if daemon.ctx else None
                if loop and daemon._shutdown_event:
                    loop.call_soon_threadsafe(daemon._shutdown_event.set)

            signal.signal(signal.SIGTERM, _handle_term)
            signal.signal(signal.SIGINT, _handle_term)

            asyncio.run(daemon.run())
        finally:
            _daemon_lock.release()


if __name__ == "__main__":
    main()
