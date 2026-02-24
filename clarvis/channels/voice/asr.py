"""ASR backend abstraction — pluggable speech recognition for the voice pipeline.

The orchestrator calls ``backend.listen()`` and gets back an ``ASRResult``.
Implementations handle all transport/model details internally.

Current backends:
- ``WidgetASRBackend``: delegates to Swift ``SFSpeechRecognizer`` via widget IPC.
"""

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...widget.socket_server import WidgetSocketServer

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Shared result type
# ------------------------------------------------------------------


@dataclass(frozen=True)
class ASRResult:
    """Speech recognition result returned by all backends."""

    success: bool
    text: str | None = None
    error: str | None = None


# ------------------------------------------------------------------
# Abstract base
# ------------------------------------------------------------------


class ASRBackend(ABC):
    """Abstract ASR backend.

    Implementations must be async-friendly and support cancellation.
    """

    @abstractmethod
    async def listen(
        self,
        timeout: float,
        silence_timeout: float,
        language: str = "en-US",
    ) -> ASRResult:
        """Begin listening and return transcribed text.

        Blocks until speech is recognised, timeout elapses, or
        :meth:`cancel` is called.
        """
        ...

    @abstractmethod
    def cancel(self) -> None:
        """Cancel any in-progress :meth:`listen` call.

        Must be safe to call from any thread and idempotent.
        """
        ...

    def handle_widget_message(self, message: dict[str, Any]) -> None:
        """Handle incoming widget messages. Default: ignore."""

    async def start(self) -> None:
        """One-time init (e.g. load model). Called at pipeline init."""

    async def stop(self) -> None:
        """Teardown (e.g. unload model). Called at daemon shutdown."""


# ------------------------------------------------------------------
# Widget backend (macOS SFSpeechRecognizer via Swift IPC)
# ------------------------------------------------------------------


class WidgetASRBackend(ASRBackend):
    """ASR via the Swift widget's ``SFSpeechRecognizer``.

    Encapsulates the ``StartASRCommand`` / ``StopASRCommand`` protocol
    and the future-based result pattern previously inline in the
    orchestrator.
    """

    def __init__(
        self,
        event_loop: asyncio.AbstractEventLoop,
        socket_server: "WidgetSocketServer",
    ) -> None:
        self._loop = event_loop
        self._socket = socket_server
        self._future: asyncio.Future[ASRResult] | None = None
        self._asr_id: str | None = None

    # -- Widget message routing ------------------------------------

    def handle_widget_message(self, message: dict[str, Any]) -> None:
        """Route ``asr_result`` messages from widget.

        Called from the socket server's read thread — uses
        ``call_soon_threadsafe`` to resolve the future on the event loop.
        """
        if message.get("method") != "asr_result":
            return

        params = message.get("params", {})
        future = self._future
        expected_id = self._asr_id

        if future is None:
            return

        result_id = params.get("id", "")
        if expected_id and result_id != expected_id:
            logger.debug(
                "Ignoring stale ASR result (got %s, expected %s)",
                result_id,
                expected_id,
            )
            return

        result = ASRResult(
            success=params.get("success", False),
            text=params.get("text"),
            error=params.get("error"),
        )

        def _safe_set() -> None:
            if not future.done():
                future.set_result(result)

        self._loop.call_soon_threadsafe(_safe_set)

    # -- ASRBackend interface --------------------------------------

    async def listen(
        self,
        timeout: float,
        silence_timeout: float,
        language: str = "en-US",
    ) -> ASRResult:
        from .orchestrator import StartASRCommand

        self._asr_id = uuid.uuid4().hex[:12]
        self._future = self._loop.create_future()

        cmd = StartASRCommand(
            timeout=timeout,
            silence_timeout=silence_timeout,
            id=self._asr_id,
            language=language,
        )
        self._socket.send_command(cmd.to_message())

        try:
            return await asyncio.wait_for(self._future, timeout=timeout + 2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return ASRResult(success=False, error="timeout")
        finally:
            self._future = None
            self._asr_id = None

    def cancel(self) -> None:
        from .orchestrator import StopASRCommand

        future = self._future
        if future is not None and not future.done():
            future.cancel()
            self._socket.send_command(StopASRCommand().to_message())
