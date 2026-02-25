"""Tests for DocumentWatcher — content-hashed file watcher for Cognee."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from clarvis.agent.memory.document_watcher import DocumentWatcher

# -- Fixtures ---------------------------------------------------------------


@pytest.fixture()
def watch_dir(tmp_path: Path) -> Path:
    d = tmp_path / "documents"
    d.mkdir()
    return d


@pytest.fixture()
def hash_store(tmp_path: Path) -> Path:
    return tmp_path / "doc_hashes.json"


@pytest.fixture()
def mock_backend():
    backend = AsyncMock()
    backend.ingest = AsyncMock(return_value={"status": "ok", "dataset": "documents"})
    return backend


@pytest.fixture()
def watcher(watch_dir, mock_backend, hash_store):
    return DocumentWatcher(
        watch_dir=watch_dir,
        cognee_backend=mock_backend,
        hash_store_path=hash_store,
        poll_interval=60,
    )


# -- Content hashing -------------------------------------------------------


def test_hash_file_deterministic(watch_dir):
    """Same content produces the same hash."""
    f = watch_dir / "test.txt"
    f.write_text("hello world")
    h1 = DocumentWatcher._hash_file(f)
    h2 = DocumentWatcher._hash_file(f)
    assert h1 == h2
    assert len(h1) == 64  # SHA256 hex digest


def test_hash_file_changes_with_content(watch_dir):
    """Different content produces different hashes."""
    f = watch_dir / "test.txt"
    f.write_text("version 1")
    h1 = DocumentWatcher._hash_file(f)
    f.write_text("version 2")
    h2 = DocumentWatcher._hash_file(f)
    assert h1 != h2


# -- Scan: new files -------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_ingests_new_file(watcher, watch_dir, mock_backend):
    """scan() should ingest a newly created file."""
    (watch_dir / "notes.md").write_text("some notes")
    results = await watcher.scan()

    assert len(results) == 1
    assert results[0]["status"] == "ok"
    assert results[0]["file"] == "notes.md"
    mock_backend.ingest.assert_awaited_once()


@pytest.mark.asyncio
async def test_scan_ingests_multiple_files(watcher, watch_dir, mock_backend):
    """scan() ingests all new files in the directory."""
    (watch_dir / "a.txt").write_text("file a")
    (watch_dir / "b.txt").write_text("file b")
    results = await watcher.scan()

    assert len(results) == 2
    assert mock_backend.ingest.await_count == 2


# -- Scan: unchanged files skipped -----------------------------------------


@pytest.mark.asyncio
async def test_scan_skips_unchanged_file(watcher, watch_dir, mock_backend):
    """scan() should skip files that haven't changed since last scan."""
    (watch_dir / "stable.txt").write_text("content")

    # First scan: should ingest
    results1 = await watcher.scan()
    assert len(results1) == 1

    mock_backend.ingest.reset_mock()

    # Second scan: same content, should skip
    results2 = await watcher.scan()
    assert len(results2) == 0
    mock_backend.ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_scan_detects_changed_file(watcher, watch_dir, mock_backend):
    """scan() re-ingests a file when its content changes."""
    f = watch_dir / "evolving.txt"
    f.write_text("version 1")

    await watcher.scan()
    mock_backend.ingest.reset_mock()

    f.write_text("version 2")
    results = await watcher.scan()

    assert len(results) == 1
    assert results[0]["file"] == "evolving.txt"
    mock_backend.ingest.assert_awaited_once()


# -- Scan: subdirectories --------------------------------------------------


@pytest.mark.asyncio
async def test_scan_handles_subdirectories(watcher, watch_dir, mock_backend):
    """scan() recurses into subdirectories."""
    sub = watch_dir / "subdir"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested content")

    results = await watcher.scan()
    assert len(results) == 1
    assert "subdir/nested.txt" in results[0]["file"]


# -- Scan: hidden files skipped --------------------------------------------


@pytest.mark.asyncio
async def test_scan_skips_hidden_files(watcher, watch_dir, mock_backend):
    """scan() skips hidden files (dotfiles)."""
    (watch_dir / ".hidden").write_text("secret")
    (watch_dir / "visible.txt").write_text("public")

    results = await watcher.scan()
    assert len(results) == 1
    assert results[0]["file"] == "visible.txt"


# -- Scan: missing directory ------------------------------------------------


@pytest.mark.asyncio
async def test_scan_returns_empty_for_missing_dir(mock_backend, hash_store):
    """scan() returns empty list if watch_dir doesn't exist."""
    watcher = DocumentWatcher(
        watch_dir=Path("/nonexistent/path"),
        cognee_backend=mock_backend,
        hash_store_path=hash_store,
    )
    results = await watcher.scan()
    assert results == []


# -- Hash persistence -------------------------------------------------------


@pytest.mark.asyncio
async def test_hash_state_persists_across_instances(watch_dir, mock_backend, hash_store):
    """Hash state is persisted and loaded by new instances."""
    (watch_dir / "doc.txt").write_text("content")

    # First instance scans
    w1 = DocumentWatcher(watch_dir, mock_backend, hash_store)
    await w1.scan()
    assert mock_backend.ingest.await_count == 1

    mock_backend.ingest.reset_mock()

    # New instance with same hash store — should skip
    w2 = DocumentWatcher(watch_dir, mock_backend, hash_store)
    results = await w2.scan()
    assert len(results) == 0
    mock_backend.ingest.assert_not_awaited()


# -- Ingest failure handling ------------------------------------------------


@pytest.mark.asyncio
async def test_scan_continues_on_ingest_failure(watcher, watch_dir, mock_backend):
    """scan() should not crash if one file fails to ingest."""
    (watch_dir / "good.txt").write_text("good")
    (watch_dir / "bad.txt").write_text("bad")

    call_count = 0

    async def flaky_ingest(path, **kwargs):
        nonlocal call_count
        call_count += 1
        if "bad.txt" in str(path):
            raise RuntimeError("ingest failed")
        return {"status": "ok", "dataset": "documents"}

    mock_backend.ingest = flaky_ingest

    results = await watcher.scan()
    # Only the successful one should be in results
    assert len(results) == 1
    assert results[0]["file"] == "good.txt"
    assert call_count == 2  # both were attempted


@pytest.mark.asyncio
async def test_failed_ingest_does_not_update_hash(watcher, watch_dir):
    """If ingest fails, the hash should NOT be stored (so retry is possible)."""
    (watch_dir / "retry.txt").write_text("content")

    backend = AsyncMock()
    backend.ingest = AsyncMock(side_effect=RuntimeError("boom"))
    watcher._backend = backend

    await watcher.scan()

    # Hash should not be stored since ingest failed
    assert "retry.txt" not in watcher._hashes


# -- Lifecycle: start/stop --------------------------------------------------


@pytest.mark.asyncio
async def test_start_creates_watch_dir(mock_backend, hash_store, tmp_path):
    """start() creates the watch_dir if it doesn't exist."""
    new_dir = tmp_path / "new_watch"
    w = DocumentWatcher(new_dir, mock_backend, hash_store)
    await w.start()
    assert new_dir.is_dir()
    await w.stop()


@pytest.mark.asyncio
async def test_stop_cancels_task(watcher):
    """stop() should cancel the background polling task."""
    await watcher.start()
    assert watcher._task is not None
    assert not watcher._task.done()

    await watcher.stop()
    assert watcher._task is None
