"""Agent -- RPC protocol event translation and error propagation."""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from clarvis.agent.agent import Agent, AgentConfig


def _make_config(**overrides) -> AgentConfig:
    defaults = dict(
        session_key="test-voice",
        project_dir=Path("/tmp/clarvis-pi-test"),
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _setup_agent_with_reader(agent, events):
    """Set up an agent with a mock process pre-loaded with event lines on stdout."""
    stdout_reader = asyncio.StreamReader()
    for event in events:
        stdout_reader.feed_data(json.dumps(event).encode() + b"\n")

    process = MagicMock()
    process.stdout = stdout_reader
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stderr = None

    agent._connected = True
    agent._process = process
    agent._reader_task = asyncio.create_task(agent._reader_loop())

    return process


async def _cancel_reader(agent):
    """Cancel and await the agent's reader task."""
    if agent._reader_task and not agent._reader_task.done():
        agent._reader_task.cancel()
        try:
            await agent._reader_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_send_translates_events():
    """send() yields text for text_delta, None for tool_execution_end, returns on agent_end."""
    agent = Agent(_make_config())

    events = [
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Hello"}},
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": " world"}},
        {"type": "tool_execution_start", "toolName": "bash"},
        {"type": "tool_execution_end", "toolName": "bash"},
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "!"}},
        {"type": "agent_end"},
    ]

    process = _setup_agent_with_reader(agent, events)

    chunks = []
    async for chunk in agent.send("test prompt"):
        chunks.append(chunk)

    assert chunks == ["Hello", " world", None, "!"]

    # Verify the command was sent as RPC format
    written = process.stdin.write.call_args[0][0].decode()
    cmd = json.loads(written)
    assert cmd["type"] == "prompt"
    assert cmd["message"] == "test prompt"
    assert "id" in cmd

    await _cancel_reader(agent)


@pytest.mark.asyncio
async def test_reset_sends_command():
    """Agent.reset() sends new_session command to stdin."""
    agent = Agent(_make_config())

    process = _setup_agent_with_reader(agent, [])

    await agent.reset()

    written = process.stdin.write.call_args[0][0].decode()
    cmd = json.loads(written)
    assert cmd["type"] == "new_session"

    await _cancel_reader(agent)


@pytest.mark.asyncio
async def test_reset_noop_when_not_connected():
    """Agent.reset() is a no-op if not connected."""
    agent = Agent(_make_config())
    # Should not raise
    await agent.reset()


@pytest.mark.asyncio
async def test_send_stops_on_process_disconnect():
    """send() stops yielding when process connection is lost mid-stream."""
    agent = Agent(_make_config())

    events = [
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Hi"}},
    ]

    stdout_reader = asyncio.StreamReader()
    for event in events:
        stdout_reader.feed_data(json.dumps(event).encode() + b"\n")
    stdout_reader.feed_eof()  # Simulate process crash

    process = MagicMock()
    process.stdout = stdout_reader
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stderr = None

    agent._connected = True
    agent._process = process
    agent._reader_task = asyncio.create_task(agent._reader_loop())

    chunks = []
    async for chunk in agent.send("test"):
        chunks.append(chunk)

    # Should have received the one text_delta before the process died
    assert chunks == ["Hi"]

    await _cancel_reader(agent)


@pytest.mark.asyncio
async def test_interrupt_sends_abort():
    """Agent.interrupt() sends abort command to stdin."""
    agent = Agent(_make_config())

    process = _setup_agent_with_reader(agent, [])

    await agent.interrupt()

    written = process.stdin.write.call_args[0][0].decode()
    cmd = json.loads(written)
    assert cmd["type"] == "abort"

    await _cancel_reader(agent)


@pytest.mark.asyncio
async def test_extension_ui_auto_confirm():
    """Extension UI confirm requests are auto-approved."""
    agent = Agent(_make_config())

    events = [
        {"type": "extension_ui_request", "ui_type": "confirm", "id": "ext_1"},
        {"type": "agent_end"},
    ]

    process = _setup_agent_with_reader(agent, events)

    chunks = []
    async for chunk in agent.send("test"):
        chunks.append(chunk)

    # Find the extension_ui_response write
    writes = [call[0][0].decode() for call in process.stdin.write.call_args_list]
    responses = [json.loads(w) for w in writes if "extension_ui_response" in w]
    assert len(responses) == 1
    assert responses[0]["type"] == "extension_ui_response"
    assert responses[0]["value"] is True
    assert responses[0]["id"] == "ext_1"

    await _cancel_reader(agent)
