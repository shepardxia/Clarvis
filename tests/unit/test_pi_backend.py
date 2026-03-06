"""PiBackend — event translation and error propagation."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from clarvis.agent.backends.pi import PiBackend, PiConfig


def _make_config(**overrides) -> PiConfig:
    defaults = dict(
        session_key="test-voice",
        project_dir=Path("/tmp/clarvis-pi-test"),
    )
    defaults.update(overrides)
    return PiConfig(**defaults)


@pytest.mark.asyncio
async def test_send_translates_events():
    """send() yields text for text_delta, None for tool_end, returns on agent_end."""
    backend = PiBackend(_make_config())

    events = [
        {"event": "text_delta", "text": "Hello"},
        {"event": "text_delta", "text": " world"},
        {"event": "tool_start", "name": "bash"},
        {"event": "tool_end", "name": "bash"},
        {"event": "text_delta", "text": "!"},
        {"event": "agent_end"},
    ]

    lines = [json.dumps(e).encode() + b"\n" for e in events]
    reader = AsyncMock()
    reader.readline = AsyncMock(side_effect=lines)
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
async def test_reset_sends_command_and_waits():
    """PiBackend.reset() sends reset command and waits for reset_done."""
    config = _make_config()
    backend = PiBackend(config)

    backend._connected = True
    backend._writer = MagicMock()
    backend._writer.write = MagicMock()

    response = json.dumps({"event": "reset_done"}) + "\n"
    backend._reader = asyncio.StreamReader()
    backend._reader.feed_data(response.encode())

    await backend.reset()

    written = backend._writer.write.call_args[0][0].decode()
    cmd = json.loads(written)
    assert cmd["method"] == "reset"


@pytest.mark.asyncio
async def test_reset_raises_when_not_connected():
    """PiBackend.reset() raises if not connected."""
    config = _make_config()
    backend = PiBackend(config)

    with pytest.raises(RuntimeError, match="not connected"):
        await backend.reset()


@pytest.mark.asyncio
async def test_send_raises_on_error_event():
    """send() raises RuntimeError on error events."""
    backend = PiBackend(_make_config())

    events = [{"event": "error", "message": "something broke"}]
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
