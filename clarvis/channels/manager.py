"""Channel manager -- owns shared agent, starts/stops channels, outbound routing.

Replaces ChannelService + nanobot ChannelManager with a unified manager
that uses a single shared agent for all online channels.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from ..core.paths import agent_home
from .bus import MessageBus
from .context import build_context_prefix
from .events import InboundMessage, OutboundMessage
from .state import ChannelState

if TYPE_CHECKING:
    from ..agent.agent import Agent
    from .registry import UserRegistry

logger = logging.getLogger(__name__)

OutboundHook = Callable[[str, InboundMessage], str]


class ChannelManager:
    """Manages all online channels with a single shared agent.

    Responsibilities:
    - Owns the shared channel Agent and provides serialized access
    - Starts/stops channels
    - Routes outbound messages to the correct channel
    - Runs the message handler (commands, access, enrichment, agent routing)
    """

    def __init__(
        self,
        agent: "Agent",
        channels_config: dict[str, Any],
        registry: "UserRegistry",
        state: ChannelState,
        bus: MessageBus | None = None,
    ):
        self._agent = agent
        self._channels_config = channels_config
        self._registry = registry
        self._state = state
        self._bus = bus or MessageBus()
        self._channels: dict[str, Any] = {}
        self._channel_tasks: list[asyncio.Task] = []
        self._dispatch_task: asyncio.Task | None = None
        self._handler_task: asyncio.Task | None = None
        self._inflight: set[asyncio.Task] = set()
        self._outbound_hooks: dict[str, OutboundHook] = {}
        self._voice_channel = None
        self._transcript_path = agent_home("factoria") / "transcript.jsonl"
        self._transcript_buf: list[str] = []
        self._transcript_flush_task: asyncio.Task | None = None

    @property
    def bus(self) -> MessageBus:
        return self._bus

    @property
    def voice_channel(self):
        return self._voice_channel

    @property
    def registry(self) -> "UserRegistry":
        return self._registry

    @property
    def state(self) -> ChannelState:
        return self._state

    def _log_transcript(self, channel: str, chat_id: str, sender: str, content: str) -> None:
        """Buffer a transcript entry and schedule flush."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "channel": channel,
            "chat_id": chat_id,
            "sender": sender,
            "content": content,
        }
        self._transcript_buf.append(json.dumps(entry, ensure_ascii=False) + "\n")
        if self._transcript_flush_task is None or self._transcript_flush_task.done():
            self._transcript_flush_task = asyncio.create_task(self._flush_transcript())

    async def _flush_transcript(self) -> None:
        """Flush buffered transcript entries to disk after a short delay."""
        await asyncio.sleep(1.0)
        if not self._transcript_buf:
            return
        lines = self._transcript_buf.copy()
        self._transcript_buf.clear()
        try:
            with self._transcript_path.open("a") as f:
                f.writelines(lines)
        except OSError:
            logger.debug("Failed to write transcript entries")

    async def send_to_agent(self, text: str) -> str:
        """Send to agent -- lock is internal to Agent._send_inner()."""
        from ..agent.agent import collect_response

        return await collect_response(self._agent, text)

    def _init_channels(self) -> None:
        """Initialize channel instances from config."""
        for name, ch_cfg in self._channels_config.items():
            if not isinstance(ch_cfg, dict):
                continue
            if not ch_cfg.get("enabled", False):
                continue

            if name == "discord":
                try:
                    from .discord.channel import DiscordChannel, DiscordConfig

                    config = DiscordConfig(
                        enabled=True,
                        token=os.environ.get("DISCORD_BOT_TOKEN") or ch_cfg.get("token", ""),
                        allow_from=ch_cfg.get("allow_from", []),
                        gateway_url=ch_cfg.get(
                            "gateway_url",
                            "wss://gateway.discord.gg/?v=10&encoding=json",
                        ),
                        intents=ch_cfg.get("intents", 37377),
                    )
                    self._channels["discord"] = DiscordChannel(config, self._bus)
                    self._outbound_hooks["discord"] = self._replace_discord_mentions
                    logger.info("Discord channel enabled")
                except ImportError:
                    logger.warning("Discord channel not available (missing deps)")
            else:
                logger.warning("Unsupported channel: %s (only discord is built-in)", name)

    async def start(self) -> None:
        """Initialize channels and start handler + dispatcher."""
        from .voice.channel import VoiceChannel

        self._voice_channel = VoiceChannel(bus=self._bus)

        # Start message handler
        self._handler_task = asyncio.create_task(self._handler_loop(), name="channel_handler")

        # Initialize external channels
        self._init_channels()

        # Register voice channel (always present for outbound TTS routing)
        self._channels["voice"] = self._voice_channel

        # Start outbound dispatcher
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound(), name="outbound_dispatch")

        # Start each external channel
        for name, channel in self._channels.items():
            if name == "voice":
                continue
            task = asyncio.create_task(
                self._start_channel(name, channel),
                name=f"channel_{name}",
            )
            self._channel_tasks.append(task)

        # If voice-only, mark it as running (daemon manages actual pipeline)
        if list(self._channels.keys()) == ["voice"]:
            await self._voice_channel.start()

        logger.info("ChannelManager started: %s", ", ".join(self._channels.keys()))

    async def _start_channel(self, name: str, channel) -> None:
        """Start a channel and log exceptions."""
        try:
            await channel.start()
        except Exception:
            logger.exception("Failed to start channel %s", name)

    async def _handler_loop(self) -> None:
        """Main loop -- consume inbound messages and process them."""
        logger.info("ChannelManager handler started")
        while True:
            try:
                msg = await self._bus.consume_inbound()
                task = asyncio.create_task(self._handle(msg))
                self._inflight.add(task)
                task.add_done_callback(self._inflight.discard)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Handler loop error")

    async def _handle(self, msg: InboundMessage) -> None:
        """Process a single inbound message."""
        # 1. Commands -- ! prefix, any channel, before access control
        if msg.content.lstrip().startswith("!"):
            from .commands import run as run_command

            response = run_command(
                msg.content,
                msg.sender_id,
                msg.chat_id,
                msg.channel,
                self._registry,
                self._state,
            )
            if response:
                logger.info("Command from %s/%s: %s", msg.channel, msg.chat_id, msg.content[:80])
                await self._bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=response,
                    )
                )
                return

        # 2. Access control -- generic
        if msg.channel != "voice":
            if not self._state.is_chat_enabled(msg.channel, msg.chat_id):
                logger.debug("Ignoring message in disabled chat %s/%s", msg.channel, msg.chat_id)
                return
            if not self._registry.is_registered(msg.channel, msg.sender_id):
                logger.debug("Ignoring unregistered user %s", msg.sender_id)
                return

        # 3. Context enrichment (channel prefix)
        prefix = build_context_prefix(msg, self._registry)
        enriched = f"{prefix}{msg.content}" if prefix else msg.content

        logger.info(
            "[dialogue] %s/%s IN: %s",
            msg.channel,
            msg.chat_id,
            enriched[:500],
        )
        self._log_transcript(msg.channel, msg.chat_id, msg.sender_id, msg.content)

        # 4. Memory + ambient grounding via ContextInjector
        enriched = await self._agent.enrich(enriched)

        # 5. Agent routing -- serialized via lock
        try:
            response = await self.send_to_agent(enriched)
            if not response:
                response = "(No response)"

            logger.info(
                "[dialogue] %s/%s OUT: %s",
                msg.channel,
                msg.chat_id,
                response[:500],
            )
            self._log_transcript(msg.channel, msg.chat_id, "clarvis", response)

            # 6. Outbound hook -- per-channel transform
            hook = self._outbound_hooks.get(msg.channel)
            if hook:
                response = hook(response, msg)

            await self._bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=response,
                )
            )
        except Exception:
            logger.exception("Failed to handle message from %s/%s", msg.channel, msg.chat_id)
            try:
                await self._bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="Sorry, I encountered an error processing your message.",
                    )
                )
            except Exception:
                logger.exception("Failed to send error response")

    def _replace_discord_mentions(self, text: str, msg: InboundMessage) -> str:
        """Replace @Name patterns with Discord <@user_id> pings."""
        name_map = self._registry.all_name_mappings("discord")
        for name, user_id in sorted(name_map.items(), key=lambda x: -len(x[0])):
            text = text.replace(f"@{name}", f"<@{user_id}>")
        return text

    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        while True:
            try:
                msg = await self._bus.consume_outbound()
                channel = self._channels.get(msg.channel)
                if channel:
                    try:
                        await channel.send(msg)
                    except Exception:
                        logger.exception("Error sending to %s", msg.channel)
                else:
                    logger.warning("Unknown channel: %s", msg.channel)
            except asyncio.CancelledError:
                break

    async def stop(self) -> None:
        """Stop all channels, handler, and dispatcher."""
        for name, channel in self._channels.items():
            if name == "voice":
                continue
            try:
                await channel.stop()
                logger.info("Stopped %s channel", name)
            except Exception:
                logger.exception("Error stopping %s", name)

        for task in self._channel_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass

        if self._handler_task:
            self._handler_task.cancel()
            try:
                await self._handler_task
            except asyncio.CancelledError:
                pass

        # Cancel in-flight _handle tasks
        for task in list(self._inflight):
            task.cancel()
        if self._inflight:
            await asyncio.gather(*self._inflight, return_exceptions=True)

        if self._voice_channel:
            await self._voice_channel.stop()

        # Flush any buffered transcript entries
        if self._transcript_buf:
            try:
                with self._transcript_path.open("a") as f:
                    f.writelines(self._transcript_buf)
                self._transcript_buf.clear()
            except OSError:
                pass

        logger.info("ChannelManager stopped")

    def get_channel(self, name: str) -> Any:
        """Get a channel by name."""
        return self._channels.get(name)

    def get_status(self) -> dict[str, dict]:
        """Get status of all channels."""
        return {name: {"enabled": True, "running": channel.is_running} for name, channel in self._channels.items()}

    @property
    def enabled_channels(self) -> list[str]:
        """List of enabled channel names."""
        return list(self._channels.keys())

    async def send_message(self, channel: str, chat_id: str, content: str) -> bool:
        """Send a message to a specific channel/chat."""
        ch = self.get_channel(channel)
        if ch is None:
            return False
        try:
            await ch.send(OutboundMessage(channel=channel, chat_id=chat_id, content=content))
            return True
        except Exception:
            logger.exception("Failed to send to %s/%s", channel, chat_id)
            return False
