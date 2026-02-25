"""Two-layer memory consolidation: MEMORY.md (rolling) + memory backend.

Inspired by nanobot's consolidation pattern. When conversation messages
exceed a threshold, old messages are summarized by an LLM into:
- A rolling MEMORY.md (curated facts for the system prompt)
- A history entry fed into the memory backend (Hindsight)
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ConversationConsolidator:
    """Consolidates old conversation messages into persistent memory layers.

    Usage::

        consolidator = ConversationConsolidator(memory_service=memory_svc)
        result = await consolidator.maybe_consolidate("voice", messages)
        if result:
            # Consolidation happened — MEMORY.md updated, history added to graph
            pass
    """

    def __init__(
        self,
        memory_service: Any = None,  # HindsightBackend or compatible
        model: str = "claude-haiku-4-5-20251001",
        threshold: int = 30,
        keep_recent: int = 15,
        memory_dir: Path | None = None,
    ):
        self._memory_service = memory_service
        self._model = model
        self._threshold = threshold
        self._keep_recent = keep_recent
        self._memory_dir = memory_dir or Path.home() / ".clarvis" / "memory"
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._memory_file = self._memory_dir / "MEMORY.md"
        self._last_consolidated: dict[str, int] = {}  # session_key → watermark

    async def maybe_consolidate(self, session_key: str, messages: list[dict]) -> dict | None:
        """Consolidate if message count exceeds threshold.

        Args:
            session_key: Channel/session identifier.
            messages: Full conversation as list of ``{"role": ..., "content": ...}`` dicts.

        Returns:
            Consolidation result dict (``history_entry``, ``memory_update``) or None if
            threshold not reached.
        """
        watermark = self._last_consolidated.get(session_key, 0)
        new_count = len(messages) - watermark
        if new_count < self._threshold:
            return None

        old_messages = messages[watermark : -self._keep_recent] if self._keep_recent else messages[watermark:]
        if not old_messages:
            return None

        logger.info(
            "Consolidating %d messages for %s (total=%d)",
            len(old_messages),
            session_key,
            len(messages),
        )

        conversation = self._format_conversation(old_messages)
        current_memory = self.get_memory_context()
        result = await self._call_llm(conversation, current_memory)

        if result:
            # Layer 1: Update rolling MEMORY.md
            if update := result.get("memory_update"):
                if update != current_memory:
                    self._write_memory(update)
                    logger.info("Updated MEMORY.md (%d chars)", len(update))

            # Layer 2: Feed history entry into memory system
            if entry := result.get("history_entry"):
                if self._memory_service:
                    try:
                        await self._memory_service.add(entry, dataset="parletre")
                        logger.info("Added history entry to memory (%d chars)", len(entry))
                    except Exception as e:
                        logger.warning("Failed to add history to memory: %s", e)

            self._last_consolidated[session_key] = max(0, len(messages) - self._keep_recent)

        return result

    def get_memory_context(self) -> str:
        """Read MEMORY.md for injection into system prompt."""
        return self._read_memory()

    def _format_conversation(self, messages: list[dict]) -> str:
        """Format messages into readable text for the LLM."""
        lines = []
        for m in messages:
            role = m.get("role", "?").upper()
            content = m.get("content", "")
            if isinstance(content, str):
                content = content[:500]
            elif isinstance(content, list):
                # Handle structured content (text blocks)
                texts = [b.get("text", "") for b in content if isinstance(b, dict)]
                content = " ".join(texts)[:500]
            else:
                content = str(content)[:500]
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _read_memory(self) -> str:
        if self._memory_file.exists():
            return self._memory_file.read_text(encoding="utf-8")
        return ""

    def _write_memory(self, content: str) -> None:
        self._memory_file.write_text(content, encoding="utf-8")

    async def _call_llm(self, conversation: str, current_memory: str) -> dict | None:
        """Call LLM for consolidation. Uses anthropic SDK directly."""
        try:
            import anthropic

            client = anthropic.AsyncAnthropic()
            prompt = (
                "You are a memory consolidation agent. Process this conversation "
                "and return a JSON object with exactly two keys:\n\n"
                '1. "history_entry": A paragraph (2-5 sentences) summarizing key events, '
                "decisions, and outcomes from this conversation.\n"
                '2. "memory_update": Updated long-term memory incorporating any new facts, '
                "preferences, or decisions discovered. Keep existing important information, "
                "add new details, remove anything contradicted. Keep it concise.\n\n"
                f"## Current Long-term Memory\n{current_memory or '(empty)'}\n\n"
                f"## Conversation to Process\n{conversation}\n\n"
                "Respond with ONLY valid JSON, no markdown fences."
            )
            response = await client.messages.create(
                model=self._model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            return json.loads(text)
        except Exception as e:
            logger.error("Consolidation LLM call failed: %s", e)
            return None
