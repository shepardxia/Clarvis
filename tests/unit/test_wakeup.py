"""WakeupManager — prompt building, timer triggers, force reflect."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from clarvis.services.wakeup import WakeupManager


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


@pytest.fixture
def wakeup(agent, state):
    return WakeupManager(agent=agent, state_store=state)


class TestWakeupPrompts:
    def test_pulse_prompt_has_context(self, wakeup):
        prompt = wakeup._build_context_prompt(reason="pulse")
        assert "clear sky" in prompt
        assert "Austin" in prompt

    def test_timer_prompt_includes_timer_info(self, wakeup):
        prompt = wakeup._build_context_prompt(reason="timer", timer_name="laundry", timer_label="Check laundry")
        assert "laundry" in prompt
        assert "Check laundry" in prompt

    def test_reflect_prompt_includes_instruction(self, wakeup):
        prompt = wakeup._build_context_prompt(reason="reflect")
        assert "/reflect" in prompt


class TestWakeupTriggers:
    @pytest.mark.asyncio
    async def test_timer_only_wakes_when_flagged(self, wakeup):
        wakeup._wakeup = AsyncMock()
        await wakeup.on_timer_fired("timer:fired", name="test", label="", wake_clarvis=False)
        wakeup._wakeup.assert_not_called()

    @pytest.mark.asyncio
    async def test_timer_wakes_when_flagged(self, wakeup):
        wakeup._wakeup = AsyncMock()
        await wakeup.on_timer_fired("timer:fired", name="test", label="hello", wake_clarvis=True)
        wakeup._wakeup.assert_called_once_with(reason="timer", timer_name="test", timer_label="hello")

    @pytest.mark.asyncio
    async def test_wakeup_sends_to_agent(self, wakeup):
        response = await wakeup._wakeup(reason="pulse")
        assert response == "I'll check on things."


class TestForceReflect:
    @pytest.mark.asyncio
    async def test_forced_reflect_sends_to_agent(self, wakeup):
        response = await wakeup.on_force_reflect()
        assert response is not None

    @pytest.mark.asyncio
    async def test_forced_reflect_prompt_has_instruction(self):
        """on_force_reflect sends prompt with /reflect instruction."""
        agent_received = []

        async def capture_send(text):
            agent_received.append(text)
            yield "Reflected."

        mock_agent = MagicMock()
        mock_agent.send = capture_send
        mock_agent._currently_sending = False

        wm = WakeupManager(agent=mock_agent)
        response = await wm.on_force_reflect()

        assert response == "Reflected."
        assert len(agent_received) == 1
        assert "/reflect" in agent_received[0]


class TestCurrentlySending:
    @pytest.mark.asyncio
    async def test_flag_set_during_send(self):
        """_currently_sending is True while send is in progress."""
        from clarvis.agent.agent import Agent
        from clarvis.agent.backends.pi import PiConfig

        backend = AsyncMock()
        seen_flag = []

        async def fake_send(text):
            seen_flag.append(agent._currently_sending)
            yield "chunk"

        backend.send = fake_send

        agent = Agent(PiConfig(session_key="test", project_dir=Path("/tmp/test-agent")))
        agent._backend = backend
        agent._connected = True

        assert agent._currently_sending is False
        async for _ in agent.send("hello"):
            pass
        assert agent._currently_sending is False
        assert seen_flag == [True]
