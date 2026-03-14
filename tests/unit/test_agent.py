"""Agent -- RPC protocol event forwarding and error propagation."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from clarvis.agent.agent import Agent, AgentConfig, auto_approve_extension_ui


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
async def test_send_yields_event_dicts():
    """send() yields raw event dicts including text_delta, tool boundaries, and agent_end."""
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

    received = []
    async for event in agent.send("test prompt"):
        received.append(event)

    # All events yielded verbatim (including agent_end)
    assert len(received) == 6
    assert received[0]["type"] == "message_update"
    assert received[0]["assistantMessageEvent"]["delta"] == "Hello"
    assert received[2]["type"] == "tool_execution_start"
    assert received[3]["type"] == "tool_execution_end"
    assert received[5]["type"] == "agent_end"

    # Verify the command was sent as RPC format
    written = process.stdin.write.call_args[0][0].decode()
    cmd = json.loads(written)
    assert cmd["type"] == "prompt"
    assert cmd["message"] == "test prompt"
    assert "id" in cmd

    await _cancel_reader(agent)


def _make_reset_agent(tmp_path, *, connected=True, context=None):
    """Create an agent with mocked disconnect/connect for reset tests."""
    agent = Agent(_make_config(project_dir=tmp_path))
    agent.disconnect = AsyncMock()
    agent.connect = AsyncMock()
    agent._connected = connected
    if context is not None:
        agent.context = context
    return agent


@pytest.mark.asyncio
async def test_reset_moves_session_to_inbox(tmp_path):
    """Agent.reset() moves the session file to staging/inbox/ with a timestamped name."""
    agent = _make_reset_agent(tmp_path)

    # Create a session file
    session_file = tmp_path / "pi-session.jsonl"
    session_file.write_text('{"type":"session"}\n')

    await agent.reset()

    # Session file should be gone from project dir
    assert not session_file.exists()

    # Should be in staging/inbox/ with session_ prefix
    from clarvis.core.paths import STAGING_INBOX

    inbox_files = list(STAGING_INBOX.glob("session_test-voice_*.jsonl"))
    assert len(inbox_files) == 1

    # Cleanup
    inbox_files[0].unlink()


@pytest.mark.asyncio
async def test_reset_reconnects_when_was_connected(tmp_path):
    """Agent.reset() reconnects if the agent was previously connected."""
    agent = _make_reset_agent(tmp_path, connected=True)
    await agent.reset()
    agent.disconnect.assert_awaited_once()
    agent.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_no_reconnect_when_not_connected(tmp_path):
    """Agent.reset() does not connect if the agent was not previously connected."""
    agent = _make_reset_agent(tmp_path, connected=False)
    await agent.reset()
    agent.disconnect.assert_awaited_once()
    agent.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_noop_no_file(tmp_path):
    """Agent.reset() works fine when no session file exists."""
    agent = _make_reset_agent(tmp_path)
    # No session file — should not raise
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

    received = []
    async for event in agent.send("test"):
        received.append(event)

    # Should have received the one text_delta before the process died
    assert len(received) == 1
    assert received[0]["assistantMessageEvent"]["delta"] == "Hi"

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
async def test_extension_ui_yielded_not_consumed():
    """Extension UI requests are yielded as events, not auto-consumed."""
    agent = Agent(_make_config())

    events = [
        {"type": "extension_ui_request", "ui_type": "confirm", "id": "ext_1"},
        {"type": "agent_end"},
    ]

    _setup_agent_with_reader(agent, events)

    received = []
    async for event in agent.send("test"):
        received.append(event)

    # Extension UI request should be yielded to the caller
    assert any(e.get("type") == "extension_ui_request" for e in received)
    assert any(e.get("type") == "agent_end" for e in received)

    await _cancel_reader(agent)


@pytest.mark.asyncio
async def test_auto_approve_extension_ui_confirm():
    """auto_approve_extension_ui sends confirm response."""
    agent = Agent(_make_config())
    process = _setup_agent_with_reader(agent, [])

    event = {"type": "extension_ui_request", "ui_type": "confirm", "id": "ext_1"}
    auto_approve_extension_ui(agent, event)

    writes = [call[0][0].decode() for call in process.stdin.write.call_args_list]
    responses = [json.loads(w) for w in writes if "extension_ui_response" in w]
    assert len(responses) == 1
    assert responses[0]["type"] == "extension_ui_response"
    assert responses[0]["value"] is True
    assert responses[0]["id"] == "ext_1"

    await _cancel_reader(agent)


@pytest.mark.asyncio
async def test_auto_approve_extension_ui_select():
    """auto_approve_extension_ui picks first option for select."""
    agent = Agent(_make_config())
    process = _setup_agent_with_reader(agent, [])

    event = {"type": "extension_ui_request", "ui_type": "select", "id": "ext_2", "options": ["a", "b"]}
    auto_approve_extension_ui(agent, event)

    writes = [call[0][0].decode() for call in process.stdin.write.call_args_list]
    responses = [json.loads(w) for w in writes if "extension_ui_response" in w]
    assert len(responses) == 1
    assert responses[0]["value"] == "a"

    await _cancel_reader(agent)
