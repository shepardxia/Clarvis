"""TranscriptReader — watermark persistence, incremental reads, role filtering."""

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


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture()
def sessions_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sessions"
    d.mkdir()
    return d


@pytest.fixture()
def watermark_path(tmp_path: Path) -> Path:
    return tmp_path / "watcher_state.json"


@pytest.fixture()
def reader(watermark_path: Path) -> TranscriptReader:
    return TranscriptReader(watermark_path=watermark_path)


# -- Tests -------------------------------------------------------------------


def test_watermark_persists(watermark_path: Path):
    """New instance reads persisted watermarks."""
    r1 = TranscriptReader(watermark_path=watermark_path)
    r1.mark_processed("sess-abc", 4096)
    r2 = TranscriptReader(watermark_path=watermark_path)
    assert r2.get_watermark("sess-abc") == 4096


@pytest.mark.asyncio
async def test_ingest_detects_new_transcript(reader: TranscriptReader, sessions_dir: Path):
    """Reads new JSONL transcripts, skips system entries."""
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


@pytest.mark.asyncio
async def test_ingest_detects_appended_content(reader: TranscriptReader, sessions_dir: Path):
    """Detects new content appended after watermark."""
    transcript = sessions_dir / "session-3.jsonl"
    _write_transcript(transcript, [{"type": "user", "content": "first message"}])

    result = await reader.ingest_session("session-3", transcript)
    reader.mark_processed("session-3", result["byte_offset"])

    _append_transcript(transcript, [{"type": "assistant", "content": "second message"}])

    result = await reader.ingest_session("session-3", transcript)
    assert result["status"] == "pending"
    assert "second message" in result["new_content"]
    assert "first message" not in result["new_content"]


@pytest.mark.asyncio
async def test_ingest_ignores_non_eligible_roles(reader: TranscriptReader, sessions_dir: Path):
    """Skips entries with non-eligible roles (system, tool_result)."""
    transcript = sessions_dir / "session-4.jsonl"
    _write_transcript(
        transcript,
        [
            {"type": "system", "content": "system prompt"},
            {"type": "tool_result", "content": "result"},
        ],
    )
    result = await reader.ingest_session("session-4", transcript)
    assert result["status"] == "skipped"


@pytest.mark.asyncio
async def test_ingest_handles_malformed_jsonl(reader: TranscriptReader, sessions_dir: Path):
    """Gracefully skips malformed JSONL lines."""
    transcript = sessions_dir / "bad.jsonl"
    with open(transcript, "w") as f:
        f.write('{"type": "user", "content": "good"}\n')
        f.write("this is not json\n")
        f.write('{"type": "assistant", "content": "also good"}\n')
        f.write("\n")

    result = await reader.ingest_session("bad", transcript)
    assert result["status"] == "pending"
    assert result["message_count"] == 2


@pytest.mark.asyncio
async def test_ingest_includes_parsed_messages(reader: TranscriptReader, sessions_dir: Path):
    """Results include parsed message dicts."""
    transcript = sessions_dir / "msgs.jsonl"
    _write_transcript(
        transcript,
        [
            {"role": "user", "content": "question?"},
            {"role": "assistant", "content": "answer!"},
        ],
    )

    result = await reader.ingest_session("msgs", transcript)
    msgs = result["messages"]
    assert len(msgs) == 2
    assert msgs[0] == {"role": "user", "content": "question?"}


@pytest.mark.asyncio
async def test_ingest_missing_file(reader: TranscriptReader, tmp_path: Path):
    """Returns skipped status for missing transcript."""
    result = await reader.ingest_session("nonexistent", tmp_path / "nope.jsonl")
    assert result["status"] == "skipped"
