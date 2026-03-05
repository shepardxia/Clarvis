"""Tests for retain_direct — field mapping, entity conversion, batch, dedup, temporal.

Pipeline step mock-verification tests removed. Only behavioral outcomes kept.
"""

from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("asyncpg", reason="asyncpg not installed (memory extra required)")

from clarvis.vendor.hindsight.engine.retain.orchestrator import retain_direct
from clarvis.vendor.hindsight.engine.retain.types import (
    EntityRef,
    FactInput,
    ProcessedFact,
)

# -- Helpers ----------------------------------------------------------------


def _make_fact_input(**overrides) -> FactInput:
    defaults = {
        "fact_text": "Shepard works at MIT",
        "fact_type": "world",
        "entities": ["Shepard", "MIT"],
        "context": "from a conversation",
        "tags": ["test"],
    }
    defaults.update(overrides)
    return FactInput(**defaults)


def _fake_format_date(dt):
    if dt is None:
        return "unknown date"
    return dt.strftime("%B %Y")


def _pipeline_patches():
    """Context manager that patches all retain_direct pipeline dependencies."""
    return (
        patch("clarvis.vendor.hindsight.engine.retain.orchestrator.acquire_with_retry"),
        patch("clarvis.vendor.hindsight.engine.retain.orchestrator.embedding_processing"),
        patch("clarvis.vendor.hindsight.engine.retain.orchestrator.deduplication"),
        patch("clarvis.vendor.hindsight.engine.retain.orchestrator.fact_storage"),
        patch("clarvis.vendor.hindsight.engine.retain.orchestrator.entity_processing"),
        patch("clarvis.vendor.hindsight.engine.retain.orchestrator.link_creation"),
    )


def _wire_mocks(
    mock_acquire, mock_emb, mock_dedup, mock_storage, mock_entity, mock_links, conn, *, n_facts=1, capture_list=None
):
    """Wire up standard mock returns for n_facts facts."""
    mock_acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    mock_acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_emb.augment_texts_with_dates.return_value = [f"aug{i}" for i in range(n_facts)]
    mock_emb.generate_embeddings_batch = AsyncMock(return_value=[[0.1]] * n_facts)
    mock_dedup.check_duplicates_batch = AsyncMock(return_value=[False] * n_facts)
    mock_dedup.filter_duplicates.side_effect = lambda facts, flags: [f for f, d in zip(facts, flags) if not d]
    mock_storage.ensure_bank_exists = AsyncMock()
    mock_storage.handle_document_tracking = AsyncMock()

    async def _insert(c, bank_id, facts, **kw):
        if capture_list is not None:
            capture_list.extend(facts)
        return [f"unit-{i}" for i in range(len(facts))]

    mock_storage.insert_facts_batch = AsyncMock(side_effect=_insert)
    mock_entity.process_entities_batch = AsyncMock(return_value=[])
    mock_entity.insert_entity_links_batch = AsyncMock()
    mock_links.create_temporal_links_batch = AsyncMock(return_value=0)
    mock_links.create_semantic_links_batch = AsyncMock(return_value=0)
    mock_links.create_causal_links_batch = AsyncMock(return_value=0)


async def _run_retain(
    pool, conn, facts, mock_embeddings_model, mock_entity_resolver, mock_config, *, capture_list=None
):
    """Run retain_direct with standard mocks, return (result, captured_facts)."""
    captured = capture_list if capture_list is not None else []
    with ExitStack() as stack:
        mocks = [stack.enter_context(p) for p in _pipeline_patches()]
        mock_acquire, mock_emb, mock_dedup, mock_storage, mock_entity, mock_links = mocks
        _wire_mocks(
            mock_acquire,
            mock_emb,
            mock_dedup,
            mock_storage,
            mock_entity,
            mock_links,
            conn,
            n_facts=len(facts),
            capture_list=captured,
        )
        result = await retain_direct(
            pool=pool,
            embeddings_model=mock_embeddings_model,
            entity_resolver=mock_entity_resolver,
            format_date_fn=_fake_format_date,
            duplicate_checker_fn=AsyncMock(return_value=[False] * len(facts)),
            bank_id="parletre",
            facts=facts,
            config=mock_config,
        )
    return result, captured


# -- Fixtures ---------------------------------------------------------------


@pytest.fixture()
def mock_pool():
    conn = AsyncMock()
    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx_cm)
    conn.fetch = AsyncMock(return_value=[])
    pool = MagicMock()
    return pool, conn


@pytest.fixture()
def mock_embeddings_model():
    return MagicMock()


@pytest.fixture()
def mock_entity_resolver():
    return MagicMock()


@pytest.fixture()
def mock_config():
    return MagicMock()


