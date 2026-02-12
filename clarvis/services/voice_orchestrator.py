"""Voice command orchestrator — coordinates the full voice pipeline.

Wake word -> pause hey-buddy -> ASR (widget) -> Claude agent -> display + TTS.

State machine
─────────────
IDLE → ACTIVATED → LISTENING → THINKING → RESPONDING → COOLDOWN → IDLE

Each _transition() call validates against _TRANSITIONS and auto-updates
the StateStore status, so the display always reflects the pipeline state.

IPC protocol
────────────
Four message types flow between the orchestrator and the Swift widget.
Each is a frozen dataclass with to_message() / from_message() methods
that document the contract and catch field-name typos at the Python
boundary.  Swift keeps dynamic JSON parsing — see the protocol reference
comment in ClarvisWidget/main.swift.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
import uuid
from contextlib import aclosing
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.state import StateStore
    from ..services.voice_agent import VoiceAgent
    from ..services.wake_word import WakeWordService
    from ..widget.socket_server import WidgetSocketServer

logger = logging.getLogger(__name__)

# Maximum time to wait for a Claude agent response before giving up.
AGENT_QUERY_TIMEOUT = 60.0


# ──────────────────────────────────────────────────────────────────────
# Pipeline state machine
# ──────────────────────────────────────────────────────────────────────


class VoicePipelineState(enum.Enum):
    IDLE = "idle"
    ACTIVATED = "activated"
    LISTENING = "listening"
    THINKING = "thinking"
    RESPONDING = "responding"
    COOLDOWN = "cooldown"


# Allowed transitions: state -> set of reachable next states.
_S = VoicePipelineState
_TRANSITIONS: dict[VoicePipelineState, set[VoicePipelineState]] = {
    _S.IDLE: {_S.ACTIVATED},
    _S.ACTIVATED: {_S.LISTENING, _S.THINKING, _S.COOLDOWN},
    _S.LISTENING: {_S.THINKING, _S.COOLDOWN},
    _S.THINKING: {_S.RESPONDING, _S.COOLDOWN},
    _S.RESPONDING: {_S.COOLDOWN, _S.LISTENING, _S.THINKING},
    _S.COOLDOWN: {_S.IDLE},
}

# States that map to a display status in the StateStore.
_STATE_TO_STATUS: dict[VoicePipelineState, str] = {
    _S.ACTIVATED: "activated",
    _S.LISTENING: "listening",
    _S.THINKING: "thinking",
    _S.RESPONDING: "responding",
}


# ──────────────────────────────────────────────────────────────────────
# IPC protocol dataclasses
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StartASRCommand:
    """Orchestrator -> Widget: begin speech recognition."""

    timeout: float
    silence_timeout: float
    id: str
    language: str = "en-US"

    def to_message(self) -> dict[str, Any]:
        return {
            "method": "start_asr",
            "params": {
                "timeout": self.timeout,
                "silence_timeout": self.silence_timeout,
                "id": self.id,
                "language": self.language,
            },
        }


@dataclass(frozen=True)
class StopASRCommand:
    """Orchestrator -> Widget: stop active speech recognition."""

    def to_message(self) -> dict[str, Any]:
        return {"method": "stop_asr"}


@dataclass(frozen=True)
class ShowResponseCommand:
    """Orchestrator -> Widget: display (partial) response text."""

    text: str

    def to_message(self) -> dict[str, Any]:
        return {
            "method": "show_response",
            "params": {"text": self.text},
        }


@dataclass(frozen=True)
class ClearResponseCommand:
    """Orchestrator -> Widget: remove the response overlay."""

    def to_message(self) -> dict[str, Any]:
        return {"method": "clear_response"}


@dataclass(frozen=True)
class ASRResult:
    """Widget -> Orchestrator: speech recognition result."""

    success: bool
    id: str
    text: str | None = None
    error: str | None = None

    @classmethod
    def from_message(cls, params: dict[str, Any]) -> ASRResult:
        return cls(
            success=params.get("success", False),
            id=params.get("id", ""),
            text=params.get("text"),
            error=params.get("error"),
        )


# ──────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────


class VoiceCommandOrchestrator:
    """Coordinates wake-word -> ASR -> Claude -> TTS pipeline.

    Thread-safety contract:
    - handle_widget_message() is called from the socket read thread.
      It uses self._loop.call_soon_threadsafe() to resolve futures on
      the event loop.
    - All other methods run on the asyncio event loop.
    """

    def __init__(
        self,
        event_loop: asyncio.AbstractEventLoop,
        socket_server: WidgetSocketServer,
        voice_agent: VoiceAgent,
        state_store: StateStore,
        wake_word_service: WakeWordService,
        tts_voice: str = "Samantha",
        tts_speed: float = 150,
        tts_enabled: bool = True,
        asr_timeout: float = 10.0,
        asr_language: str = "en-US",
        silence_timeout: float = 3.0,
        text_linger: float = 3.0,
    ):
        self._loop = event_loop
        self.socket = socket_server
        self.agent = voice_agent
        self.state = state_store
        self.wake = wake_word_service
        self.tts_voice = tts_voice
        self.tts_speed = tts_speed
        self.tts_enabled = tts_enabled
        self.asr_timeout = asr_timeout
        self.asr_language = asr_language
        self.silence_timeout = silence_timeout
        self.text_linger = text_linger

        self._state = VoicePipelineState.IDLE
        # Written on the event loop, read from the socket thread.
        # Benign race: the future.done() guard in _safe_set() prevents
        # double-setting, and a stale read at worst drops a result.
        self._asr_future: asyncio.Future[ASRResult] | None = None
        self._asr_id: str | None = None
        self._interrupt = asyncio.Event()
        self._cancelled = False  # True when mic-off cancels the pipeline
        self._tts_proc: asyncio.subprocess.Process | None = None
        self._prev_display: str = ""  # Previous voice text for turn separator

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _transition(self, target: VoicePipelineState) -> bool:
        """Attempt a state transition. Returns True if valid."""
        allowed = _TRANSITIONS.get(self._state, set())
        if target not in allowed:
            logger.warning(
                "Invalid voice pipeline transition: %s -> %s (allowed: %s)",
                self._state.name,
                target.name,
                ", ".join(s.name for s in allowed) or "none",
            )
            return False
        self._state = target

        # Auto-update StateStore for display-relevant states
        status_str = _STATE_TO_STATUS.get(target)
        if status_str is not None:
            current = self.state.get("status") or {}
            current["status"] = status_str
            self.state.update("status", current, force=True)
            # Push immediate status update to widget (bypasses 3 FPS render loop)
            self._push_status_now(status_str)

        return True

    def _push_status_now(self, status: str) -> None:
        """Send a lightweight status-only frame for instant visual feedback."""
        from ..core.colors import StatusColors

        color_def = StatusColors.get(status)
        self.socket.push_frame({"theme_color": list(color_def.rgb)})

    def _set_voice_text(self, text: str, *, streaming: bool = True, tts_started_at: float = 0) -> None:
        """Update voice_text state for display."""
        self.state.update(
            "voice_text",
            {
                "full_text": text,
                "tts_started_at": tts_started_at,
                "tts_speed": self.tts_speed,
                "active": True,
                "streaming": streaming,
            },
        )

    def _clear_voice_text(self) -> None:
        """Clear voice text from display."""
        self.state.update("voice_text", {"active": False})

    async def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep that returns early if wake word interrupt fires."""
        try:
            await asyncio.wait_for(self._interrupt.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    # ------------------------------------------------------------------
    # Widget message handler (called from socket read thread)
    # ------------------------------------------------------------------

    def handle_widget_message(self, message: dict) -> None:
        """Dispatch messages received from the widget.

        Called from the socket server's read thread.  Uses
        self._loop.call_soon_threadsafe() to resolve the ASR future
        on the event loop.
        """
        method = message.get("method")
        params = message.get("params", {})

        if method == "asr_result":
            future = self._asr_future
            expected_id = self._asr_id
            if future is None:
                return

            result = ASRResult.from_message(params)

            # Validate that this result matches the current ASR request.
            if expected_id and result.id != expected_id:
                logger.debug(
                    "Ignoring stale ASR result (got %s, expected %s)",
                    result.id,
                    expected_id,
                )
                return

            def _safe_set() -> None:
                if not future.done():
                    future.set_result(result)

            self._loop.call_soon_threadsafe(_safe_set)

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    async def on_wake_word(self) -> None:
        """Entry point -- triggered by wake word detection.

        If the pipeline is already active, signals an interrupt instead
        of starting a new pipeline.  The running pipeline sees the
        interrupt, cleans up, and immediately restarts (no cooldown).
        This makes "clarvis" act as a reset button mid-pipeline.
        """
        if self._state is not VoicePipelineState.IDLE:
            logger.info("Wake word interrupt in %s state", self._state.name)
            self._interrupt.set()
            self._kill_tts()
            return

        self._prev_display = ""  # Fresh wake-word activation — no separator
        self._cancelled = False  # Reset cancel flag for new session

        # Lock status once for the entire voice session (including restarts).
        # Must happen here, BEFORE _run_pipeline, to capture the real
        # pre-voice status (not "activated" written by the detection callback).
        self.state.lock_status()

        try:
            is_restart = False
            while True:
                self._interrupt.clear()
                try:
                    await self._run_pipeline(is_restart=is_restart)
                except Exception:
                    logger.exception("Voice command pipeline failed")

                was_interrupted = self._interrupt.is_set()

                # --- Per-iteration cleanup ---
                if self._state is not VoicePipelineState.COOLDOWN:
                    self._state = VoicePipelineState.COOLDOWN
                self._clear_voice_text()

                if was_interrupted and not self._cancelled:
                    # Pause wake word and restart pipeline
                    logger.info("Pipeline interrupted — restarting")
                    self._prev_display = ""
                    self.wake.pause()
                    self._state = VoicePipelineState.IDLE
                    is_restart = True
                    continue

                break
        finally:
            self._interrupt.clear()
            self._clear_voice_text()
            self._state = VoicePipelineState.IDLE
            # Unlock status and restore pre-voice state
            self.state.unlock_status()
            restored = self.state.get("status") or {}
            restored_status = restored.get("status", "idle")
            self._push_status_now(restored_status)
            # Only resume wake word if not cancelled by mic toggle
            if not self._cancelled:
                self.wake.resume()
            self._cancelled = False

    async def notify(self, prompt: str) -> None:
        """Programmatic voice notification — skips wake word + ASR.

        Sends *prompt* directly to the voice agent through the full
        pipeline (context enrichment, Claude streaming, TTS).  Follow-up
        conversation via ASR is supported if Claude requests it.

        If the pipeline is already active the notification is dropped.
        """
        if self._state is not VoicePipelineState.IDLE:
            logger.warning(
                "Notification dropped — pipeline busy (%s)",
                self._state.name,
            )
            return

        self._prev_display = ""
        self._cancelled = False
        self.state.lock_status()
        try:
            await self._run_pipeline(prompt=prompt)
        except Exception:
            logger.exception("Voice notification failed")
        finally:
            self._interrupt.clear()
            self._clear_voice_text()
            self._state = VoicePipelineState.IDLE
            self.state.unlock_status()
            restored = self.state.get("status") or {}
            self._push_status_now(restored.get("status", "idle"))
            if not self._cancelled:
                self.wake.resume()
            self._cancelled = False

    async def _run_pipeline(self, is_restart: bool = False, prompt: str | None = None) -> None:
        t_start = time.monotonic()

        # 1. Activate — pause wake word (lock_status handled by caller)
        self._transition(VoicePipelineState.ACTIVATED)
        self._play_sound("Tink")
        self.wake.pause()

        # 2. Kick off prep work (agent connect + context build)
        agent_task = asyncio.create_task(self.agent.ensure_connected())
        context_task = self._loop.run_in_executor(None, self._build_voice_context)

        # 3. Get the user's text — either from ASR or from the supplied prompt
        if prompt is not None:
            # Programmatic path: skip ASR entirely
            text = prompt
            await asyncio.sleep(0.3)  # let activation sound play
        else:
            # ASR path: fire off speech recognition in parallel with prep
            self._asr_id = uuid.uuid4().hex[:12]
            self._asr_future = self._loop.create_future()
            asr_cmd = StartASRCommand(
                timeout=self.asr_timeout,
                silence_timeout=self.silence_timeout,
                id=self._asr_id,
                language=self.asr_language,
            )
            self.socket.send_command(asr_cmd.to_message())

            self._transition(VoicePipelineState.LISTENING)
            try:
                result = await asyncio.wait_for(self._asr_future, timeout=self.asr_timeout + 2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                if not is_restart and not self._cancelled:
                    await self._visual_bail()
                else:
                    self._transition(VoicePipelineState.COOLDOWN)
                return
            finally:
                self._asr_future = None
                self._asr_id = None

            if not result.success:
                if not is_restart:
                    await self._visual_bail()
                else:
                    self._transition(VoicePipelineState.COOLDOWN)
                return

            text = (result.text or "").strip()
            if not text:
                if not is_restart:
                    await self._visual_bail()
                else:
                    self._transition(VoicePipelineState.COOLDOWN)
                return

            logger.info("Voice command: %s", text)

        # 4. Await prep tasks (should already be done — ran during ASR/sleep)
        await agent_task
        context_prefix = await context_task

        t_prep = time.monotonic()

        # Re-enable wake word now that ASR is done (mic is free).
        # This lets the user say "clarvis" to interrupt Claude or TTS.
        self.wake.resume()

        # 5. Send to Claude, stream, parse metadata, speak
        self._transition(VoicePipelineState.THINKING)
        enriched = f"{context_prefix}{text}" if context_prefix else text
        logger.info(
            "Voice context: %s",
            context_prefix.replace("\n", " | ")[:200] if context_prefix else "none",
        )
        logger.info(
            "⏱ prep: %.2fs",
            t_prep - t_start,
        )

        result = await self._stream_and_speak(enriched)
        if result is None:
            # Interrupted or timed out — _stream_and_speak already transitioned
            return

        clean_text, expects_reply = result

        # 6. Follow-up conversation loop (no repeat wake word needed)
        #    Wake word stays paused for the entire follow-up loop to
        #    prevent accidental interrupts between turns.
        while expects_reply and not self._interrupt.is_set():
            self.wake.pause()
            self._push_status_now("awaiting")
            self._play_sound("Pop")  # Audible cue: "I'm listening for your reply"
            self._transition(VoicePipelineState.LISTENING)

            # Guard: check interrupt after state change
            if self._interrupt.is_set():
                break

            # Cancel any stale ASR future before creating a new one
            if self._asr_future is not None and not self._asr_future.done():
                self._asr_future.cancel()

            # Start follow-up ASR with extended timeout
            self._asr_id = uuid.uuid4().hex[:12]
            self._asr_future = self._loop.create_future()
            asr_cmd = StartASRCommand(
                timeout=self.asr_timeout + 3.0,
                silence_timeout=self.silence_timeout,
                id=self._asr_id,
                language=self.asr_language,
            )
            self.socket.send_command(asr_cmd.to_message())

            try:
                asr_result = await asyncio.wait_for(self._asr_future, timeout=self.asr_timeout + 5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.info("Follow-up ASR timed out or cancelled — ending conversation")
                self._kill_tts()
                break
            finally:
                self._asr_future = None
                self._asr_id = None

            if not asr_result.success or not (asr_result.text or "").strip():
                logger.info("Follow-up ASR empty/failed — ending conversation")
                self._kill_tts()
                break

            follow_up_text = asr_result.text.strip()
            logger.info("Voice follow-up: %s", follow_up_text)

            # Re-enable wake word for interrupt during Claude streaming/TTS
            self.wake.resume()

            self._transition(VoicePipelineState.THINKING)
            result = await self._stream_and_speak(follow_up_text)
            if result is None:
                return

            clean_text, expects_reply = result

        self._transition(VoicePipelineState.COOLDOWN)

    # ------------------------------------------------------------------
    # Context enrichment
    # ------------------------------------------------------------------

    def _build_voice_context(self) -> str:
        """Build situational context to prepend to voice commands.

        Reads directly from self.state (StateStore) — no IPC overhead.
        Returns a ``<context>`` block, or empty string if nothing useful.
        """
        parts: list[str] = []

        # Weather + location
        weather = self.state.get("weather") or {}
        if weather.get("temperature"):
            desc = weather.get("description", "").lower()
            temp = weather.get("temperature", "")
            parts.append(f"weather: {temp}F {desc}")

        location = self.state.get("location") or {}
        if location.get("city"):
            parts.append(f"location: {location['city']}")

        # Time
        time_data = self.state.get("time") or {}
        if time_data.get("timestamp"):
            try:
                dt = datetime.fromisoformat(time_data["timestamp"])
                parts.append(f"time: {dt.strftime('%A, %B %-d, %-I:%M%p').lower()}")
            except (ValueError, KeyError):
                pass

        if not parts:
            return ""

        block = "\n".join(parts)
        return f"<context>\n{block}\n</context>\n\n"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _stream_and_speak(self, query: str) -> tuple[str, bool] | None:
        """Send query to Claude, stream to grid, speak via TTS.

        Speaks eagerly at tool boundaries: when the agent yields None,
        accumulated text is spoken immediately before the tool executes.
        This gives the user instant feedback ("lemme check...") while
        the tool runs in the background.

        Returns (full_response_text, expects_reply), or None if interrupted
        or timed out (transitions to COOLDOWN in those cases).
        """
        t_query = time.monotonic()
        t_first_token = None
        response_chunks: list[str] = []
        all_spoken: list[str] = []
        interrupted = False

        # Show "Still thinking..." if TTFT exceeds 20s
        async def _thinking_hint() -> None:
            await asyncio.sleep(20.0)
            self._set_voice_text("Still thinking...")

        hint_task = self._loop.create_task(_thinking_hint())
        try:
            async with asyncio.timeout(AGENT_QUERY_TIMEOUT):
                async with aclosing(self.agent.send(query)) as stream:
                    async for chunk in stream:
                        if self._interrupt.is_set():
                            logger.info("Voice interrupt during Claude streaming")
                            await self._safe_interrupt()
                            interrupted = True
                            break

                        if chunk is None:
                            # Tool boundary — speak accumulated text now
                            if response_chunks:
                                segment = "".join(response_chunks).strip()
                                if segment:
                                    hint_task.cancel()
                                    self._transition(VoicePipelineState.RESPONDING)
                                    # Text already on screen from streaming — just speak
                                    await self._speak(segment)
                                    all_spoken.append(segment)
                                    self._prev_display = (
                                        f"{self._prev_display}\n\n{segment}" if self._prev_display else segment
                                    )
                                    if self._interrupt.is_set():
                                        interrupted = True
                                        break
                                response_chunks.clear()
                                self._clear_voice_text()
                            # Back to thinking while tool executes
                            self._transition(VoicePipelineState.THINKING)
                            continue

                        if t_first_token is None:
                            t_first_token = time.monotonic()
                            hint_task.cancel()
                        response_chunks.append(chunk)
                        current = "".join(response_chunks)
                        display = f"{self._prev_display}\n\n{current}" if self._prev_display else current
                        self._set_voice_text(display)
        except TimeoutError:
            logger.warning("Agent query timed out after %ss", AGENT_QUERY_TIMEOUT)
            await self._safe_interrupt()
            await self._bail("Sorry, that took too long.")
            return None
        finally:
            hint_task.cancel()

        t_stream_done = time.monotonic()

        if interrupted:
            self._transition(VoicePipelineState.COOLDOWN)
            return None

        # Speak any remaining text after stream ends
        final_segment = "".join(response_chunks).strip()
        expects_reply = self.agent.expects_reply

        # When a follow-up turn is expected, pause wake word before
        # the final TTS so speaker audio can't trigger a false wake-word
        # detection (which would kill TTS and skip the follow-up loop).
        # The follow-up loop in _run_pipeline keeps it paused; on_wake_word's
        # finally block resumes it when the voice session ends.
        if expects_reply:
            self.wake.pause()

        # Shorter linger when a follow-up is expected — just enough for
        # the audio system to flush before the "Pop" + ASR prompt.
        linger = 2.0 if expects_reply else self.text_linger

        if final_segment:
            self._transition(VoicePipelineState.RESPONDING)
            # Text already on screen from streaming — just speak
            await self._speak(final_segment)
            all_spoken.append(final_segment)
            self._prev_display = f"{self._prev_display}\n\n{final_segment}" if self._prev_display else final_segment
            if not self._interrupt.is_set() and linger > 0:
                await self._interruptible_sleep(linger)
        elif all_spoken and not self._interrupt.is_set() and linger > 0:
            # All text was spoken eagerly, but still linger before clearing
            await self._interruptible_sleep(linger)

        self._clear_voice_text()

        clean_response = " ".join(all_spoken)
        t_done = time.monotonic()
        ttft = (t_first_token - t_query) if t_first_token else 0
        logger.info(
            "⏱ TTFT: %.2fs | stream: %.2fs | TTS: %.2fs | total: %.2fs (%d chars)",
            ttft,
            t_stream_done - (t_first_token or t_query),
            t_done - t_stream_done,
            t_done - t_query,
            len(clean_response),
        )

        return clean_response, expects_reply

    def _play_sound(self, sound: str = "Tink") -> None:
        """Play a macOS system sound (fire-and-forget)."""

        async def _reap() -> None:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "afplay",
                    f"/System/Library/Sounds/{sound}.aiff",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            except Exception:
                pass

        self._loop.create_task(_reap())

    async def _visual_bail(self) -> None:
        """Brief visual-only feedback on ASR failure, then cooldown.

        Shows "..." on the grid for 1 second (no TTS) so the user knows the
        system heard the wake word but didn't get speech.
        """
        self._set_voice_text("...")
        await asyncio.sleep(1.0)
        self._clear_voice_text()
        self._transition(VoicePipelineState.COOLDOWN)

    async def _safe_interrupt(self) -> None:
        """Interrupt the agent with a timeout guard.

        If the SDK hangs, force-disconnect to unblock the pipeline.
        """
        try:
            await asyncio.wait_for(self.agent.interrupt(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error("Agent interrupt timed out — force-disconnecting")
            await self.agent.disconnect()

    def _kill_tts(self) -> None:
        """Kill TTS subprocess if running."""
        if self._tts_proc is not None:
            try:
                self._tts_proc.kill()
            except ProcessLookupError:
                pass

    def cancel(self) -> None:
        """Cancel any active voice pipeline immediately.

        Called from the mic toggle handler when the user disables the mic.
        Safe to call from any state (no-op if idle).
        """
        if self._state is VoicePipelineState.IDLE:
            return

        logger.info("Voice pipeline cancelled by mic toggle (was %s)", self._state.name)

        # Mark as cancelled so on_wake_word exits instead of restarting
        self._cancelled = True

        # Signal the pipeline loop to exit
        self._interrupt.set()
        self._kill_tts()

        # Cancel the pending ASR future so the pipeline doesn't hang
        # waiting for speech that will never come.
        if self._asr_future is not None and not self._asr_future.done():
            self._asr_future.cancel()
            # Tell the widget to stop listening immediately
            self.socket.send_command(StopASRCommand().to_message())

    async def _bail(self, message: str) -> None:
        """Speak an error/abort message and transition to COOLDOWN."""
        await self._speak(message)
        self._transition(VoicePipelineState.COOLDOWN)

    async def _speak(self, text: str) -> None:
        """TTS via macOS say command. Killable via _interrupt / _tts_proc."""
        if not self.tts_enabled:
            return
        try:
            self._tts_proc = await asyncio.create_subprocess_exec(
                "say",
                "-v",
                self.tts_voice,
                "-r",
                str(self.tts_speed),
                text,
            )
            await self._tts_proc.wait()
        except Exception:
            logger.exception("TTS failed")
        finally:
            self._tts_proc = None
