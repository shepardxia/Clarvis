"""Claude SDK client for memU — uses the official Anthropic Python SDK.

Mirrors the interface of memU's OpenAISDKClient so it can be used as a
drop-in replacement. Based on memU PR #214 (NevaMind-AI/memU).

Methods: chat, summarize, vision, embed (raises), transcribe (raises).
All return ``tuple[str, raw_response]`` so LLMClientWrapper can unpack.
"""

import base64
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class ClaudeUsage:
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ClaudeMessage:
    id: str
    type: str
    role: str
    content: list[dict[str, Any]]
    model: str
    stop_reason: str | None
    stop_sequence: str | None
    usage: ClaudeUsage

    @property
    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")


class ClaudeSDKClient:
    """Async Anthropic client matching memU's LLM client interface."""

    def __init__(
        self,
        *,
        api_key: str,
        chat_model: str = "claude-haiku-4-5-20251001",
        base_url: str | None = None,
        embed_model: str | None = None,
    ):
        from anthropic import AsyncAnthropic

        self.api_key = api_key
        self.chat_model = chat_model
        self.embed_model = embed_model

        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = AsyncAnthropic(**kwargs)

    async def chat(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> tuple[str, ClaudeMessage]:
        kwargs: dict[str, Any] = {
            "model": self.chat_model,
            "max_tokens": max_tokens or 4096,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = await self.client.messages.create(**kwargs)
        message = self._parse_response(response)
        logger.debug("Claude chat response: %s tokens", message.usage.total_tokens)
        return message.text, message

    async def summarize(
        self,
        text: str,
        *,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
    ) -> tuple[str, ClaudeMessage]:
        prompt = system_prompt or "Summarize the text in one short paragraph."
        response = await self.client.messages.create(
            model=self.chat_model,
            max_tokens=max_tokens or 4096,
            system=prompt,
            messages=[{"role": "user", "content": text}],
        )
        message = self._parse_response(response)
        logger.debug("Claude summarize response: %s tokens", message.usage.total_tokens)
        return message.text, message

    async def vision(
        self,
        prompt: str,
        image_path: str,
        *,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
    ) -> tuple[str, ClaudeMessage]:
        image_data = Path(image_path).read_bytes()
        base64_image = base64.b64encode(image_data).decode("utf-8")
        suffix = Path(image_path).suffix.lower()
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }.get(suffix, "image/jpeg")

        content: list[dict[str, Any]] = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64_image}},
            {"type": "text", "text": prompt},
        ]
        kwargs: dict[str, Any] = {
            "model": self.chat_model,
            "max_tokens": max_tokens or 4096,
            "messages": [{"role": "user", "content": content}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = await self.client.messages.create(**kwargs)
        message = self._parse_response(response)
        logger.debug("Claude vision response: %s tokens", message.usage.total_tokens)
        return message.text, message

    async def embed(self, inputs: list[str]) -> tuple[list[list[float]], None]:
        msg = "Claude has no embedding API. Use a separate 'embedding' profile with OpenAI or Voyage AI."
        raise NotImplementedError(msg)

    async def transcribe(
        self,
        audio_path: str,
        *,
        prompt: str | None = None,
        language: str | None = None,
        response_format: Literal["text", "json", "verbose_json"] = "text",
    ) -> tuple[str, Any]:
        msg = "Claude has no transcription API. Use OpenAI Whisper or another provider."
        raise NotImplementedError(msg)

    def _parse_response(self, response: Any) -> ClaudeMessage:
        usage = ClaudeUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        content = []
        for block in response.content:
            if hasattr(block, "text"):
                content.append({"type": "text", "text": block.text})
            elif hasattr(block, "type"):
                content.append({"type": block.type})
        return ClaudeMessage(
            id=response.id,
            type=response.type,
            role=response.role,
            content=content,
            model=response.model,
            stop_reason=response.stop_reason,
            stop_sequence=response.stop_sequence,
            usage=usage,
        )
