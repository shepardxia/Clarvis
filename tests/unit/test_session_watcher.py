"""Tests for SessionWatcher -- watermarks, scanning, and pending session detection."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from clarvis.agent.memory.session_watcher import SessionWatcher

# -- Helpers -----------------------------------------------------------------


def _write_transcript(path: Path, entries: list[dict[str, Any]]) -> None:
    """Write JSONL entries to *path*."""
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _append_transcript(path: Path, entries: list[dict[str, Any]]) -> None:
    """Append JSONL entries to an existing file."""
    with open(path, "a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture()
def sessions_dir(tmp_path: Path) -> Path:
    """Temporary sessions directory."""
    d = tmp_path / "sessions"
    d.mkdir()
    return d


@pytest.fixture()
def watermark_path(tmp_path: Path) -> Path:
    """Temporary watermark file path."""
    return tmp_path / "watcher_state.json"


@pytest.fixture()
def watcher(sessions_dir: Path, watermark_path: Path) -> SessionWatcher:
    return SessionWatcher(sessions_dir=sessions_dir, watermark_path=watermark_path)


# -- Watermark tests ---------------------------------------------------------


def test_watermark_persists(sessions_dir: Path, watermark_path: Path):
    """A new SessionWatcher instance should read persisted watermarks."""
    w1 = SessionWatcher(sessions_dir=sessions_dir, watermark_path=watermark_path)
    w1.mark_processed("sess-abc", 4096)

    # New instance pointing at the same watermark file.
    w2 = SessionWatcher(sessions_dir=sessions_dir, watermark_path=watermark_path)
    assert w2.get_watermark("sess-abc") == 4096


# -- Staleness tests ---------------------------------------------------------


def test_is_stale_when_never_scanned(watcher: SessionWatcher):
    """Watcher with no prior scans should be stale."""
    assert watcher.is_stale() is True


def test_stale_after_threshold(watcher: SessionWatcher):
    """Watcher should be stale when last scan exceeds staleness_hours."""
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    watcher._state["last_scan_ts"] = old
    assert watcher.is_stale(staleness_hours=24) is True


# -- Scan tests (direct .jsonl files) ---------------------------------------


@pytest.mark.asyncio
async def test_scan_detects_new_transcript(
    watcher: SessionWatcher,
    sessions_dir: Path,
):
    """scan() should find new JSONL transcripts with eligible content."""
    transcript = sessions_dir / "session-1.jsonl"
    _write_transcript(
        transcript,
        [
            {"type": "user", "content": "hello"},
            {"type": "assistant", "content": "hi there"},
            {"type": "system", "content": "should be skipped"},
        ],
    )

    pending = await watcher.scan()

    assert len(pending) == 1
    sess = pending[0]
    assert sess["session_id"] == "session-1"
    assert sess["message_count"] == 2
    assert "user: hello" in sess["new_content"]
    assert "assistant: hi there" in sess["new_content"]
    assert "system" not in sess["new_content"]
    assert sess["byte_offset"] == transcript.stat().st_size


@pytest.mark.asyncio
async def test_scan_skips_already_processed(
    watcher: SessionWatcher,
    sessions_dir: Path,
):
    """scan() should not return sessions that have been fully processed."""
    transcript = sessions_dir / "session-2.jsonl"
    _write_transcript(
        transcript,
        [
            {"type": "user", "content": "hello"},
            {"type": "assistant", "content": "world"},
        ],
    )

    # Mark as fully processed
    watcher.mark_processed("session-2", transcript.stat().st_size)

    pending = await watcher.scan()
    assert len(pending) == 0


@pytest.mark.asyncio
async def test_scan_detects_appended_content(
    watcher: SessionWatcher,
    sessions_dir: Path,
):
    """scan() should detect new content appended after the watermark."""
    transcript = sessions_dir / "session-3.jsonl"
    _write_transcript(
        transcript,
        [{"type": "user", "content": "first message"}],
    )

    # Process initial content
    pending = await watcher.scan()
    assert len(pending) == 1
    watcher.mark_processed("session-3", pending[0]["byte_offset"])

    # Append more content
    _append_transcript(
        transcript,
        [{"type": "assistant", "content": "second message"}],
    )

    # Should detect only the new content
    pending = await watcher.scan()
    assert len(pending) == 1
    assert pending[0]["message_count"] == 1
    assert "second message" in pending[0]["new_content"]
    assert "first message" not in pending[0]["new_content"]


@pytest.mark.asyncio
async def test_scan_ignores_non_eligible_roles(
    watcher: SessionWatcher,
    sessions_dir: Path,
):
    """scan() should skip entries with non-eligible roles."""
    transcript = sessions_dir / "session-4.jsonl"
    _write_transcript(
        transcript,
        [
            {"type": "system", "content": "system prompt"},
            {"type": "tool_result", "content": "result"},
        ],
    )

    pending = await watcher.scan()
    assert len(pending) == 0


# -- Scan tests (subdirectory pattern) --------------------------------------


@pytest.mark.asyncio
async def test_scan_finds_subdirectory_transcripts(
    watcher: SessionWatcher,
    sessions_dir: Path,
):
    """scan() should find transcript.jsonl in session subdirectories."""
    subdir = sessions_dir / "session-sub"
    subdir.mkdir()
    transcript = subdir / "transcript.jsonl"
    _write_transcript(
        transcript,
        [{"role": "user", "content": "from subdir"}],
    )

    pending = await watcher.scan()
    assert len(pending) == 1
    assert pending[0]["session_id"] == "session-sub"
    assert "from subdir" in pending[0]["new_content"]


# -- Multiple sessions -------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_multiple_sessions(
    watcher: SessionWatcher,
    sessions_dir: Path,
):
    """scan() should handle multiple sessions at once."""
    for i in range(3):
        transcript = sessions_dir / f"multi-{i}.jsonl"
        _write_transcript(
            transcript,
            [{"type": "user", "content": f"message {i}"}],
        )

    pending = await watcher.scan()
    assert len(pending) == 3
    session_ids = {p["session_id"] for p in pending}
    assert session_ids == {"multi-0", "multi-1", "multi-2"}


# -- Malformed JSONL ---------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_handles_malformed_jsonl(
    watcher: SessionWatcher,
    sessions_dir: Path,
):
    """scan() should gracefully skip malformed JSONL lines."""
    transcript = sessions_dir / "bad.jsonl"
    with open(transcript, "w") as f:
        f.write('{"type": "user", "content": "good"}\n')
        f.write("this is not json\n")
        f.write('{"type": "assistant", "content": "also good"}\n')
        f.write("\n")  # empty line

    pending = await watcher.scan()
    assert len(pending) == 1
    assert pending[0]["message_count"] == 2


# -- Empty sessions dir ------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_empty_dir(watcher: SessionWatcher):
    """scan() on an empty sessions dir should return nothing."""
    pending = await watcher.scan()
    assert pending == []


# -- Messages field ----------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_includes_parsed_messages(
    watcher: SessionWatcher,
    sessions_dir: Path,
):
    """scan() results should include parsed message dicts."""
    transcript = sessions_dir / "msgs.jsonl"
    _write_transcript(
        transcript,
        [
            {"role": "user", "content": "question?"},
            {"role": "assistant", "content": "answer!"},
        ],
    )

    pending = await watcher.scan()
    assert len(pending) == 1
    msgs = pending[0]["messages"]
    assert len(msgs) == 2
    assert msgs[0] == {"role": "user", "content": "question?"}
    assert msgs[1] == {"role": "assistant", "content": "answer!"}
