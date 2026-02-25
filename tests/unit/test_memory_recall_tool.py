"""Tests for the memory MCP tool helpers."""

import json
from pathlib import Path

from clarvis.channels.memory_context import read_recent_transcript
from clarvis.mcp.memory_tools import _fmt_facts

# -- read_recent_transcript ------------------------------------------------


def test_read_recent_transcript_returns_messages(tmp_path: Path):
    """Should parse JSONL and return role-mapped messages."""
    path = tmp_path / "transcript.jsonl"
    path.write_text(
        json.dumps({"sender": "alice", "content": "hi"})
        + "\n"
        + json.dumps({"sender": "clarvis", "content": "hello"})
        + "\n"
    )
    result = read_recent_transcript(path)
    assert len(result) == 2
    assert result[0] == {"role": "user", "content": "hi"}
    assert result[1] == {"role": "assistant", "content": "hello"}


def test_read_recent_transcript_missing_file():
    """Should return empty list for non-existent file."""
    result = read_recent_transcript(Path("/tmp/nonexistent_xyz.jsonl"))
    assert result == []


# -- _fmt_facts ---------------------------------------------------------------


def test_fmt_facts_with_data():
    """Should format facts with IDs, types, and content."""
    facts = [
        {"id": "abc-12345678", "fact_type": "world", "content": "user is a developer"},
        {"id": "def-12345678", "fact_type": "opinion", "content": "prefers Python", "confidence": 0.8},
    ]
    formatted = _fmt_facts(facts)
    assert "[world]" in formatted
    assert "user is a developer" in formatted
    assert "[opinion]" in formatted
    assert "prefers Python" in formatted
    assert "confidence: 0.8" in formatted
    assert "id:abc-1234567" in formatted


def test_fmt_facts_empty():
    """Should return 'No results.' for empty list."""
    assert _fmt_facts([]) == "No results."


def test_fmt_facts_missing_fields():
    """Should handle facts with missing fields gracefully."""
    facts = [{"id": "x", "content": "just content"}]
    formatted = _fmt_facts(facts)
    assert "just content" in formatted
