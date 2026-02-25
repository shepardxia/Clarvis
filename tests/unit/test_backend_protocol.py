"""Verify AgentBackend protocol is structurally sound."""

from collections.abc import AsyncGenerator
from pathlib import Path

from clarvis.agent.backends.protocol import AgentBackend, BackendConfig


class FakeBackend:
    """Minimal implementation to verify protocol compliance."""

    def __init__(self):
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def send(self, text: str) -> AsyncGenerator[str | None, None]:
        yield f"echo: {text}"

    async def interrupt(self) -> None:
        pass

    @property
    def connected(self) -> bool:
        return self._connected

    def setup(self) -> None:
        pass


def test_fake_backend_satisfies_protocol():
    assert isinstance(FakeBackend(), AgentBackend)


def test_backend_config_defaults():
    cfg = BackendConfig(
        session_key="test",
        project_dir=Path("/tmp/test"),
        session_id_path=Path("/tmp/test/session_id"),
    )
    assert cfg.model is None
    assert cfg.mcp_port is None
