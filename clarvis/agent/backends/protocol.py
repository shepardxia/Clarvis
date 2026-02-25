"""Agent backend protocol — interface for LLM runtime backends."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class BackendConfig:
    """Shared config passed to any backend at construction time."""

    session_key: str
    project_dir: Path
    session_id_path: Path
    system_prompt: str | None = None
    model: str | None = None
    max_thinking_tokens: int | None = None
    mcp_port: int | None = None
    allowed_tools: list[str] | None = None


@runtime_checkable
class AgentBackend(Protocol):
    """Interface for swappable agent runtimes."""

    async def connect(self) -> None:
        """Establish connection to the LLM runtime."""
        ...

    async def disconnect(self) -> None:
        """Tear down connection."""
        ...

    async def send(self, text: str) -> AsyncGenerator[str | None, None]:
        """Send a message and yield response chunks.

        Yields text chunks and None at tool-call boundaries.
        """
        ...

    async def interrupt(self) -> None:
        """Interrupt the current operation."""
        ...

    @property
    def connected(self) -> bool:
        """Whether the backend is currently connected."""
        ...

    def setup(self) -> None:
        """One-time setup (e.g. project dir scaffolding). Called before connect."""
        ...
