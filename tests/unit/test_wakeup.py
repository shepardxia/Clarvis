"""WakeupManager tests."""

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
def consolidator():
    c = MagicMock()
    c.get_memory_context.return_value = "# Memory\n- User likes jazz"
    return c


@pytest.fixture
def wakeup(agent, state, consolidator):
    return WakeupManager(
        agent=agent,
        state_store=state,
        memory_service=None,
        consolidator=consolidator,
    )


class TestWakeupPrompts:
    def test_pulse_prompt_has_context(self, wakeup):
        prompt = wakeup._build_context_prompt(reason="pulse")
        assert "pulse" in prompt.lower()
        assert "UTC" in prompt
        assert "clear sky" in prompt
        assert "Austin" in prompt
        assert "jazz" in prompt

    def test_timer_prompt_includes_timer_info(self, wakeup):
        prompt = wakeup._build_context_prompt(reason="timer", timer_name="laundry", timer_label="Check laundry")
        assert "laundry" in prompt
        assert "Check laundry" in prompt

    def test_consolidation_prompt(self, wakeup):
        prompt = wakeup._build_context_prompt(reason="consolidation", session_key="voice")
        assert "consolidation" in prompt.lower()
        assert "voice" in prompt

    def test_no_state_graceful(self):
        wakeup = WakeupManager(agent=AsyncMock(), state_store=None)
        prompt = wakeup._build_context_prompt(reason="pulse")
        assert "pulse" in prompt.lower()  # Still works without state


class TestWakeupTriggers:
    @pytest.mark.asyncio
    async def test_timer_only_wakes_when_flagged(self, wakeup):
        """on_timer_fired with wake_clarvis=False does nothing."""
        wakeup._wakeup = AsyncMock()
        await wakeup.on_timer_fired("timer:fired", name="test", label="", wake_clarvis=False)
        wakeup._wakeup.assert_not_called()

    @pytest.mark.asyncio
    async def test_timer_wakes_when_flagged(self, wakeup):
        """on_timer_fired with wake_clarvis=True triggers wakeup."""
        wakeup._wakeup = AsyncMock()
        await wakeup.on_timer_fired("timer:fired", name="test", label="hello", wake_clarvis=True)
        wakeup._wakeup.assert_called_once_with(reason="timer", timer_name="test", timer_label="hello")

    @pytest.mark.asyncio
    async def test_pulse_triggers_wakeup(self, wakeup):
        wakeup._wakeup = AsyncMock()
        await wakeup.on_pulse()
        wakeup._wakeup.assert_called_once_with(reason="pulse")

    @pytest.mark.asyncio
    async def test_wakeup_sends_to_agent(self, wakeup):
        """_wakeup sends the prompt to the agent and returns response."""
        response = await wakeup._wakeup(reason="pulse")
        assert response == "I'll check on things."
