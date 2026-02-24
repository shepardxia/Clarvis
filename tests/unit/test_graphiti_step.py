"""Tests for GraphitiStep — memU pipeline step that syncs items to Graphiti."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from clarvis.services.memory.graphiti_step import make_graphiti_step


@pytest.fixture()
def graphiti_backend():
    mock = AsyncMock()
    mock.add_episode = AsyncMock()
    return mock


@pytest.fixture()
def step(graphiti_backend):
    return make_graphiti_step(graphiti_backend)


# -- Step construction -------------------------------------------------------


def test_step_has_correct_id(step):
    assert step.step_id == "graphiti_sync"


def test_step_requires_items(step):
    assert "items" in step.requires


# -- Handler -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_syncs_items(graphiti_backend, step):
    """Handler should call add_episode for each item."""
    items = [
        SimpleNamespace(summary="likes coffee", memory_type="preference"),
        SimpleNamespace(summary="works on Clarvis", memory_type="knowledge"),
    ]
    state = {"items": items, "user": {"dataset": "parletre"}}

    result = await step.run(state, context=None)

    assert result == state
    assert graphiti_backend.add_episode.await_count == 2
    graphiti_backend.add_episode.assert_any_await(text="likes coffee", dataset="parletre", name="preference")
    graphiti_backend.add_episode.assert_any_await(text="works on Clarvis", dataset="parletre", name="knowledge")


@pytest.mark.asyncio
async def test_handler_defaults_to_agora(graphiti_backend, step):
    """Handler should default dataset to 'agora' when user has no dataset."""
    items = [SimpleNamespace(summary="a fact", memory_type="knowledge")]
    state = {"items": items, "user": {}}

    await step.run(state, context=None)

    graphiti_backend.add_episode.assert_awaited_once_with(
        text="a fact",
        dataset="agora",
        name="knowledge",
    )


@pytest.mark.asyncio
async def test_handler_uses_str_fallback_for_items(graphiti_backend, step):
    """Handler should fall back to str(item) when .summary is missing."""
    item = SimpleNamespace(memory_type="event")  # no .summary
    state = {"items": [item], "user": {"dataset": "agora"}}

    await step.run(state, context=None)

    call_kwargs = graphiti_backend.add_episode.call_args[1]
    assert "memory_type" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_handler_empty_items(graphiti_backend, step):
    """Handler should be a no-op with empty items list."""
    state = {"items": [], "user": {"dataset": "parletre"}}

    result = await step.run(state, context=None)

    assert result == state
    graphiti_backend.add_episode.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_graceful_on_graphiti_error(graphiti_backend, step):
    """Handler should log and continue when Graphiti fails on one item."""
    graphiti_backend.add_episode = AsyncMock(side_effect=[RuntimeError("boom"), None])
    items = [
        SimpleNamespace(summary="item1", memory_type="knowledge"),
        SimpleNamespace(summary="item2", memory_type="knowledge"),
    ]
    state = {"items": items, "user": {"dataset": "agora"}}

    result = await step.run(state, context=None)

    # Should not raise — continues past the failure
    assert result == state
    assert graphiti_backend.add_episode.await_count == 2


@pytest.mark.asyncio
async def test_handler_non_dict_user(graphiti_backend, step):
    """Handler should default to 'agora' when user is not a dict."""
    items = [SimpleNamespace(summary="fact", memory_type="knowledge")]
    state = {"items": items, "user": "not-a-dict"}

    await step.run(state, context=None)

    graphiti_backend.add_episode.assert_awaited_once_with(
        text="fact",
        dataset="agora",
        name="knowledge",
    )
