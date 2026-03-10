#!/usr/bin/env python3
"""Background daemon for Clarvis - handles status processing and data refreshes.

CentralHubDaemon is the orchestration layer that wires together:
- HookProcessor: translates Claude Code hook events into semantic statuses
- CommandHandlers: IPC request handlers for daemon commands
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

from .core.commands import CommandHandlers
from .core.context import AppContext
from .core.ipc import DaemonServer
from .core.paths import STAGING_DIGESTED, STAGING_INBOX
from .core.persistence import json_load_safe
from .core.scheduler import Scheduler
from .core.signals import SignalBus
from .core.state import StateStore, get_state_store
from .display.click_regions import ClickRegion, ClickRegionManager
from .display.config import CONFIG_PATH, get_config
from .display.display_manager import DisplayManager
from .display.refresh_manager import RefreshManager
from .display.socket_server import WidgetSocketServer, get_socket_server
from .display.sprites.system import MicControl
from .hooks.hook_processor import HookProcessor
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
    - CommandHandlers: IPC request handlers for daemon commands
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
        self.voice_orchestrator = None
        self.channel_manager = None
        self._chat_bridge = None
        self._owned_services: list = []  # services with no other refs (prevent GC)

        # Deferred — initialized in run()
        self.memory = None
        self.document_watcher = None
        self.display: DisplayManager | None = None
        self.socket_server: WidgetSocketServer | None = socket_server
        self.click_manager = None
        self.refresh: RefreshManager | None = None
        self.hook_processor: HookProcessor | None = None
        self.commands = None

        self.ctx: AppContext | None = None
        self._staleness_handle: asyncio.TimerHandle | None = None
        self.scheduler: Scheduler | None = None
        self.timer_service: TimerService | None = None
        self.bus: SignalBus | None = None

        self.running = False
        self._stopped = False
        self._shutdown_event: asyncio.Event | None = None

    def _init_memory(self) -> None:
        """Initialize memory backend (MemoryStore + DocumentWatcher)."""
        config = get_config()
        if not config.memory.enabled:
            return

        try:
            from .memory.store import MemoryStore

            h_cfg = config.memory.hindsight
            c_cfg = config.memory.cognee
            self.memory = MemoryStore(
                db_url=h_cfg.db_url,
                banks={name: {"visibility": dc.visibility} for name, dc in h_cfg.banks.items()},
                llm_provider=h_cfg.llm_provider,
                llm_model=h_cfg.llm_model,
                llm_api_key=h_cfg.llm_api_key,
                kg_db_host=c_cfg.db_host,
                kg_db_port=c_cfg.db_port,
                kg_db_name=c_cfg.db_name,
                kg_db_username=c_cfg.db_username,
                kg_db_password=c_cfg.db_password,
                kg_graph_path=c_cfg.graph_path,
                kg_llm_provider=c_cfg.llm_provider,
                kg_llm_model=c_cfg.llm_model,
                kg_llm_api_key=c_cfg.llm_api_key,
            )
        except ImportError:
            logger.info("memory deps not installed — memory disabled")

        if self.memory is not None:
            try:
                from .memory.document_watcher import DocumentWatcher

                d_cfg = config.memory.documents
                self.document_watcher = DocumentWatcher(
                    watch_dir=Path(d_cfg.watch_dir),
                    memory=self.memory,
                    hash_store_path=Path(d_cfg.hash_store_path),
                    poll_interval=d_cfg.poll_interval,
                )
            except ImportError:
                logger.info("document watcher deps not installed")

    def _init_display(self) -> None:
        """Initialize display pipeline (scene, socket server, display manager)."""
        from .display.cv.builder import SceneBuilder
        from .display.cv.registry import CvRegistry

        config = get_config()
        elements_dir = Path(__file__).parent / "display" / "elements"
        cv_registry = CvRegistry(elements_dir)
        cv_registry.load()
        scene = SceneBuilder.build(
            cv_registry,
            scene_name="default",
            width=config.display.grid_width,
            height=config.display.grid_height,
        )
        self.socket_server = self.socket_server or get_socket_server()
        self.click_manager = ClickRegionManager(self.socket_server)
        self.display = DisplayManager(
            scene=scene,
            socket_server=self.socket_server,
            fps=self.display_fps,
        )

        # Refresh manager (passive — Scheduler drives it)
        self.refresh = RefreshManager(state=self.state)

        # Hook processor (event classification, staleness, context)
        self.hook_processor = HookProcessor(
            state=self.state,
            session_tracker=self.session_tracker,
        )

    # --- Hook event processing (delegated to HookProcessor) ---

    def process_hook_event(self, raw_data: dict) -> dict:
        """Process raw hook event into status/color based on tool_name."""
        return self.hook_processor.process_hook_event(raw_data)

    def _handle_hook_event(self, **raw_data) -> dict:
        """Process a hook event received via IPC (replaces file-based watcher)."""
        tp = raw_data.get("transcript_path")
        processed = self.process_hook_event(raw_data)

        # Only update StateStore status for the displayed session (DisplayManager reads from it)
        if processed.get("session_id") == self.session_tracker.displayed_id:
            self.state.update("status", processed)

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
            self.state.update("status", {"status": "idle"})
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

    def _get_display_state(self) -> str:
        """Get current display status for rendering.

        In testing mode, writes fixed values to StateStore so DisplayManager
        picks them up via _build_tick_context().
        """
        config = self.ctx.config

        if config.testing.enabled:
            self.state.update("status", {"status": config.testing.status})
            self.state.update(
                "weather",
                {
                    "widget_type": config.testing.weather,
                    "widget_intensity": config.testing.weather_intensity,
                    "wind_speed": config.testing.wind_speed,
                },
            )
            return config.testing.status

        status = self.state.get("status")
        return status.get("status", "idle") if status else "idle"

    # --- Service getters for ctools ---

    def _get_spotify_session(self):
        """Lazy SpotifySession getter."""
        try:
            from .services.spotify_session import get_spotify_session

            return get_spotify_session()
        except Exception:
            return None

    # --- Voice pipeline ---

    def _init_agents(self) -> None:
        """Create the Clarvis agent with ContextInjector.

        Called from run() after AppContext is set.  The Clarvis agent
        serves voice, ``clarvis chat``, and nudge.  Factoria gets a
        shared agent in ``_init_channel_manager()``.
        """
        if self.ctx is None:
            return

        config = self.ctx.config
        # Read channels config early — needed by _init_channel_manager
        raw_config = json_load_safe(CONFIG_PATH) or {}
        self._channels_config = raw_config.get("channels") or {}

        # Clarvis agent — always created (serves voice, terminal chat, wakeup)
        from .agent.context import ContextInjector
        from .agent.factory import create_clarvis_agent

        agent = create_clarvis_agent(model=config.clarvis.model, thinking=config.clarvis.thinking)
        agent.context = ContextInjector(
            state=self.state,
            memory=self.memory,
            visibility="master",
            include_ambient=True,
        )
        self._agents["clarvis"] = agent

    def _init_voice_pipeline(self) -> None:
        """Initialize voice orchestrator with the captured event loop.

        Called from run() after AppContext and Clarvis agent are set.
        The Clarvis agent is already a self-contained Agent created in
        ``_init_agents()``.
        """
        config = self.ctx.config
        needs_voice = (
            config.voice.wake_word.enabled
            and config.voice.enabled
            and self.wake_word_service is not None
            and self._agents.get("clarvis") is not None
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
            agent=self._agents["clarvis"],
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
        # Orchestrator now self-subscribes to wake_word signals via bus;
        # remove the daemon fallback so both don't fire.
        if self.bus:
            self.bus.off("wake_word:detected", self._fallback_wake_word)

        # Register mic toggle region
        self._register_mic_region()
        logger.info("Voice command pipeline initialized")

    async def _init_channel_manager(self) -> None:
        """Initialize online channels with a single shared Factoria agent.

        All online channels (Discord, Telegram, etc.) share one agent at
        ``~/.clarvis/factoria/`` with serialized access.  The Clarvis agent
        is set up separately in ``_init_agents()``.
        """
        channels_config = getattr(self, "_channels_config", None) or {}
        if not any(ch.get("enabled") for ch in channels_config.values() if isinstance(ch, dict)):
            return

        config = self.ctx.config

        try:
            from .agent.context import ContextInjector
            from .agent.factory import create_factoria_agent
            from .channels.manager import ChannelManager
            from .channels.registry import UserRegistry
            from .channels.state import ChannelState

            # Factoria agent for all online channels
            factoria_agent = create_factoria_agent(
                model=config.channels.model or config.clarvis.model,
            )
            factoria_agent.context = ContextInjector(
                state=self.state,
                memory=self.memory,
                visibility="all",
                include_ambient=False,
            )
            self._agents["factoria"] = factoria_agent

            registry = UserRegistry(admin_user_ids=config.channels.admin_user_ids)
            state = ChannelState()

            self.channel_manager = ChannelManager(
                agent=factoria_agent,
                channels_config=channels_config,
                registry=registry,
                state=state,
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
        self.state.update("status", {"status": "activated"}, force=True)

        def _revert() -> None:
            current = self.state.get("status")
            current_status = current.get("status", "idle") if current else "idle"
            if current_status == "activated":
                self.state.update("status", {"status": "idle"}, force=True)

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

        # Memory backend (start — heavy imports run in executor)
        if self.memory is not None:
            try:
                await self.memory.start()
                logger.info("MemoryStore started (facts=%s, kg=%s)", self.memory.facts_ready, self.memory.kg_ready)
            except Exception:
                logger.exception("Failed to start MemoryStore")
                self.memory = None

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
                voice_orchestrator_provider=lambda: self.voice_orchestrator,
            )
        )

        self.scheduler.start()

    async def stop(self) -> None:
        """Stop the daemon."""
        if self._stopped:
            return

        self._stopped = True
        self.running = False
        # Stop ChatBridge
        if self._chat_bridge:
            self._chat_bridge.stop()
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

        # Stop memory backends
        if self.document_watcher is not None:
            try:
                await asyncio.wait_for(self.document_watcher.stop(), timeout=5.0)
            except Exception:
                pass

        if self.memory is not None and self.memory.ready:
            try:
                await asyncio.wait_for(self.memory.stop(), timeout=5.0)
            except Exception:
                pass

    async def reset_all_agents(self) -> None:
        """Reset all agent sessions in parallel."""
        results = await asyncio.gather(
            *(agent.reset() for agent in self._agents.values()),
            return_exceptions=True,
        )
        for name, result in zip(self._agents, results):
            if isinstance(result, Exception):
                logger.warning("Failed to reset agent %s: %s", name, result, exc_info=True)
            else:
                logger.info("Reset agent session: %s", name)

    async def complete_reflect(self) -> dict:
        """Finalize reflect: move inbox → digested, then reset agents."""
        if STAGING_INBOX.is_dir():
            STAGING_DIGESTED.mkdir(parents=True, exist_ok=True)
            for f in STAGING_INBOX.glob("*"):
                if f.is_file():
                    f.rename(STAGING_DIGESTED / f.name)
        await self.reset_all_agents()
        return {"status": "reflect complete"}

    async def run(self) -> None:
        """Run the daemon until interrupted."""
        # Initialize memory before AppContext (frozen dataclass)
        self._init_memory()

        loop = asyncio.get_running_loop()
        self.bus = SignalBus(loop)
        self.ctx = AppContext(
            loop=loop,
            bus=self.bus,
            state=self.state,
            config=get_config(),
            memory=self.memory,
        )
        self._shutdown_event = asyncio.Event()

        # Initialize display pipeline (scene, socket, rendering)
        self._init_display()

        self.commands = CommandHandlers(
            ctx=self.ctx,
            session_tracker=self.session_tracker,
            refresh=self.refresh,
            command_server=self.command_server,
            services={
                "voice": lambda: self.voice_orchestrator,
                "memory": lambda: self.memory,
                "agents": lambda: self._agents,
                "spotify_session": lambda: self._get_spotify_session(),
                "timer_service": lambda: self.timer_service,
                "channel_manager": lambda: self.channel_manager,
                "daemon": lambda: self,
            },
        )

        logger.info("Starting daemon services…")
        await self.start()
        logger.info("Daemon services started")
        self._start_scheduler()

        self._init_agents()
        self._init_voice_pipeline()

        # ChatBridge — streaming socket for `clarvis chat` TUI
        if self._agents:
            from .chat.bridge import ChatBridge

            self._chat_bridge = ChatBridge(
                agents=self._agents,
                state=self.state,
                loop=self.ctx.loop,
                user_name=self.ctx.config.user_name,
            )
            self._chat_bridge.start()

        # Wire timer:fired → nudge for wake_clarvis timers
        clarvis_agent = self._agents.get("clarvis")
        if clarvis_agent:
            from .services.wakeup import nudge

            self.bus.on(
                "timer:fired",
                lambda sig, *, wake_clarvis=False, name="", label="", **kw: (
                    asyncio.create_task(nudge(clarvis_agent, "timer", timer_name=name, timer_label=label))
                    if wake_clarvis
                    else None
                ),
            )
        # Start channel manager (chat channels, gated behind channels extra)
        await self._init_channel_manager()

        # Eager-connect agents
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

        # Warm up Spotify session in background (player init + device discovery)
        async def _warm_spotify():
            try:
                await self.ctx.loop.run_in_executor(None, self._get_spotify_session)
                session = self._get_spotify_session()
                if session:
                    await self.ctx.loop.run_in_executor(None, session.run, "status")
                    logger.info("Spotify session warmed up")
            except Exception as e:
                logger.debug("Spotify warm-up skipped: %s", e)

        asyncio.create_task(_warm_spotify())

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
        refresh = RefreshManager(state=get_state_store())
        refresh.refresh_all()
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
