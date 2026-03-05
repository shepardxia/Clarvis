"""WakeupManager — prompt building, memory context, timer/consolidation triggers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from clarvis.services.wakeup import WakeupManager


@pytest.fixture
def agent():
    a = AsyncMock()

    async def fake_send(text):
        yield "I'll check on things."

    a.send = fake_send
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
    return WakeupManager(agent=agent, state_store=state, memory_service=None)


class TestWakeupPrompts:
    def test_pulse_prompt_has_context(self, wakeup):
        prompt = wakeup._build_context_prompt(reason="pulse")
        assert "UTC" in prompt
        assert "clear sky" in prompt
        assert "Austin" in prompt

    def test_prompt_includes_memory_context(self, wakeup):
        prompt = wakeup._build_context_prompt(reason="pulse", memory_context="# Memory\n- User likes jazz")
        assert "jazz" in prompt

    def test_timer_prompt_includes_timer_info(self, wakeup):
        prompt = wakeup._build_context_prompt(reason="timer", timer_name="laundry", timer_label="Check laundry")
        assert "laundry" in prompt
        assert "Check laundry" in prompt

    def test_consolidation_prompt(self, wakeup):
        prompt = wakeup._build_context_prompt(reason="consolidation", session_key="voice")
        assert "consolidation" in prompt.lower()
        assert "voice" in prompt


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