# -- Tests ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fact_input_to_processed_fact(mock_pool, mock_embeddings_model, mock_entity_resolver, mock_config):
    """FactInput fields are correctly mapped to ProcessedFact."""
    pool, conn = mock_pool
    fact = _make_fact_input(
        fact_text="Shepard works at MIT",
        fact_type="world",
        entities=["Shepard", "MIT"],
        context="from a conversation",
        tags=["research"],
        document_id="transcript-001",
        metadata={"source": "voice"},
    )

    result, captured = await _run_retain(pool, conn, [fact], mock_embeddings_model, mock_entity_resolver, mock_config)

    assert result == ["unit-0"]
    assert len(captured) == 1
    pf = captured[0]
    assert isinstance(pf, ProcessedFact)
    assert pf.fact_text == "Shepard works at MIT"
    assert pf.fact_type == "world"
    assert pf.context == "from a conversation"
    assert pf.tags == ["research"]
    assert pf.document_id == "transcript-001"
    assert pf.metadata == {"source": "voice"}
    assert pf.embedding == [0.1]


@pytest.mark.asyncio
async def test_entity_names_converted_to_entity_refs(
    mock_pool, mock_embeddings_model, mock_entity_resolver, mock_config
):
    """Entity name strings are converted to EntityRef objects."""
    pool, conn = mock_pool
    fact = _make_fact_input(entities=["Shepard", "MIT", "Boston"])

    _, captured = await _run_retain(pool, conn, [fact], mock_embeddings_model, mock_entity_resolver, mock_config)

    pf = captured[0]
    assert len(pf.entities) == 3
    for entity in pf.entities:
        assert isinstance(entity, EntityRef)
    assert [e.name for e in pf.entities] == ["Shepard", "MIT", "Boston"]


@pytest.mark.asyncio
async def test_multiple_facts_in_batch(mock_pool, mock_embeddings_model, mock_entity_resolver, mock_config):
    """Multiple facts processed as a batch with correct types."""
    pool, conn = mock_pool
    facts = [
        _make_fact_input(fact_text="Shepard works at MIT", entities=["Shepard", "MIT"]),
        _make_fact_input(fact_text="Alice likes Python", fact_type="experience", entities=["Alice"]),
        _make_fact_input(fact_text="GRPO > PPO", fact_type="opinion", entities=[]),
    ]

    result, captured = await _run_retain(pool, conn, facts, mock_embeddings_model, mock_entity_resolver, mock_config)

    assert result == ["unit-0", "unit-1", "unit-2"]
    assert len(captured) == 3
    assert captured[0].fact_type == "world"
    assert captured[1].fact_type == "experience"
    assert captured[2].fact_type == "opinion"


@pytest.mark.asyncio
async def test_all_duplicates_returns_empty(mock_pool, mock_embeddings_model, mock_entity_resolver, mock_config):
    """When all facts are duplicates, returns empty list and skips storage."""
    pool, conn = mock_pool
    fact = _make_fact_input()

    with ExitStack() as stack:
        mocks = [stack.enter_context(p) for p in _pipeline_patches()]
        mock_acquire, mock_emb, mock_dedup, mock_storage, mock_entity, mock_links = mocks
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_emb.augment_texts_with_dates.return_value = ["augmented"]
        mock_emb.generate_embeddings_batch = AsyncMock(return_value=[[0.1]])
        mock_dedup.check_duplicates_batch = AsyncMock(return_value=[True])
        mock_dedup.filter_duplicates.return_value = []
        mock_storage.ensure_bank_exists = AsyncMock()
        mock_storage.handle_document_tracking = AsyncMock()
        mock_storage.insert_facts_batch = AsyncMock()
        mock_entity.process_entities_batch = AsyncMock()
        mock_entity.insert_entity_links_batch = AsyncMock()
        mock_links.create_temporal_links_batch = AsyncMock()
        mock_links.create_semantic_links_batch = AsyncMock()
        mock_links.create_causal_links_batch = AsyncMock()

        result = await retain_direct(
            pool=pool,
            embeddings_model=mock_embeddings_model,
            entity_resolver=mock_entity_resolver,
            format_date_fn=_fake_format_date,
            duplicate_checker_fn=AsyncMock(return_value=[True]),
            bank_id="parletre",
            facts=[fact],
            config=mock_config,
        )

    assert result == []
    mock_storage.insert_facts_batch.assert_not_called()


@pytest.mark.asyncio
async def test_temporal_fields_passed_through(mock_pool, mock_embeddings_model, mock_entity_resolver, mock_config):
    """occurred_start and occurred_end flow through to ProcessedFact."""
    pool, conn = mock_pool
    start = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
    end = datetime(2026, 1, 15, 11, 0, tzinfo=UTC)
    fact = _make_fact_input(occurred_start=start, occurred_end=end)

    _, captured = await _run_retain(pool, conn, [fact], mock_embeddings_model, mock_entity_resolver, mock_config)

    pf = captured[0]
    assert pf.occurred_start == start
    assert pf.occurred_end == end
