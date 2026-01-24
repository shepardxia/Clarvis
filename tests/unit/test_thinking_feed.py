"""Tests for thinking feed service."""

import json
import pytest
from pathlib import Path

from clarvis.services.thinking_feed import (
    parse_jsonl_line,
    extract_thinking_blocks,
    is_session_stop_event,
    extract_project_from_path,
    SessionState,
    SessionStatus,
    ThinkingBlock,
)


class TestParseJsonlLine:
    """Tests for JSONL line parsing."""

    def test_valid_json(self):
        line = '{"type": "assistant", "message": "hello"}'
        result = parse_jsonl_line(line)
        assert result == {"type": "assistant", "message": "hello"}

    def test_empty_line(self):
        assert parse_jsonl_line("") is None
        assert parse_jsonl_line("   ") is None

    def test_invalid_json(self):
        assert parse_jsonl_line("{invalid}") is None
        assert parse_jsonl_line("not json at all") is None

    def test_incomplete_json(self):
        assert parse_jsonl_line('{"type": "assistant"') is None


class TestExtractThinkingBlocks:
    """Tests for thinking block extraction."""

    def test_extract_from_assistant_message(self, sample_jsonl_entry):
        """Should extract thinking blocks from assistant messages."""
        blocks = extract_thinking_blocks(sample_jsonl_entry)
        assert len(blocks) == 1
        assert blocks[0].text == "Let me analyze this problem..."
        assert blocks[0].session_id == "test-session"

    def test_skip_non_assistant_messages(self):
        """Should skip non-assistant messages."""
        entry = {"type": "user", "message": {"content": "hello"}}
        blocks = extract_thinking_blocks(entry)
        assert len(blocks) == 0

    def test_skip_sidechain_messages(self, sample_jsonl_entry):
        """Should skip sidechain (parallel exploration) messages."""
        sample_jsonl_entry["isSidechain"] = True
        blocks = extract_thinking_blocks(sample_jsonl_entry)
        assert len(blocks) == 0

    def test_string_content_no_thinking(self):
        """Messages with string content have no thinking blocks."""
        entry = {
            "type": "assistant",
            "message": {"content": "Just a text response"},
        }
        blocks = extract_thinking_blocks(entry)
        assert len(blocks) == 0

    def test_multiple_thinking_blocks(self):
        """Should extract multiple thinking blocks from one message."""
        entry = {
            "type": "assistant",
            "sessionId": "multi-session",
            "timestamp": "2026-01-23T10:00:00Z",
            "uuid": "msg-multi",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "First thought"},
                    {"type": "text", "text": "Response part 1"},
                    {"type": "thinking", "thinking": "Second thought"},
                    {"type": "text", "text": "Response part 2"},
                ]
            },
        }
        blocks = extract_thinking_blocks(entry)
        assert len(blocks) == 2
        assert blocks[0].text == "First thought"
        assert blocks[1].text == "Second thought"


class TestIsSessionStopEvent:
    """Tests for stop event detection."""

    def test_stop_event(self):
        entry = {
            "type": "progress",
            "data": {"type": "hook_progress", "hookEvent": "Stop"},
        }
        assert is_session_stop_event(entry) is True

    def test_non_stop_event(self):
        entry = {
            "type": "progress",
            "data": {"type": "hook_progress", "hookEvent": "PreToolUse"},
        }
        assert is_session_stop_event(entry) is False

    def test_non_progress_type(self):
        entry = {"type": "assistant", "message": "hello"}
        assert is_session_stop_event(entry) is False


class TestExtractProjectFromPath:
    """Tests for project path extraction."""

    def test_standard_path(self):
        path = Path("/Users/user/.claude/projects/-Users-user-myproject/session.jsonl")
        name, project_path = extract_project_from_path(path)
        assert name == "myproject"
        assert project_path == "/Users/user/myproject"

    def test_nested_path(self):
        path = Path("/home/.claude/projects/-home-user-code-repo/session.jsonl")
        name, project_path = extract_project_from_path(path)
        assert name == "repo"


