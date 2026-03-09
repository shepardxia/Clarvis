"""Nudge -- prompt building and agent delivery."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from clarvis.services.wakeup import _build_reason_prefix, nudge


@pytest.fixture
def agent():
    a = AsyncMock()

    async def fake_send(text, *, owner=""):
        yield {
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_delta", "delta": "I'll check on things."},
        }
        yield {"type": "agent_end"}

    a.send = fake_send
    a.context = None
    a.is_busy = False
    a._send_command = MagicMock()
    return a


class TestNudgePrompts:
    def test_timer_prompt_includes_timer_info(self):
        prefix = _build_reason_prefix(reason="timer", timer_name="laundry", timer_label="Check laundry")
        assert "laundry" in prefix
        assert "Check laundry" in prefix

    def test_reflect_prompt_includes_instruction(self):
        prefix = _build_reason_prefix(reason="reflect")
        assert "/reflect" in prefix


class TestNudgeDelivery:
    @pytest.mark.asyncio
    async def test_nudge_sends_to_agent(self, agent):
        response = await nudge(agent, reason="pulse")
        assert response == "I'll check on things."

    @pytest.mark.asyncio
    async def test_nudge_reflect_has_instruction(self):
        """Reflect nudge sends prompt with /reflect instruction."""
        agent_received = []

        async def capture_send(text, *, owner=""):
            agent_received.append(text)
            yield {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Reflected."}}
            yield {"type": "agent_end"}

        mock_agent = MagicMock()
        mock_agent.send = capture_send
        mock_agent.context = None
        mock_agent.is_busy = False
        mock_agent._send_command = MagicMock()

        response = await nudge(mock_agent, reason="reflect")

        assert response == "Reflected."
        assert len(agent_received) == 1
        assert "/reflect" in agent_received[0]


class TestSendOwner:
    @pytest.mark.asyncio
    async def test_owner_set_during_send(self):
        """_send_owner is set while send is in progress."""
        import asyncio
        import json
        from pathlib import Path
        from unittest.mock import MagicMock

        from clarvis.agent.agent import Agent, AgentConfig

        agent = Agent(AgentConfig(session_key="test", project_dir=Path("/tmp/test-agent")))

        # Set up mock process with events on stdout
        stdout_reader = asyncio.StreamReader()
        events = [
            {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "chunk"}},
            {"type": "agent_end"},
        ]
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

        assert agent._send_owner is None
        seen_owner = []
        async for event in agent.send("hello", owner="test"):
            seen_owner.append(agent._send_owner)
        assert agent._send_owner is None
        assert seen_owner == ["test", "test"]

        if agent._reader_task and not agent._reader_task.done():
            agent._reader_task.cancel()
            try:
                await agent._reader_task
            except asyncio.CancelledError:
                pass
