"""TranscriptReader — watermark persistence, incremental reads, role filtering, error handling."""

import json
from pathlib import Path
from typing import Any

import pytest

from clarvis.agent.memory.transcript_reader import TranscriptReader

# -- Helpers -----------------------------------------------------------------


def _write_transcript(path: Path, entries: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _append_transcript(path: Path, entries: list[dict[str, Any]]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


# -- Tests -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcript_reading_pipeline(tmp_path: Path):
    """Watermark persistence → first read → incremental read → role filtering."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    watermark_path = tmp_path / "watcher_state.json"

    # watermark persists across instances
    r1 = TranscriptReader(watermark_path=watermark_path)
    r1.mark_processed("sess-abc", 4096)
    r2 = TranscriptReader(watermark_path=watermark_path)
    assert r2.get_watermark("sess-abc") == 4096

    # first read detects new transcript, skips system entries
    reader = TranscriptReader(watermark_path=watermark_path)
    transcript = sessions_dir / "session-1.jsonl"
    _write_transcript(
        transcript,
        [
            {"type": "user", "content": "hello"},
            {"type": "assistant", "content": "hi there"},
            {"type": "system", "content": "should be skipped"},
        ],
    )

    result = await reader.ingest_session("session-1", transcript)
    assert result["status"] == "pending"
    assert result["message_count"] == 2
    assert "user: hello" in result["new_content"]
    assert "system" not in result["new_content"]

    # incremental read after watermark advance
    reader.mark_processed("session-1", result["byte_offset"])
    _append_transcript(transcript, [{"type": "assistant", "content": "second message"}])

    result = await reader.ingest_session("session-1", transcript)
    assert result["status"] == "pending"
    assert "second message" in result["new_content"]
    assert "hello" not in result["new_content"]

    # non-eligible roles (system, tool_result) produce skipped status
    transcript2 = sessions_dir / "session-4.jsonl"
    _write_transcript(
        transcript2,
        [
            {"type": "system", "content": "system prompt"},
            {"type": "tool_result", "content": "result"},
        ],
    )
    result = await reader.ingest_session("session-4", transcript2)
    assert result["status"] == "skipped"


@pytest.mark.asyncio
async def test_transcript_error_handling(tmp_path: Path):
    """Malformed JSONL and missing file handling."""
    watermark_path = tmp_path / "watcher_state.json"
    reader = TranscriptReader(watermark_path=watermark_path)

    # malformed JSONL lines gracefully skipped
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    bad_transcript = sessions_dir / "bad.jsonl"
    with open(bad_transcript, "w") as f:
        f.write('{"type": "user", "content": "good"}\n')
        f.write("this is not json\n")
        f.write('{"type": "assistant", "content": "also good"}\n')
        f.write("\n")

    result = await reader.ingest_session("bad", bad_transcript)
    assert result["status"] == "pending"
    assert result["message_count"] == 2

    # missing file returns skipped status
    result = await reader.ingest_session("nonexistent", tmp_path / "nope.jsonl")
    assert result["status"] == "skipped"
