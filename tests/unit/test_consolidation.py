"""Memory consolidation tests."""

from unittest.mock import AsyncMock, patch

import pytest

from clarvis.agent.memory.consolidation import ConversationConsolidator


@pytest.fixture
def consolidator(tmp_path):
    memory_service = AsyncMock()
    memory_service.add = AsyncMock(return_value={"status": "ok"})
    return ConversationConsolidator(
        memory_service=memory_service,
        model="claude-haiku-4-5-20251001",
        threshold=5,
        keep_recent=2,
        memory_dir=tmp_path,
    )


class TestConsolidation:
    @pytest.mark.asyncio
    async def test_below_threshold_returns_none(self, consolidator):
        """Don't consolidate if below threshold."""
        messages = [{"role": "user", "content": "hi"}] * 3
        result = await consolidator.maybe_consolidate("test", messages)
        assert result is None

    @pytest.mark.asyncio
    async def test_above_threshold_calls_llm(self, consolidator):
        """Above threshold triggers consolidation."""
        messages = [{"role": "user", "content": f"message {i}"} for i in range(10)]
        fake_result = {
            "history_entry": "User sent 10 messages",
            "memory_update": "# Memory\n- User likes testing",
        }
        with patch.object(consolidator, "_call_llm", return_value=fake_result):
            result = await consolidator.maybe_consolidate("test", messages)
            assert result is not None
            assert result["history_entry"] == "User sent 10 messages"

    @pytest.mark.asyncio
    async def test_writes_memory_file(self, consolidator, tmp_path):
        """Consolidation updates MEMORY.md."""
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        fake_result = {
            "history_entry": "summary",
            "memory_update": "# Updated Memory\n- New fact",
        }
        with patch.object(consolidator, "_call_llm", return_value=fake_result):
            await consolidator.maybe_consolidate("test", messages)
            content = (tmp_path / "MEMORY.md").read_text()
            assert "New fact" in content

    @pytest.mark.asyncio
    async def test_feeds_memory(self, consolidator):
        """History entry is added to memory via memory_service."""
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        fake_result = {
            "history_entry": "Summary of conversation",
            "memory_update": "# Memory",
        }
        with patch.object(consolidator, "_call_llm", return_value=fake_result):
            await consolidator.maybe_consolidate("test", messages)
            consolidator._memory_service.add.assert_called_once_with("Summary of conversation", dataset="parletre")

    @pytest.mark.asyncio
    async def test_watermark_prevents_reprocessing(self, consolidator):
        """After consolidation, same messages don't trigger again."""
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        fake_result = {"history_entry": "s", "memory_update": "m"}
        with patch.object(consolidator, "_call_llm", return_value=fake_result):
            result1 = await consolidator.maybe_consolidate("test", messages)
            assert result1 is not None
            # Same messages — should not trigger again
            result2 = await consolidator.maybe_consolidate("test", messages)
            assert result2 is None

    def test_get_memory_context_empty(self, consolidator):
        """Empty memory returns empty string."""
        assert consolidator.get_memory_context() == ""

    def test_get_memory_context_with_content(self, consolidator, tmp_path):
        """Returns content of MEMORY.md."""
        (tmp_path / "MEMORY.md").write_text("# Existing memory")
        assert consolidator.get_memory_context() == "# Existing memory"

    def test_format_conversation(self, consolidator):
        """Messages are formatted as ROLE: content."""
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        text = consolidator._format_conversation(messages)
        assert "USER: hello" in text
        assert "ASSISTANT: hi there" in text
