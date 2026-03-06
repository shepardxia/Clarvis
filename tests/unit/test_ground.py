"""Memory grounding — budget allocation, visibility filtering, grounding files, error resilience."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from clarvis.memory.ground import (
    _read_grounding_files,
    build_memory_context,
)

# ── Helpers ──────────────────────────────────────────────────


def _model(id: str, name: str, content: str, tags: list[str] | None = None) -> dict:
    return {"id": id, "name": name, "content": content, "tags": tags or []}


def _fact(text: str, fact_type: str = "experience", date: str | None = None) -> dict:
    return {"text": text, "fact_type": fact_type, "occurred_start": date, "mentioned_at": date}


def _observation(text: str, proof_count: int = 1) -> dict:
    return {"text": text, "proof_count": proof_count}


def _make_store():
    s = MagicMock()
    type(s).ready = PropertyMock(return_value=True)
    s.visible_banks.return_value = ["parletre", "agora"]
    s.list_mental_models = AsyncMock(return_value=[])
    s.get_bank_stats = AsyncMock(return_value={"total_facts": 10, "pending": 2})
    s.list_facts = AsyncMock(return_value={"items": [], "total": 0})
    s.list_observations = AsyncMock(return_value=[])
    return s


# ── Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio(loop_scope="function")
async def test_memory_context_bank_and_visibility(tmp_path):
    """Core models always present → extras fill budget → both banks → visibility filters."""
    store = _make_store()
    gdir = tmp_path / "grounding"
    gdir.mkdir()

    # core models always included
    core = _model("m1", "Music Taste", "Heavy/dark/experimental", ["core"])
    store.list_mental_models = AsyncMock(
        side_effect=[
            [core],  # parletre core
            [core],  # parletre all
            [],  # agora core
            [],  # agora all
        ]
    )

    result = await build_memory_context(store, "master", grounding_dir=gdir)
    assert "<memory_context>" in result
    assert "Music Taste" in result
    assert "Heavy/dark/experimental" in result

    # extra models fill remaining budget
    extra = _model("m2", "Extra Model", "Extra content", ["research"])
    store.list_mental_models = AsyncMock(
        side_effect=[
            [core],  # parletre core
            [core, extra],  # parletre all
            [],  # agora core
            [],  # agora all
        ]
    )

    result = await build_memory_context(store, "master", grounding_dir=gdir)
    assert "Music Taste" in result
    assert "Extra Model" in result

    # both banks appear in output
    parletre_model = _model("m1", "Personal", "Personal content", ["core"])
    agora_model = _model("m2", "Shared", "Shared content", ["core"])
    store.list_mental_models = AsyncMock(
        side_effect=[
            [parletre_model],  # parletre core
            [parletre_model],  # parletre all
            [agora_model],  # agora core
            [agora_model],  # agora all
        ]
    )

    result = await build_memory_context(store, "master", grounding_dir=gdir)
    assert "### parletre" in result
    assert "### agora" in result

    # visibility="all" filters to agora only
    store.visible_banks.return_value = ["agora"]
    model = _model("m1", "Shared", "Shared content", ["core"])
    store.list_mental_models = AsyncMock(
        side_effect=[
            [model],  # agora core
            [model],  # agora all
        ]
    )

    result = await build_memory_context(store, "all", grounding_dir=gdir)
    assert "### agora" in result
    assert "### parletre" not in result


@pytest.mark.asyncio(loop_scope="function")
async def test_memory_context_budget_limits(tmp_path):
    """Budget caps exclude extra models and facts."""
    store = _make_store()
    gdir = tmp_path / "grounding"
    gdir.mkdir()

    core = _model("m1", "Core Model", "X" * 100, ["core"])
    extra = _model("m2", "Extra Model", "Y" * 500, ["research"])

    # extra models excluded when over budget
    store.list_mental_models = AsyncMock(
        side_effect=[
            [core],  # parletre core
            [core, extra],  # parletre all
            [],  # agora core
            [],  # agora all
        ]
    )

    result = await build_memory_context(store, "master", token_budget=30, grounding_dir=gdir)
    assert "Core Model" in result
    assert "Extra Model" not in result

    # facts excluded when over budget
    core2 = _model("m1", "Core", "X" * 80, ["core"])
    store.list_mental_models = AsyncMock(
        side_effect=[
            [core2],  # parletre core
            [core2],  # parletre all
            [],  # agora core
            [],  # agora all
        ]
    )
    store.list_facts = AsyncMock(
        return_value={
            "items": [_fact("Should not appear", "experience")],
            "total": 1,
        }
    )

    result = await build_memory_context(store, "master", token_budget=30, grounding_dir=gdir)
    assert "Should not appear" not in result


@pytest.mark.asyncio(loop_scope="function")
async def test_grounding_files_integration(tmp_path):
    """File inclusion, sorting, fallback without store, missing dir handling."""
    store = _make_store()

    # grounding files included with correct content
    gdir = tmp_path / "grounding"
    gdir.mkdir()
    (gdir / "01-personality.md").write_text("I am Clarvis.", encoding="utf-8")
    (gdir / "02-profile.md").write_text("User likes metal.", encoding="utf-8")

    result = await build_memory_context(store, "master", grounding_dir=gdir)
    assert "I am Clarvis." in result
    assert "User likes metal." in result

    # files sorted by name
    gdir2 = tmp_path / "grounding2"
    gdir2.mkdir()
    (gdir2 / "02-second.md").write_text("Second.", encoding="utf-8")
    (gdir2 / "01-first.md").write_text("First.", encoding="utf-8")

    text = _read_grounding_files(gdir2)
    assert text.index("First.") < text.index("Second.")

    # grounding files work without store
    result = await build_memory_context(None, "master", grounding_dir=gdir)
    assert "<memory_context>" in result
    assert "I am Clarvis." in result

    # nonexistent grounding dir falls back to models-only
    core = _model("m1", "Core", "Content", ["core"])
    store.list_mental_models = AsyncMock(
        side_effect=[
            [core],  # parletre core
            [core],  # parletre all
            [],  # agora core
            [],  # agora all
        ]
    )

    result = await build_memory_context(
        store,
        "master",
        grounding_dir=tmp_path / "nonexistent",
    )
    assert "Core" in result
    assert "<memory_context>" in result


@pytest.mark.asyncio(loop_scope="function")
async def test_recent_items_in_context(tmp_path):
    """Stats, facts, and observations all appear with correct formatting."""
    store = _make_store()
    gdir = tmp_path / "grounding"
    gdir.mkdir()

    core = _model("m1", "Core", "Content", ["core"])

    # bank stats included
    store.list_mental_models = AsyncMock(
        side_effect=[
            [core],
            [core],  # parletre
            [],
            [],  # agora
        ]
    )
    store.get_bank_stats = AsyncMock(return_value={"total_facts": 42, "pending": 5})

    result = await build_memory_context(store, "master", grounding_dir=gdir)
    assert "Stats:" in result
    assert "total_facts: 42" in result

    # recent facts included with type and date
    store.list_mental_models = AsyncMock(
        side_effect=[
            [core],
            [core],  # parletre
            [],
            [],  # agora
        ]
    )
    store.list_facts = AsyncMock(
        return_value={
            "items": [
                _fact("Trained wake word model R7", "experience", "2026-03-01"),
                _fact("Python 3.13 is the latest stable", "world"),
            ],
            "total": 2,
        }
    )

    result = await build_memory_context(store, "master", grounding_dir=gdir)
    assert "**Recent facts**" in result
    assert "Trained wake word model R7" in result
    assert "[experience]" in result
    assert "2026-03-01" in result

    # recent observations included with proof counts
    store.list_mental_models = AsyncMock(
        side_effect=[
            [core],
            [core],  # parletre
            [],
            [],  # agora
        ]
    )
    store.list_facts = AsyncMock(return_value={"items": [], "total": 0})
    store.list_observations = AsyncMock(
        return_value=[
            _observation("User prefers dark themes", 3),
            _observation("Single observation"),
        ]
    )

    result = await build_memory_context(store, "master", grounding_dir=gdir)
    assert "**Recent observations**" in result
    assert "User prefers dark themes" in result
    assert "(x3)" in result
    assert "Single observation" in result
    assert "(x1)" not in result


@pytest.mark.asyncio(loop_scope="function")
async def test_memory_context_error_resilience(tmp_path):
    """Graceful degradation across multiple failure modes."""
    store = _make_store()
    gdir = tmp_path / "grounding"
    gdir.mkdir()

    # total failure returns empty string
    store.list_mental_models = AsyncMock(side_effect=RuntimeError("db down"))
    store.get_bank_stats = AsyncMock(side_effect=RuntimeError("db down"))
    store.list_facts = AsyncMock(side_effect=RuntimeError("db down"))
    store.list_observations = AsyncMock(side_effect=RuntimeError("db down"))

    result = await build_memory_context(store, "master", grounding_dir=gdir)
    assert result == ""

    # models with empty content are skipped
    store = _make_store()
    empty = _model("m1", "Empty", "", ["core"])
    real = _model("m2", "Real", "Has content", ["core"])
    store.list_mental_models = AsyncMock(
        side_effect=[
            [empty, real],  # parletre core
            [empty, real],  # parletre all
            [],  # agora core
            [],  # agora all
        ]
    )

    result = await build_memory_context(store, "master", grounding_dir=gdir)
    assert "Real" in result
    assert "Empty" not in result

    # facts error degrades gracefully — models still present
    store = _make_store()
    core = _model("m1", "Core", "Content", ["core"])
    store.list_mental_models = AsyncMock(
        side_effect=[
            [core],
            [core],
            [],
            [],
        ]
    )
    store.list_facts = AsyncMock(side_effect=RuntimeError("db error"))

    result = await build_memory_context(store, "master", grounding_dir=gdir)
    assert "Core" in result
    assert "Recent" not in result
