"""WakeupManager — prompt building, memory context, timer/nudge triggers."""

import asyncio
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
def accumulator():
    """Mock ContextAccumulator with pending sessions."""
    acc = MagicMock()
    acc.get_pending.return_value = {
        "sessions_since_last": [
            {
                "session_id": "abc123",
                "project": "clarvis-suite",
                "project_path": "/Users/test/clarvis-suite",
                "transcript_path": "/tmp/fake_transcript.jsonl",
                "timestamp": "2026-03-06T10:00:00+00:00",
                "preview": "U: Fix the retain bug\nA: I'll look into it...",
            },
        ],
        "staged_items": [],
        "last_check_in": "2026-03-06T08:00:00+00:00",
    }
    return acc


@pytest.fixture
def wakeup(agent, state):
    return WakeupManager(agent=agent, state_store=state, memory_service=None)


class TestWakeupPrompts:
    def test_pulse_prompt_has_context(self, wakeup):
        prompt = wakeup._build_context_prompt(reason="pulse")
        assert "clear sky" in prompt
        assert "Austin" in prompt

    def test_prompt_includes_memory_context(self, wakeup):
        prompt = wakeup._build_context_prompt(reason="pulse", memory_context="# Memory\n- User likes jazz")
        assert "jazz" in prompt

    def test_timer_prompt_includes_timer_info(self, wakeup):
        prompt = wakeup._build_context_prompt(reason="timer", timer_name="laundry", timer_label="Check laundry")
        assert "laundry" in prompt
        assert "Check laundry" in prompt

    def test_nudge_prompt_includes_sessions(self, wakeup, accumulator):
        wakeup._accumulator = accumulator
        prompt = wakeup._build_context_prompt(
            reason="nudge",
            pending_sessions=1,
            session_previews="clarvis-suite:\n    U: Fix the retain bug...",
        )
        assert "nudge" in prompt.lower()
        assert "clarvis-suite" in prompt

    def test_nudge_prompt_no_fact_count(self, wakeup):
        """Nudge prompt should not include unconsolidated fact count."""
        prompt = wakeup._build_context_prompt(
            reason="nudge",
            pending_sessions=1,
            session_previews="test preview",
        )
        assert "unconsolidated" not in prompt.lower()

    def test_forced_reflect_prompt_includes_instruction(self, wakeup):
        prompt = wakeup._build_context_prompt(
            reason="nudge — reflect",
            pending_sessions=1,
            session_previews="test preview",
            force_reflect=True,
        )
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


class TestNudge:
    @pytest.mark.asyncio
    async def test_on_nudge_sends_to_agent(self, agent, state, accumulator):
        wm = WakeupManager(
            agent=agent,
            state_store=state,
            memory_service=None,
            accumulator=accumulator,
        )
        wm._is_quiet_hours = lambda: False
        response = await wm.on_nudge()
        assert response is not None
        accumulator.mark_checked_in.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_nudge_skips_when_agent_busy(self, state, accumulator):
        busy_agent = AsyncMock()
        busy_agent._currently_sending = True

        wm = WakeupManager(
            agent=busy_agent,
            state_store=state,
            memory_service=None,
            accumulator=accumulator,
        )
        response = await wm.on_nudge()
        assert response is None
        accumulator.mark_checked_in.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_nudge_skips_no_pending(self, agent, state):
        empty_acc = MagicMock()
        empty_acc.get_pending.return_value = {
            "sessions_since_last": [],
            "staged_items": [],
            "last_check_in": "2026-03-06T08:00:00+00:00",
        }
        wm = WakeupManager(
            agent=agent,
            state_store=state,
            memory_service=None,
            accumulator=empty_acc,
        )
        response = await wm.on_nudge()
        assert response is None
        empty_acc.mark_checked_in.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_nudge_skips_quiet_hours(self, agent, accumulator):
        wm = WakeupManager(agent=agent, accumulator=accumulator)
        wm._is_quiet_hours = lambda: True
        response = await wm.on_nudge()
        assert response is None
        accumulator.mark_checked_in.assert_not_called()


