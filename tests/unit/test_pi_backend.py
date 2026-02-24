"""Tests for PiBackend — protocol compliance, config, and event translation."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from clarvis.core.backends.pi import PiBackend
from clarvis.core.backends.protocol import AgentBackend, BackendConfig


def _make_config(**overrides) -> BackendConfig:
    defaults = dict(
        session_key="test-voice",
        project_dir=Path("/tmp/clarvis-pi-test"),
        session_id_path=Path("/tmp/clarvis-pi-test/session_id"),
    )
    defaults.update(overrides)
    return BackendConfig(**defaults)


# ── Protocol compliance ──


def test_pi_backend_satisfies_protocol():
    backend = PiBackend(_make_config())
    assert isinstance(backend, AgentBackend)


# ── Socket path uniqueness ──


def test_socket_path_includes_session_key():
    b1 = PiBackend(_make_config(session_key="voice"))
    b2 = PiBackend(_make_config(session_key="channels"))
    assert "voice" in b1._socket_path
    assert "channels" in b2._socket_path
    assert b1._socket_path != b2._socket_path


# ── Setup creates directory ──


def test_setup_creates_project_dir(tmp_path):
    target = tmp_path / "new-dir"
    backend = PiBackend(_make_config(project_dir=target))
    backend.setup()
    assert target.is_dir()


# ── Session ID no-ops ──


def test_session_id_noop():
    backend = PiBackend(_make_config())
    backend.set_session_id("abc")
    assert backend.get_session_id() is None


# ── Initial state ──


def test_not_connected_initially():
    backend = PiBackend(_make_config())
    assert not backend.connected


# ── send() event translation ──


@pytest.mark.asyncio
async def test_send_translates_events():
    """Verify send() yields text for text_delta, None for tool_end, returns on agent_end."""
    backend = PiBackend(_make_config())

    events = [
        {"event": "text_delta", "text": "Hello"},
        {"event": "text_delta", "text": " world"},
        {"event": "tool_start", "name": "bash"},
        {"event": "tool_end", "name": "bash"},
        {"event": "text_delta", "text": "!"},
        {"event": "agent_end"},
    ]

    # Mock the reader as an async line-reader
    lines = [json.dumps(e).encode() + b"\n" for e in events]
    reader = AsyncMock()
    reader.readline = AsyncMock(side_effect=lines)

    # Mock writer
    writer = MagicMock()
    writer.write = MagicMock()

    backend._connected = True
    backend._reader = reader
    backend._writer = writer

    chunks = []
    async for chunk in backend.send("test prompt"):
        chunks.append(chunk)

    assert chunks == ["Hello", " world", None, "!"]


@pytest.mark.asyncio
async def test_send_raises_on_error_event():
    """Verify send() raises RuntimeError on error events."""
    backend = PiBackend(_make_config())

    events = [
        {"event": "error", "message": "something broke"},
    ]
    lines = [json.dumps(e).encode() + b"\n" for e in events]
    reader = AsyncMock()
    reader.readline = AsyncMock(side_effect=lines)

    writer = MagicMock()
    writer.write = MagicMock()

    backend._connected = True
    backend._reader = reader
    backend._writer = writer

    with pytest.raises(RuntimeError, match="something broke"):
        async for _ in backend.send("test"):
            pass


@pytest.mark.asyncio
async def test_send_raises_when_not_connected():
    """Verify send() raises when not connected."""
    backend = PiBackend(_make_config())

    with pytest.raises(RuntimeError, match="not connected"):
        async for _ in backend.send("test"):
            pass


# ── Session file path ──


def test_session_file_in_project_dir():
    cfg = _make_config(project_dir=Path("/home/test/.clarvis/home"))
    backend = PiBackend(cfg)
    assert backend._session_file == Path("/home/test/.clarvis/home/pi-session.jsonl")
