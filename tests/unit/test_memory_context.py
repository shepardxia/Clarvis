"""Tests for memory context utilities (transcript reading + grounding)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from clarvis.channels.memory_context import (
    build_memory_grounding,
    read_recent_transcript,
)

# -- read_recent_transcript -------------------------------------------------


def test_read_recent_transcript_reads_last_n(tmp_path: Path):
    """Should read last N lines from JSONL file."""
    path = tmp_path / "transcript.jsonl"
    lines = [json.dumps({"sender": "user1", "content": f"msg {i}"}) for i in range(10)]
    path.write_text("\n".join(lines))

    result = read_recent_transcript(path, max_lines=3)
    assert len(result) == 3
    assert result[0]["content"] == "msg 7"
    assert result[2]["content"] == "msg 9"


def test_read_recent_transcript_maps_roles(tmp_path: Path):
    """Should map 'clarvis' sender to 'assistant', others to 'user'."""
    path = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps({"sender": "user1", "content": "hello"}),
        json.dumps({"sender": "clarvis", "content": "hi there"}),
    ]
    path.write_text("\n".join(lines))

    result = read_recent_transcript(path)
    assert result[0]["role"] == "user"
    assert result[1]["role"] == "assistant"


def test_read_recent_transcript_missing_file():
    """Should return empty list for missing file."""
    result = read_recent_transcript(Path("/nonexistent/transcript.jsonl"))
    assert result == []


def test_read_recent_transcript_malformed_json(tmp_path: Path):
    """Should skip malformed JSON lines and continue."""
    path = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps({"sender": "user1", "content": "good"}),
        "not valid json {{{",
        json.dumps({"sender": "user2", "content": "also good"}),
    ]
    path.write_text("\n".join(lines))

    result = read_recent_transcript(path)
    assert len(result) == 2
    assert result[0]["content"] == "good"
    assert result[1]["content"] == "also good"


def test_read_recent_transcript_skips_empty_content(tmp_path: Path):
    """Should skip entries with empty content."""
    path = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps({"sender": "user1", "content": ""}),
        json.dumps({"sender": "user1", "content": "real message"}),
    ]
    path.write_text("\n".join(lines))

    result = read_recent_transcript(path)
    assert len(result) == 1
    assert result[0]["content"] == "real message"


def test_read_recent_transcript_truncates_long_content(tmp_path: Path):
    """Should truncate content longer than 2000 chars."""
    path = tmp_path / "transcript.jsonl"
    long_text = "x" * 5000
    path.write_text(json.dumps({"sender": "user1", "content": long_text}))

    result = read_recent_transcript(path)
    assert len(result[0]["content"]) == 2000


# -- build_memory_grounding ------------------------------------------------


@pytest.mark.asyncio
async def test_build_memory_grounding_formats_context():
    """Should format Hindsight recall result into <memory_context> block."""
    backend = MagicMock()
    backend.ready = True
    backend.recall = AsyncMock(
        return_value={
            "results": [
                {"content": "likes coffee", "fact_type": "world"},
                {"content": "user is a developer", "fact_type": "world"},
            ],
            "entities": [{"name": "Shepard"}],
        }
    )

    transcript = [{"role": "user", "content": "tell me about myself"}]
    result = await build_memory_grounding(backend, "parletre", transcript)

    assert result.startswith("<memory_context>")
    assert result.endswith("</memory_context>")
    assert "likes coffee" in result
    assert "user is a developer" in result
    assert "Shepard" in result


@pytest.mark.asyncio
async def test_build_memory_grounding_empty_when_not_ready():
    """Should return empty string when backend is not ready."""
    backend = MagicMock()
    backend.ready = False

    result = await build_memory_grounding(backend, "parletre", [])
    assert result == ""


@pytest.mark.asyncio
async def test_build_memory_grounding_empty_when_none():
    """Should return empty string when hindsight_backend is None."""
    result = await build_memory_grounding(None, "parletre", [])
    assert result == ""


@pytest.mark.asyncio
async def test_build_memory_grounding_empty_when_no_results():
    """Should return empty string when recall returns no data."""
    backend = MagicMock()
    backend.ready = True
    backend.recall = AsyncMock(
        return_value={
            "results": [],
            "entities": [],
        }
    )

    result = await build_memory_grounding(backend, "parletre", [])
    assert result == ""


@pytest.mark.asyncio
async def test_build_memory_grounding_truncates_long_results():
    """Should truncate grounding body to ~2000 chars."""
    backend = MagicMock()
    backend.ready = True
    backend.recall = AsyncMock(
        return_value={
            "results": [{"content": "x" * 300, "fact_type": "world"} for _ in range(20)],
            "entities": [],
        }
    )

    result = await build_memory_grounding(backend, "parletre", [])
    # The body (inside tags) should be <= ~2000 chars
    body = result.replace("<memory_context>\n", "").replace("\n</memory_context>", "")
    assert len(body) <= 2003  # 2000 + "..."


@pytest.mark.asyncio
async def test_build_memory_grounding_handles_recall_error():
    """Should return empty string on recall error."""
    backend = MagicMock()
    backend.ready = True
    backend.recall = AsyncMock(return_value={"error": "boom"})

    result = await build_memory_grounding(backend, "parletre", [])
    assert result == ""


@pytest.mark.asyncio
async def test_build_memory_grounding_with_fact_types():
    """Should show fact type prefixes in grounding."""
    backend = MagicMock()
    backend.ready = True
    backend.recall = AsyncMock(
        return_value={
            "results": [
                {"content": "likes metal", "fact_type": "opinion", "confidence": 0.9},
                {"content": "works at MIT", "fact_type": "world"},
            ],
            "entities": [],
        }
    )

    result = await build_memory_grounding(backend, "parletre", [])
    assert "[opinion]" in result
    assert "[world]" in result
    assert "conf: 0.9" in result
