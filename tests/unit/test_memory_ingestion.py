"""Tests for IngestionPipeline -- watermarks, staleness, and incremental ingest."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from clarvis.services.memory.ingestion import IngestionPipeline

# -- Fixtures ---------------------------------------------------------------


@pytest.fixture()
def state_dir(tmp_path: Path) -> Path:
    """Temporary state directory."""
    d = tmp_path / "state"
    d.mkdir()
    return d


@pytest.fixture()
def mock_memory() -> MagicMock:
    """Mock memory service with async ingest_transcript."""
    svc = MagicMock()
    svc.ingest_transcript = AsyncMock(return_value={"status": "ok"})
    return svc


@pytest.fixture()
def pipeline(state_dir: Path, mock_memory: MagicMock) -> IngestionPipeline:
    return IngestionPipeline(state_dir=state_dir, memory_service=mock_memory)


# -- Watermark tests --------------------------------------------------------


def test_initial_watermark_is_zero(pipeline: IngestionPipeline):
    """A never-seen session key should return watermark 0."""
    assert pipeline.get_watermark("new-session") == 0


def test_watermark_advances(pipeline: IngestionPipeline):
    """set_watermark should update the value returned by get_watermark."""
    pipeline.set_watermark("s1", 1024)
    assert pipeline.get_watermark("s1") == 1024

    pipeline.set_watermark("s1", 2048)
    assert pipeline.get_watermark("s1") == 2048


def test_watermark_persists(state_dir: Path, mock_memory: MagicMock):
    """A new IngestionPipeline instance should read persisted watermarks."""
    p1 = IngestionPipeline(state_dir=state_dir, memory_service=mock_memory)
    p1.set_watermark("sess-abc", 4096)

    # New instance pointing at the same state directory.
    p2 = IngestionPipeline(state_dir=state_dir, memory_service=mock_memory)
    assert p2.get_watermark("sess-abc") == 4096


# -- Staleness tests --------------------------------------------------------


def test_is_stale_when_never_written(pipeline: IngestionPipeline):
    """Pipeline with no prior writes should be stale."""
    assert pipeline.is_stale() is True


def test_not_stale_when_recently_written(pipeline: IngestionPipeline):
    """Pipeline with a recent write should not be stale."""
    now = datetime.now(timezone.utc).isoformat()
    pipeline._state["last_write_ts"] = now
    assert pipeline.is_stale() is False


def test_stale_after_threshold(pipeline: IngestionPipeline):
    """Pipeline should be stale when last write exceeds staleness_hours."""
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    pipeline._state["last_write_ts"] = old
    assert pipeline.is_stale(staleness_hours=24) is True


# -- Ingestion tests --------------------------------------------------------


def _write_transcript(path: Path, entries: list[dict]) -> None:
    """Helper: write JSONL entries to *path*."""
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


@pytest.mark.asyncio
async def test_ingest_from_watermark(
    pipeline: IngestionPipeline,
    mock_memory: MagicMock,
    tmp_path: Path,
):
    """Ingestion should read JSONL, call ingest_transcript, and advance watermark."""
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(
        transcript,
        [
            {"type": "user", "content": "hello"},
            {"type": "assistant", "content": "hi there"},
            {"type": "system", "content": "should be skipped"},
        ],
    )

    result = await pipeline.ingest_session("sess-1", transcript, dataset="test")

    assert result["status"] == "ok"
    assert result["lines"] == 2

    # Verify the memory service was called with the right text.
    mock_memory.ingest_transcript.assert_awaited_once()
    call_args = mock_memory.ingest_transcript.call_args
    text = call_args[0][0]
    assert "user: hello" in text
    assert "assistant: hi there" in text
    assert "system" not in text

    # Watermark should now equal the file size.
    assert pipeline.get_watermark("sess-1") == transcript.stat().st_size

    # last_write_ts should be set.
    assert pipeline.last_write_ts is not None


@pytest.mark.asyncio
async def test_no_reingest_same_content(
    pipeline: IngestionPipeline,
    mock_memory: MagicMock,
    tmp_path: Path,
):
    """Second ingest of the same file should be a no-op."""
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(
        transcript,
        [
            {"type": "user", "content": "hello"},
            {"type": "assistant", "content": "world"},
        ],
    )

    r1 = await pipeline.ingest_session("sess-2", transcript, dataset="test")
    assert r1["status"] == "ok"

    r2 = await pipeline.ingest_session("sess-2", transcript, dataset="test")
    assert r2["status"] == "skipped"
    assert r2["reason"] == "no new content"

    # ingest_transcript should only have been called once.
    assert mock_memory.ingest_transcript.await_count == 1
