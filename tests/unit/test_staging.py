"""Tests for StagingStore — reflect diff approval flow."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from clarvis.agent.memory.staging import StagedChange, StagingStore

# -- Fixtures ---------------------------------------------------------------


@pytest.fixture()
def staging_path(tmp_path: Path) -> Path:
    return tmp_path / "staging.json"


@pytest.fixture()
def store(staging_path: Path) -> StagingStore:
    return StagingStore(staging_path)


@pytest.fixture()
def mock_backend():
    """Mocked HindsightBackend for approve tests."""
    backend = MagicMock()
    backend.retain = AsyncMock(return_value=[{"id": "new-1", "fact_type": "world"}])
    backend.update = AsyncMock(
        return_value={
            "success": True,
            "old_id": "old-1",
            "new_ids": ["new-2"],
            "message": "Memory replaced",
        }
    )
    backend.forget = AsyncMock(return_value={"success": True, "unit_id": "del-1", "message": "Deleted"})
    return backend


# -- StagedChange validation -----------------------------------------------


def test_staged_change_defaults():
    """StagedChange should have sensible defaults."""
    change = StagedChange(content="test fact")
    assert change.action == "add"
    assert change.bank == "parletre"
    assert change.id  # UUID should be auto-generated
    assert change.timestamp  # Should have a timestamp


def test_staged_change_invalid_action():
    """StagedChange should reject invalid actions."""
    with pytest.raises(ValueError, match="Invalid action"):
        StagedChange(action="explode", content="boom")


def test_staged_change_add_requires_content():
    """'add' action must have content."""
    with pytest.raises(ValueError, match="requires content"):
        StagedChange(action="add", content=None)


def test_staged_change_update_requires_target():
    """'update' action must have target_fact_id."""
    with pytest.raises(ValueError, match="requires target_fact_id"):
        StagedChange(action="update", content="new text")


def test_staged_change_forget_requires_target():
    """'forget' action must have target_fact_id."""
    with pytest.raises(ValueError, match="requires target_fact_id"):
        StagedChange(action="forget")


def test_staged_change_valid_forget():
    """'forget' action with target_fact_id should work."""
    change = StagedChange(action="forget", target_fact_id="unit-123")
    assert change.action == "forget"
    assert change.target_fact_id == "unit-123"


# -- Stage / list tests -----------------------------------------------------


def test_stage_returns_id(store):
    """stage() should return the change's ID."""
    change = StagedChange(content="fact A", reason="important")
    cid = store.stage(change)
    assert cid == change.id


def test_list_staged_returns_staged_changes(store):
    """list_staged() should return all staged changes."""
    store.stage(StagedChange(content="fact A"))
    store.stage(StagedChange(content="fact B"))

    staged = store.list_staged()
    assert len(staged) == 2
    contents = {c.content for c in staged}
    assert contents == {"fact A", "fact B"}


def test_list_staged_returns_oldest_first(store):
    """list_staged() should return changes ordered by timestamp."""
    c1 = StagedChange(content="first", timestamp="2026-01-01T00:00:00+00:00")
    c2 = StagedChange(content="second", timestamp="2026-01-02T00:00:00+00:00")
    c3 = StagedChange(content="third", timestamp="2026-01-03T00:00:00+00:00")

    # Stage out of order
    store.stage(c3)
    store.stage(c1)
    store.stage(c2)

    staged = store.list_staged()
    assert [c.content for c in staged] == ["first", "second", "third"]


def test_list_staged_empty(store):
    """list_staged() on empty store returns empty list."""
    assert store.list_staged() == []


# -- Persistence tests ------------------------------------------------------


def test_persistence_across_instances(staging_path):
    """Staged changes should survive store re-creation."""
    store1 = StagingStore(staging_path)
    store1.stage(StagedChange(content="persisted fact", reason="test"))

    # New instance should load from disk
    store2 = StagingStore(staging_path)
    staged = store2.list_staged()
    assert len(staged) == 1
    assert staged[0].content == "persisted fact"
    assert staged[0].reason == "test"


def test_persistence_after_reject(staging_path):
    """Rejected changes should not appear after reload."""
    store = StagingStore(staging_path)
    cid = store.stage(StagedChange(content="temp"))
    store.reject([cid])

    reloaded = StagingStore(staging_path)
    assert reloaded.list_staged() == []


def test_persistence_after_clear(staging_path):
    """Cleared store should persist as empty."""
    store = StagingStore(staging_path)
    store.stage(StagedChange(content="X"))
    store.stage(StagedChange(content="Y"))
    store.clear()

    reloaded = StagingStore(staging_path)
    assert reloaded.list_staged() == []


# -- Reject tests -----------------------------------------------------------


def test_reject_removes_changes(store):
    """reject() should remove specified changes."""
    c1_id = store.stage(StagedChange(content="A"))
    store.stage(StagedChange(content="B"))

    removed = store.reject([c1_id])
    assert removed == 1

    remaining = store.list_staged()
    assert len(remaining) == 1
    assert remaining[0].content == "B"


def test_reject_unknown_id(store):
    """reject() with unknown ID should return 0 removed."""
    store.stage(StagedChange(content="A"))
    removed = store.reject(["nonexistent-id"])
    assert removed == 0
    assert len(store.list_staged()) == 1


