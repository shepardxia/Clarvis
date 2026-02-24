"""Tests for the memory_recall MCP tool and its helpers."""

import json
from pathlib import Path

from clarvis.mcp.memory_tools import (
    _format_recall_result,
    _read_recent_transcript,
)

# -- _read_recent_transcript ------------------------------------------------


def test_read_recent_transcript_returns_messages(tmp_path: Path):
    """Should parse JSONL and return role-mapped messages."""
    path = tmp_path / "transcript.jsonl"
    path.write_text(
        json.dumps({"sender": "alice", "content": "hi"})
        + "\n"
        + json.dumps({"sender": "clarvis", "content": "hello"})
        + "\n"
    )
    result = _read_recent_transcript(path)
    assert len(result) == 2
    assert result[0] == {"role": "user", "content": "hi"}
    assert result[1] == {"role": "assistant", "content": "hello"}


def test_read_recent_transcript_missing_file():
    """Should return empty list for non-existent file."""
    result = _read_recent_transcript(Path("/tmp/nonexistent_xyz.jsonl"))
    assert result == []


# -- _format_recall_result --------------------------------------------------


def test_format_recall_result_with_full_data():
    """Should format categories, items, facts, and next_step_query."""
    result = {
        "categories": [{"name": "personal", "summary": "user preferences"}],
        "items": [
            {"summary": "likes coffee", "memory_type": "profile"},
            {"summary": "works on Clarvis", "memory_type": "knowledge"},
        ],
        "graphiti_facts": [{"fact": "user is a developer"}],
        "next_step_query": "What tools does the user prefer?",
    }
    formatted = _format_recall_result(result)

    assert "## Categories" in formatted
    assert "personal" in formatted
    assert "## Memory Items" in formatted
    assert "[profile]" in formatted
    assert "likes coffee" in formatted
    assert "## Knowledge Graph Facts" in formatted
    assert "user is a developer" in formatted
    assert "Suggested follow-up" in formatted


def test_format_recall_result_empty():
    """Should return 'No memories found.' when all sections empty."""
    result = {
        "categories": [],
        "items": [],
        "graphiti_facts": [],
    }
    assert _format_recall_result(result) == "No memories found."


def test_format_recall_result_error():
    """Should return error message on error result."""
    result = {"error": "memU backend not started"}
    formatted = _format_recall_result(result)
    assert "Error:" in formatted
    assert "memU backend not started" in formatted


def test_format_recall_result_items_only():
    """Should format correctly when only items are present."""
    result = {
        "categories": [],
        "items": [{"summary": "a memory"}],
        "graphiti_facts": [],
    }
    formatted = _format_recall_result(result)
    assert "## Memory Items" in formatted
    assert "a memory" in formatted
    assert "## Categories" not in formatted
    assert "## Knowledge Graph Facts" not in formatted


def test_format_recall_result_graphiti_facts_only():
    """Should format correctly when only graphiti facts present."""
    result = {
        "categories": [],
        "items": [],
        "graphiti_facts": [{"fact": "a fact"}, {"text": "another fact"}],
    }
    formatted = _format_recall_result(result)
    assert "## Knowledge Graph Facts" in formatted
    assert "a fact" in formatted
    assert "another fact" in formatted
