"""Voice channel — wraps existing voice orchestrator as a BaseChannel.

The voice pipeline (wake word → ASR → Claude → TTS) is managed by the
daemon and voice_orchestrator. This channel adapter exists for outbound
TTS routing: agent-initiated messages (timer notifications, etc.) are
spoken aloud via the orchestrator.

Inbound voice goes directly through the orchestrator → Clarvis agent,
bypassing the MessageBus entirely.
"""

import logging
from typing import TYPE_CHECKING, Any

from ..base import BaseChannel

if TYPE_CHECKING:
    from ..bus import MessageBus
    from ..events import OutboundMessage
    from .orchestrator import VoiceCommandOrchestrator

logger = logging.getLogger(__name__)


class VoiceChannel(BaseChannel):
    """Adapts Clarvis's voice pipeline into the channel system.

    The voice pipeline lifecycle is managed by the daemon — start/stop
    here are lightweight hooks for the ChannelManager to call.
    """

    name = "voice"

    def __init__(
        self,
        bus: "MessageBus",
        orchestrator: "VoiceCommandOrchestrator | None" = None,
        config: Any = None,
    ):
        super().__init__(config=config, bus=bus)
        self._orchestrator = orchestrator

    def set_orchestrator(self, orchestrator: "VoiceCommandOrchestrator") -> None:
        """Late-bind the orchestrator (available after daemon voice init)."""
        self._orchestrator = orchestrator

    async def start(self) -> None:
        """Mark channel as running.

        The actual voice pipeline (wake word, ASR) is started by the daemon.
        """
        self._running = True
        logger.info("Voice channel started")

    async def stop(self) -> None:
        """Mark channel as stopped."""
        self._running = False
        logger.info("Voice channel stopped")

    async def send(self, msg: "OutboundMessage") -> None:
        """Speak a response via TTS through the voice orchestrator.

        Used for agent-initiated messages (timer notifications, cron jobs)
        that need to be spoken aloud.
        """
        if not self._orchestrator:
            logger.warning("Voice channel: no orchestrator, dropping message")
            return
        await self._orchestrator.notify(msg.content)

    def is_allowed(self, sender_id: str) -> bool:
        """Voice is always local — always allowed."""
        return True