def test_reject_multiple(store):
    """reject() should handle multiple IDs."""
    ids = [store.stage(StagedChange(content=f"fact-{i}")) for i in range(5)]
    removed = store.reject(ids[:3])
    assert removed == 3
    assert len(store.list_staged()) == 2


# -- Clear tests ------------------------------------------------------------


def test_clear_removes_all(store):
    """clear() should remove all staged changes."""
    store.stage(StagedChange(content="A"))
    store.stage(StagedChange(content="B"))
    store.stage(StagedChange(content="C"))

    store.clear()
    assert store.list_staged() == []


def test_clear_on_empty(store):
    """clear() on empty store should be a no-op."""
    store.clear()
    assert store.list_staged() == []


# -- Approve tests ----------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_add(store, mock_backend):
    """Approving an 'add' change should call backend.retain()."""
    cid = store.stage(
        StagedChange(
            content="Shepard works at MIT",
            fact_type="world",
            bank="parletre",
            reason="from conversation",
        )
    )

    results = await store.approve([cid], mock_backend)

    assert len(results) == 1
    assert results[0]["action"] == "add"
    assert results[0]["facts"] == [{"id": "new-1", "fact_type": "world"}]

    mock_backend.retain.assert_awaited_once_with(
        "Shepard works at MIT",
        bank="parletre",
        fact_type="world",
        confidence=None,
    )

    # Change should be removed from staging
    assert store.list_staged() == []


@pytest.mark.asyncio
async def test_approve_update(store, mock_backend):
    """Approving an 'update' change should call backend.update()."""
    cid = store.stage(
        StagedChange(
            action="update",
            target_fact_id="old-1",
            content="Updated content",
            bank="parletre",
            reason="correction",
        )
    )

    results = await store.approve([cid], mock_backend)

    assert len(results) == 1
    assert results[0]["action"] == "update"
    assert results[0]["success"] is True

    mock_backend.update.assert_awaited_once_with(
        "old-1",
        bank="parletre",
        content="Updated content",
        fact_type=None,
        confidence=None,
    )

    assert store.list_staged() == []


@pytest.mark.asyncio
async def test_approve_forget(store, mock_backend):
    """Approving a 'forget' change should call backend.forget()."""
    cid = store.stage(
        StagedChange(
            action="forget",
            target_fact_id="del-1",
            reason="outdated",
        )
    )

    results = await store.approve([cid], mock_backend)

    assert len(results) == 1
    assert results[0]["action"] == "forget"
    assert results[0]["success"] is True

    mock_backend.forget.assert_awaited_once_with("del-1")
    assert store.list_staged() == []


@pytest.mark.asyncio
async def test_approve_unknown_id(store, mock_backend):
    """Approving an unknown ID should return an error."""
    results = await store.approve(["no-such-id"], mock_backend)

    assert len(results) == 1
    assert results[0]["error"] == "Not found in staging"
    mock_backend.retain.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_backend_failure(store, mock_backend):
    """If backend raises, the change stays in staging."""
    mock_backend.retain = AsyncMock(side_effect=RuntimeError("DB down"))

    cid = store.stage(StagedChange(content="will fail"))
    results = await store.approve([cid], mock_backend)

    assert len(results) == 1
    assert "error" in results[0]
    assert "DB down" in results[0]["error"]

    # Change should still be staged (not removed)
    assert len(store.list_staged()) == 1


@pytest.mark.asyncio
async def test_approve_multiple(store, mock_backend):
    """approve() should handle multiple changes in one call."""
    c1 = store.stage(StagedChange(content="A"))
    c2 = store.stage(StagedChange(content="B"))

    results = await store.approve([c1, c2], mock_backend)

    assert len(results) == 2
    assert all(r["action"] == "add" for r in results)
    assert store.list_staged() == []


@pytest.mark.asyncio
async def test_approve_partial_failure(store, mock_backend):
    """If one change fails, others still succeed and failed stays staged."""
    call_count = 0

    async def flaky_retain(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("First one fails")
        return [{"id": "ok", "fact_type": "world"}]

    mock_backend.retain = AsyncMock(side_effect=flaky_retain)

    c1 = store.stage(StagedChange(content="fails"))
    c2 = store.stage(StagedChange(content="succeeds"))

    results = await store.approve([c1, c2], mock_backend)

    assert len(results) == 2
    assert "error" in results[0]
    assert results[1]["action"] == "add"

    # Only the failed one should remain
    remaining = store.list_staged()
    assert len(remaining) == 1
    assert remaining[0].content == "fails"


# -- Approve with confidence -----------------------------------------------


@pytest.mark.asyncio
async def test_approve_add_with_confidence(store, mock_backend):
    """Approving an opinion-type add should pass confidence."""
    cid = store.stage(
        StagedChange(
            content="Prefers GRPO over PPO",
            fact_type="opinion",
            confidence=0.7,
            reason="inferred from conversation",
        )
    )

    await store.approve([cid], mock_backend)

    mock_backend.retain.assert_awaited_once_with(
        "Prefers GRPO over PPO",
        bank="parletre",
        fact_type="opinion",
        confidence=0.7,
    )