class TestForceReflect:
    @pytest.mark.asyncio
    async def test_forced_reflect_sends_nudge(self, agent, state, accumulator):
        wm = WakeupManager(
            agent=agent,
            state_store=state,
            memory_service=None,
            accumulator=accumulator,
        )
        response = await wm.on_force_reflect()
        assert response is not None
        accumulator.mark_checked_in.assert_called_once()

    @pytest.mark.asyncio
    async def test_forced_reflect_bypasses_quiet_hours(self, agent, accumulator):
        wm = WakeupManager(agent=agent, accumulator=accumulator)
        wm._is_quiet_hours = lambda: True
        response = await wm.on_force_reflect()
        assert response is not None
        accumulator.mark_checked_in.assert_called_once()


class TestNudgeIntegration:
    @pytest.mark.asyncio
    async def test_full_nudge_flow(self):
        """Nudge fires -> context built -> agent receives -> accumulator cleared."""
        agent_received = []

        async def capture_send(text):
            agent_received.append(text)
            yield "Extracted 3 facts."

        mock_agent = MagicMock()
        mock_agent.send = capture_send
        mock_agent._currently_sending = False

        mock_state = MagicMock()
        mock_state.get.return_value = None

        mock_acc = MagicMock()
        mock_acc.get_pending.return_value = {
            "sessions_since_last": [
                {
                    "session_id": "sess1",
                    "project": "my-project",
                    "preview": "U: What is X?\nA: X is...",
                    "timestamp": "2026-03-06T10:00:00+00:00",
                },
                {
                    "session_id": "sess2",
                    "project": "my-project",
                    "preview": "U: Fix bug Y\nA: Done.",
                    "timestamp": "2026-03-06T11:00:00+00:00",
                },
            ],
            "staged_items": [],
            "last_check_in": "2026-03-06T08:00:00+00:00",
        }

        wm = WakeupManager(
            agent=mock_agent,
            state_store=mock_state,
            memory_service=None,
            accumulator=mock_acc,
        )
        wm._is_quiet_hours = lambda: False
        response = await wm.on_nudge()

        assert response == "Extracted 3 facts."
        assert len(agent_received) == 1
        assert "my-project" in agent_received[0]
        mock_acc.mark_checked_in.assert_called_once()

    @pytest.mark.asyncio
    async def test_forced_reflect_includes_instruction(self):
        """on_force_reflect sends nudge with reflect instruction."""
        agent_received = []

        async def capture_send(text):
            agent_received.append(text)
            yield "Reflected."

        mock_agent = MagicMock()
        mock_agent.send = capture_send
        mock_agent._currently_sending = False

        mock_acc = MagicMock()
        mock_acc.get_pending.return_value = {
            "sessions_since_last": [
                {"session_id": "s1", "project": "proj", "preview": "hello"},
            ],
            "staged_items": [],
            "last_check_in": "2026-03-06T08:00:00+00:00",
        }

        wm = WakeupManager(agent=mock_agent, accumulator=mock_acc)
        response = await wm.on_force_reflect()

        assert response == "Reflected."
        assert len(agent_received) == 1
        assert "/reflect" in agent_received[0]
        mock_acc.mark_checked_in.assert_called_once()


class TestCurrentlySending:
    @pytest.mark.asyncio
    async def test_flag_set_during_send(self):
        """_currently_sending is True while send is in progress."""
        from clarvis.agent.agent import Agent, SessionProfile

        profile = SessionProfile(
            project_dir=Path("/tmp/test-agent"),
            session_id_path=Path("/tmp/test-agent/session_id"),
            allowed_tools=[],
            mcp_port=7778,
        )

        backend = AsyncMock()
        backend.get_session_id = MagicMock(return_value=None)
        seen_flag = []

        async def fake_send(text):
            seen_flag.append(agent._currently_sending)
            yield "chunk"

        backend.send = fake_send

        agent = Agent(
            session_key="test",
            profile=profile,
            event_loop=asyncio.get_running_loop(),
            backend=backend,
        )
        agent._connected = True

        assert agent._currently_sending is False
        async for _ in agent.send("hello"):
            pass
        assert agent._currently_sending is False
        assert seen_flag == [True]
