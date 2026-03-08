"""Nudge — prompt building and agent delivery."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from clarvis.services.wakeup import _build_prompt, nudge


@pytest.fixture
def agent():
    a = AsyncMock()

    async def fake_send(text):
        yield "I'll check on things."

    a.send = fake_send
    a._currently_sending = False
    return a


@pytest.fixture
def state():
    s = MagicMock()

    def get_state(key):
        data = {
            "status": "idle",
            "weather": {"description": "clear sky", "temperature": 68},
            "location": {"city": "Austin"},
        }
        return data.get(key)

    s.get = get_state
    return s


class TestNudgePrompts:
    def test_pulse_prompt_has_context(self, state):
        prompt = _build_prompt(reason="pulse", state_store=state)
        assert "clear sky" in prompt
        assert "Austin" in prompt

    def test_timer_prompt_includes_timer_info(self, state):
        prompt = _build_prompt(reason="timer", state_store=state, timer_name="laundry", timer_label="Check laundry")
        assert "laundry" in prompt
        assert "Check laundry" in prompt

    def test_reflect_prompt_includes_instruction(self, state):
        prompt = _build_prompt(reason="reflect", state_store=state)
        assert "/reflect" in prompt


class TestNudgeDelivery:
    @pytest.mark.asyncio
    async def test_nudge_sends_to_agent(self, agent, state):
        response = await nudge(agent, reason="pulse", state_store=state)
        assert response == "I'll check on things."

    @pytest.mark.asyncio
    async def test_nudge_reflect_has_instruction(self):
        """Reflect nudge sends prompt with /reflect instruction."""
        agent_received = []

        async def capture_send(text):
            agent_received.append(text)
            yield "Reflected."

        mock_agent = MagicMock()
        mock_agent.send = capture_send
        mock_agent._currently_sending = False

        response = await nudge(mock_agent, reason="reflect")

        assert response == "Reflected."
        assert len(agent_received) == 1
        assert "/reflect" in agent_received[0]


class TestCurrentlySending:
    @pytest.mark.asyncio
    async def test_flag_set_during_send(self):
        """_currently_sending is True while send is in progress."""
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

        assert agent._currently_sending is False
        seen_flag = []
        async for chunk in agent.send("hello"):
            seen_flag.append(agent._currently_sending)
        assert agent._currently_sending is False
        assert seen_flag == [True]

        if agent._reader_task and not agent._reader_task.done():
            agent._reader_task.cancel()
            try:
                await agent._reader_task
            except asyncio.CancelledError:
                pass