class TestSessionState:
    """Tests for SessionState management."""

    def test_add_thought(self):
        session = SessionState(
            session_id="test",
            project="myproject",
            project_path="/path",
            file_path=Path("/tmp/test.jsonl"),
        )
        thought = ThinkingBlock(
            text="Test thought",
            timestamp="2026-01-23T10:00:00Z",
            session_id="test",
        )
        session.add_thought(thought)

        assert len(session.thoughts) == 1
        assert session.status == SessionStatus.ACTIVE

    def test_max_thoughts_limit(self):
        """Should keep only max_thoughts most recent."""
        session = SessionState(
            session_id="test",
            project="myproject",
            project_path="/path",
            file_path=Path("/tmp/test.jsonl"),
        )

        # Add 60 thoughts with max_thoughts=50
        for i in range(60):
            thought = ThinkingBlock(
                text=f"Thought {i}",
                timestamp=f"2026-01-23T10:{i:02d}:00Z",
                session_id="test",
            )
            session.add_thought(thought, max_thoughts=50)

        assert len(session.thoughts) == 50
        # Should have kept the most recent (10-59)
        assert session.thoughts[0].text == "Thought 10"
        assert session.thoughts[-1].text == "Thought 59"

    def test_get_recent_thoughts(self):
        session = SessionState(
            session_id="test",
            project="myproject",
            project_path="/path",
            file_path=Path("/tmp/test.jsonl"),
        )

        for i in range(10):
            thought = ThinkingBlock(
                text=f"Thought {i}",
                timestamp=f"2026-01-23T10:{i:02d}:00Z",
                session_id="test",
            )
            session.add_thought(thought)

        recent = session.get_recent_thoughts(limit=3)
        assert len(recent) == 3
        assert recent[-1].text == "Thought 9"

    def test_get_recent_thoughts_empty(self):
        """Should return empty list when no thoughts."""
        session = SessionState(
            session_id="test",
            project="myproject",
            project_path="/path",
            file_path=Path("/tmp/test.jsonl"),
        )
        assert session.get_recent_thoughts() == []

    def test_initial_state(self):
        """Should initialize with correct default values."""
        session = SessionState(
            session_id="test",
            project="myproject",
            project_path="/path",
            file_path=Path("/tmp/test.jsonl"),
        )
        assert session.status == SessionStatus.ACTIVE
        assert session.thoughts == []
        assert session.file_position == 0


class TestThinkingBlock:
    """Tests for ThinkingBlock dataclass."""

    def test_default_message_id(self):
        """Should have empty string as default message_id."""
        block = ThinkingBlock(
            text="My thought",
            timestamp="2024-01-15T10:00:00Z",
            session_id="sess-123",
        )
        assert block.message_id == ""

    def test_all_fields(self):
        """Should create block with all fields."""
        block = ThinkingBlock(
            text="My thought",
            timestamp="2024-01-15T10:00:00Z",
            session_id="sess-123",
            message_id="msg-456:0",
        )
        assert block.text == "My thought"
        assert block.timestamp == "2024-01-15T10:00:00Z"
        assert block.session_id == "sess-123"
        assert block.message_id == "msg-456:0"


class TestSessionStatus:
    """Tests for SessionStatus enum."""

    def test_status_values(self):
        """Should have expected status values."""
        assert SessionStatus.ACTIVE.value == "active"
        assert SessionStatus.IDLE.value == "idle"
        assert SessionStatus.ENDED.value == "ended"


class TestEdgeCases:
    """Additional edge case tests."""

    def test_extract_thinking_blocks_missing_message(self):
        """Should handle missing message field."""
        entry = {"type": "assistant"}
        assert extract_thinking_blocks(entry) == []

    def test_extract_thinking_blocks_missing_content(self):
        """Should handle missing content field."""
        entry = {"type": "assistant", "message": {}}
        assert extract_thinking_blocks(entry) == []

    def test_extract_thinking_blocks_empty_thinking_text(self):
        """Should skip thinking blocks with empty text."""
        entry = {
            "type": "assistant",
            "sessionId": "sess-123",
            "timestamp": "2024-01-15T10:00:00Z",
            "uuid": "msg-456",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": ""},
                    {"type": "thinking", "thinking": "Has content"},
                ]
            }
        }
        blocks = extract_thinking_blocks(entry)
        assert len(blocks) == 1
        assert blocks[0].text == "Has content"

    def test_is_session_stop_missing_data(self):
        """Should handle missing data field."""
        entry = {"type": "progress"}
        assert is_session_stop_event(entry) is False

    def test_is_session_stop_non_hook_progress(self):
        """Should return False for non-hook_progress data."""
        entry = {
            "type": "progress",
            "data": {
                "type": "other_progress",
                "hookEvent": "Stop"
            }
        }
        assert is_session_stop_event(entry) is False

    def test_parse_jsonl_whitespace_trimmed(self):
        """Should trim whitespace before parsing."""
        line = '  {"key": "value"}  \n'
        result = parse_jsonl_line(line)
        assert result == {"key": "value"}

    def test_extract_project_simple_slug(self):
        """Should handle simple project slug without leading dash."""
        file_path = Path("/Users/test/.claude/projects/simple-project/session.jsonl")
        name, path = extract_project_from_path(file_path)
        assert name == "project"
        assert path == "simple/project"
