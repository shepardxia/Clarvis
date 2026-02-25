"""Staging store for reflect-then-approve memory changes.

Staged changes accumulate during async reflect and are committed
(or rejected) during interactive ``clarvis checkin`` sessions.
Persists to a JSON file using atomic writes.
"""

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from clarvis.core.persistence import json_load_safe, json_save_atomic

if TYPE_CHECKING:
    from clarvis.agent.memory.hindsight_backend import HindsightBackend

logger = logging.getLogger(__name__)

VALID_ACTIONS = frozenset({"add", "update", "forget"})


@dataclass
class StagedChange:
    """A proposed memory change awaiting approval.

    Attributes:
        id: Unique change identifier (auto-generated UUID).
        action: One of "add", "update", or "forget".
        bank: Target Hindsight bank (e.g. "parletre", "agora").
        content: Memory content for add/update actions.
        fact_type: Hindsight fact type (world, experience, opinion, observation).
        confidence: Confidence score for opinion facts (0.0-1.0).
        target_fact_id: Existing fact ID for update/forget actions.
        reason: Human-readable explanation of why this change is proposed.
        timestamp: When the change was staged.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    action: str = "add"
    bank: str = "parletre"
    content: str | None = None
    fact_type: str | None = None
    confidence: float | None = None
    target_fact_id: str | None = None
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"Invalid action '{self.action}'. Must be one of: {', '.join(sorted(VALID_ACTIONS))}")
        if self.action == "add" and not self.content:
            raise ValueError("'add' action requires content")
        if self.action in ("update", "forget") and not self.target_fact_id:
            raise ValueError(f"'{self.action}' action requires target_fact_id")


class StagingStore:
    """Persists proposed memory changes as a JSON diff file.

    Usage::

        store = StagingStore(path=Path("~/.clarvis/memory/staging.json"))
        change_id = store.stage(StagedChange(action="add", content="...", reason="..."))
        pending = store.list_staged()
        results = await store.approve(["change-id"], backend)
        rejected = store.reject(["other-id"])
        store.clear()
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path).expanduser()
        self._changes: dict[str, StagedChange] = {}
        self._load()

    # ── Persistence ────────────────────────────────────────────────

    def _load(self) -> None:
        """Load staged changes from disk."""
        raw = json_load_safe(self._path)
        if raw is None:
            self._changes = {}
            return
        self._changes = {}
        for item in raw:
            try:
                change = StagedChange(**item)
                self._changes[change.id] = change
            except (TypeError, ValueError):
                logger.warning("Skipping invalid staged change: %s", item)

    def _save(self) -> None:
        """Persist current changes to disk atomically."""
        data = [asdict(c) for c in self._changes.values()]
        json_save_atomic(self._path, data)

    # ── Public API ─────────────────────────────────────────────────

    def stage(self, change: StagedChange) -> str:
        """Add a proposed change to staging. Returns the change ID."""
        self._changes[change.id] = change
        self._save()
        logger.debug("Staged change %s (%s)", change.id[:8], change.action)
        return change.id

    def list_staged(self) -> list[StagedChange]:
        """Return all currently staged changes, oldest first."""
        return sorted(self._changes.values(), key=lambda c: c.timestamp)

    async def approve(
        self,
        change_ids: list[str],
        backend: "HindsightBackend",
    ) -> list[dict[str, Any]]:
        """Commit approved changes to the backend.

        Each approved change is executed against the HindsightBackend.
        Successfully committed changes are removed from staging.

        Returns a list of result dicts (one per approved change).
        """
        results: list[dict[str, Any]] = []

        for cid in change_ids:
            change = self._changes.get(cid)
            if change is None:
                results.append({"id": cid, "error": "Not found in staging"})
                continue

            try:
                result = await self._execute_change(change, backend)
                result["staged_id"] = cid
                results.append(result)
                # Remove from staging on success
                del self._changes[cid]
            except Exception as exc:
                logger.warning("Failed to approve change %s: %s", cid[:8], exc)
                results.append({"id": cid, "error": str(exc)})

        self._save()
        return results

    def reject(self, change_ids: list[str]) -> int:
        """Discard staged changes. Returns count of actually removed changes."""
        removed = 0
        for cid in change_ids:
            if cid in self._changes:
                del self._changes[cid]
                removed += 1
        self._save()
        return removed

    def clear(self) -> None:
        """Remove all staged changes."""
        self._changes.clear()
        self._save()

    # ── Internal ───────────────────────────────────────────────────

    @staticmethod
    async def _execute_change(
        change: StagedChange,
        backend: "HindsightBackend",
    ) -> dict[str, Any]:
        """Dispatch a single staged change to the backend."""
        if change.action == "add":
            facts = await backend.retain(
                change.content,  # type: ignore[arg-type]  # validated in __post_init__
                bank=change.bank,
                fact_type=change.fact_type,
                confidence=change.confidence,
            )
            return {"action": "add", "facts": facts}

        if change.action == "update":
            result = await backend.update(
                change.target_fact_id,  # type: ignore[arg-type]
                bank=change.bank,
                content=change.content,
                fact_type=change.fact_type,
                confidence=change.confidence,
            )
            return {"action": "update", **result}

        if change.action == "forget":
            result = await backend.forget(
                change.target_fact_id,  # type: ignore[arg-type]
            )
            return {"action": "forget", **result}

        raise ValueError(f"Unknown action: {change.action}")
