"""Tests for DocumentWatcher — content-hashed file watcher for knowledge graph ingestion."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from clarvis.memory.document_watcher import DocumentWatcher

# -- Tests ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_scan_lifecycle(tmp_path: Path):
    """New file → unchanged skip → modified re-ingest → hash persists across instances."""
    watch_dir = tmp_path / "documents"
    watch_dir.mkdir()
    hash_store = tmp_path / "doc_hashes.json"
    backend = AsyncMock()
    backend.kg_ingest = AsyncMock(return_value={"status": "ok", "dataset": "documents"})
    watcher = DocumentWatcher(watch_dir=watch_dir, memory=backend, hash_store_path=hash_store, poll_interval=60)

    # first scan ingests new file
    (watch_dir / "notes.md").write_text("some notes")
    results = await watcher.scan()
    assert len(results) == 1
    assert results[0]["status"] == "ok"
    assert results[0]["file"] == "notes.md"
    backend.kg_ingest.assert_awaited_once()

    # rescan unchanged file — skipped
    backend.kg_ingest.reset_mock()
    results = await watcher.scan()
    assert len(results) == 0
    backend.kg_ingest.assert_not_awaited()

    # modify file — re-ingested
    (watch_dir / "notes.md").write_text("updated notes")
    results = await watcher.scan()
    assert len(results) == 1
    assert results[0]["file"] == "notes.md"
    backend.kg_ingest.assert_awaited_once()

    # hash state persists across instances
    backend.kg_ingest.reset_mock()
    (watch_dir / "stable.txt").write_text("content")
    w2_backend = AsyncMock()
    w2_backend.kg_ingest = AsyncMock(return_value={"status": "ok", "dataset": "documents"})
    w2 = DocumentWatcher(watch_dir=watch_dir, memory=w2_backend, hash_store_path=hash_store, poll_interval=60)
    results = await w2.scan()
    # only stable.txt is new; notes.md hash persisted from previous instance
    assert len(results) == 1
    assert results[0]["file"] == "stable.txt"


@pytest.mark.asyncio
async def test_document_scan_structure(tmp_path: Path):
    """Recursive scanning into subdirectories and dotfile exclusion."""
    watch_dir = tmp_path / "documents"
    watch_dir.mkdir()
    hash_store = tmp_path / "doc_hashes.json"
    backend = AsyncMock()
    backend.kg_ingest = AsyncMock(side_effect=lambda *a, **kw: {"status": "ok", "dataset": "documents"})
    watcher = DocumentWatcher(watch_dir=watch_dir, memory=backend, hash_store_path=hash_store, poll_interval=60)

    # subdirectories are recursed
    sub = watch_dir / "subdir"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested content")

    # hidden files skipped
    (watch_dir / ".hidden").write_text("secret")
    (watch_dir / "visible.txt").write_text("public")

    results = await watcher.scan()
    assert len(results) == 2
    result_files = [r["file"] for r in results]
    assert any("visible.txt" in f for f in result_files)
    assert any("nested.txt" in f for f in result_files)
    # .hidden not ingested
    assert not any(".hidden" in f for f in result_files)


@pytest.mark.asyncio
async def test_document_scan_error_resilience(tmp_path: Path):
    """Failure isolation and hash rollback on ingest error."""
    watch_dir = tmp_path / "documents"
    watch_dir.mkdir()
    hash_store = tmp_path / "doc_hashes.json"

    # scan continues when one file fails
    backend = AsyncMock()
    call_count = 0

    async def flaky_ingest(path, **kwargs):
        nonlocal call_count
        call_count += 1
        if "bad.txt" in str(path):
            raise RuntimeError("ingest failed")
        return {"status": "ok", "dataset": "documents"}

    backend.kg_ingest = flaky_ingest
    watcher = DocumentWatcher(watch_dir=watch_dir, memory=backend, hash_store_path=hash_store, poll_interval=60)

    (watch_dir / "good.txt").write_text("good")
    (watch_dir / "bad.txt").write_text("bad")

    results = await watcher.scan()
    assert len(results) == 1
    assert results[0]["file"] == "good.txt"
    assert call_count == 2  # both attempted

    # failed ingest does not update hash — retry is possible
    backend2 = AsyncMock()
    backend2.kg_ingest = AsyncMock(side_effect=RuntimeError("boom"))
    watcher2 = DocumentWatcher(watch_dir=watch_dir, memory=backend2, hash_store_path=hash_store, poll_interval=60)
    (watch_dir / "retry.txt").write_text("content")

    await watcher2.scan()
    assert "retry.txt" not in watcher2._hashes
