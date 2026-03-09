"""Watches a directory for new/changed files and ingests via MemoryStore.

Uses content hashing (SHA256) to skip unchanged files.  Persists hash state
to a JSON file so restarts don't re-ingest already-processed documents.
Runs as a polling loop on the asyncio event loop.
"""

import asyncio
import fnmatch
import hashlib
import logging
from pathlib import Path
from typing import Any

from clarvis.core.persistence import json_load_safe, json_save_atomic

logger = logging.getLogger(__name__)

# Files we never try to ingest.
_SKIP_PATTERNS = {".*", "__pycache__", "*.pyc", ".DS_Store"}


def _should_skip(rel: Path) -> bool:
    """Return True if *rel* (relative to watch root) should be skipped."""
    if any(part.startswith(".") for part in rel.parts):
        return True
    return any(fnmatch.fnmatch(rel.name, pat) for pat in _SKIP_PATTERNS)


class DocumentWatcher:
    """Poll a directory for new/changed files and ingest them.

    Parameters
    ----------
    watch_dir:
        Directory to monitor for document files.
    memory:
        The ``MemoryStore`` instance used for ingestion.
    hash_store_path:
        Path to persist the SHA256 content-hash state JSON.
    poll_interval:
        Seconds between scans (default ``60``).
    """

    def __init__(
        self,
        watch_dir: Path,
        memory: Any,
        hash_store_path: Path,
        poll_interval: int = 60,
    ) -> None:
        self._watch_dir = Path(watch_dir).expanduser()
        self._backend = memory
        self._hash_store_path = Path(hash_store_path).expanduser()
        self._poll_interval = poll_interval
        self._hashes: dict[str, str] = self._load_hashes()
        self._task: asyncio.Task | None = None

    # ── Lifecycle ───────────────────────────────────────────────

    async def start(self) -> None:
        """Start the polling loop as a background task."""
        self._watch_dir.mkdir(parents=True, exist_ok=True)
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("DocumentWatcher started (dir=%s, interval=%ds)", self._watch_dir, self._poll_interval)

    async def stop(self) -> None:
        """Cancel the polling loop."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("DocumentWatcher stopped")

    # ── Hash persistence ────────────────────────────────────────

    def _load_hashes(self) -> dict[str, str]:
        data = json_load_safe(self._hash_store_path)
        if isinstance(data, dict):
            return data
        return {}

    def _save_hashes(self) -> None:
        json_save_atomic(self._hash_store_path, self._hashes)

    # ── Content hashing ─────────────────────────────────────────

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Return SHA256 hex digest of *path* contents."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    # ── Scanning ────────────────────────────────────────────────

    async def scan(self) -> list[dict[str, Any]]:
        """Scan the watch directory and ingest changed files.

        Returns a list of result dicts from the backend for each file
        that was ingested.
        """
        if not self._watch_dir.is_dir():
            return []

        loop = asyncio.get_running_loop()
        results: list[dict[str, Any]] = []

        for path in sorted(self._watch_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self._watch_dir)
            if _should_skip(rel):
                continue

            rel = str(rel)
            try:
                current_hash = await loop.run_in_executor(None, self._hash_file, path)
            except OSError:
                logger.warning("Failed to hash %s", path, exc_info=True)
                continue

            stored_hash = self._hashes.get(rel)
            if stored_hash == current_hash:
                continue  # unchanged

            logger.info("Document changed: %s", rel)
            try:
                result = await self._backend.kg_ingest(
                    str(path),
                    dataset="documents",
                    tags=[rel],
                )
                result["file"] = rel
                results.append(result)
                self._hashes[rel] = current_hash
                self._save_hashes()
            except Exception:
                logger.exception("Failed to ingest %s", rel)

        return results

    # ── Poll loop ───────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        """Continuously scan at the configured interval."""
        while True:
            try:
                await self.scan()
            except Exception:
                logger.exception("DocumentWatcher scan failed")
            await asyncio.sleep(self._poll_interval)
