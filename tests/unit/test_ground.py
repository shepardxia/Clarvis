"""Memory grounding — budget allocation, visibility filtering, grounding files, error resilience."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from clarvis.memory.ground import (
    _format_fact,
    _format_model,
    _format_observation,
    _read_grounding_files,
    build_memory_context,
)

# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def store():
    s = MagicMock()
    type(s).ready = PropertyMock(return_value=True)
    s.visible_banks.return_value = ["parletre", "agora"]
    s.list_mental_models = AsyncMock(return_value=[])
    s.get_bank_stats = AsyncMock(return_value={"total_facts": 10, "pending": 2})
    s.list_facts = AsyncMock(return_value={"items": [], "total": 0})
    s.list_observations = AsyncMock(return_value=[])
    return s


@pytest.fixture
def empty_grounding(tmp_path):
    """Return a grounding_dir that exists but has no files."""
    d = tmp_path / "grounding"
    d.mkdir()
    return d


def _model(id: str, name: str, content: str, tags: list[str] | None = None) -> dict:
    return {"id": id, "name": name, "content": content, "tags": tags or []}


def _fact(text: str, fact_type: str = "experience", date: str | None = None) -> dict:
    return {"text": text, "fact_type": fact_type, "occurred_start": date, "mentioned_at": date}


def _observation(text: str, proof_count: int = 1) -> dict:
    return {"text": text, "proof_count": proof_count}


# ── build_memory_context ─────────────────────────────────────


class TestBuildMemoryContext:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_core_models_always_included(self, store, empty_grounding):
        core = _model("m1", "Music Taste", "Heavy/dark/experimental", ["core"])
        store.list_mental_models = AsyncMock(
            side_effect=[
                [core],  # parletre core
                [core],  # parletre all
                [],  # agora core
                [],  # agora all
            ]
        )

        result = await build_memory_context(store, "master", grounding_dir=empty_grounding)
        assert "<memory_context>" in result
        assert "Music Taste" in result
        assert "Heavy/dark/experimental" in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_extra_models_fill_budget(self, store, empty_grounding):
        core = _model("m1", "Core Model", "Core content", ["core"])
        extra = _model("m2", "Extra Model", "Extra content", ["research"])
        store.list_mental_models = AsyncMock(
            side_effect=[
                [core],  # parletre core
                [core, extra],  # parletre all
                [],  # agora core
                [],  # agora all
            ]
        )

        result = await build_memory_context(store, "master", grounding_dir=empty_grounding)
        assert "Core Model" in result
        assert "Extra Model" in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_extra_models_excluded_when_over_budget(self, store, empty_grounding):
        core = _model("m1", "Core Model", "X" * 100, ["core"])
        extra = _model("m2", "Extra Model", "Y" * 500, ["research"])
        store.list_mental_models = AsyncMock(
            side_effect=[
                [core],  # parletre core
                [core, extra],  # parletre all
                [],  # agora core
                [],  # agora all
            ]
        )

        result = await build_memory_context(
            store,
            "master",
            token_budget=30,
            grounding_dir=empty_grounding,
        )
        assert "Core Model" in result
        assert "Extra Model" not in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_multiple_banks(self, store, empty_grounding):
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

        result = await build_memory_context(store, "master", grounding_dir=empty_grounding)
        assert "### parletre" in result
        assert "### agora" in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_visibility_filters_banks(self, store, empty_grounding):
        store.visible_banks.return_value = ["agora"]
        model = _model("m1", "Shared", "Shared content", ["core"])
        store.list_mental_models = AsyncMock(
            side_effect=[
                [model],  # agora core
                [model],  # agora all
            ]
        )

        result = await build_memory_context(store, "all", grounding_dir=empty_grounding)
        assert "### agora" in result
        assert "### parletre" not in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_graceful_on_list_error(self, store, empty_grounding):
        store.list_mental_models = AsyncMock(side_effect=RuntimeError("db down"))
        store.get_bank_stats = AsyncMock(side_effect=RuntimeError("db down"))
        store.list_facts = AsyncMock(side_effect=RuntimeError("db down"))
        store.list_observations = AsyncMock(side_effect=RuntimeError("db down"))
        result = await build_memory_context(store, "master", grounding_dir=empty_grounding)
        assert result == ""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_skips_models_with_empty_content(self, store, empty_grounding):
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

        result = await build_memory_context(store, "master", grounding_dir=empty_grounding)
        assert "Real" in result
        assert "Empty" not in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_bank_stats_included(self, store, empty_grounding):
        core = _model("m1", "Core", "Content", ["core"])
        store.list_mental_models = AsyncMock(
            side_effect=[
                [core],  # parletre core
                [core],  # parletre all
                [],  # agora core
                [],  # agora all
            ]
        )
        store.get_bank_stats = AsyncMock(return_value={"total_facts": 42, "pending": 5})

        result = await build_memory_context(store, "master", grounding_dir=empty_grounding)
        assert "Stats:" in result
        assert "total_facts: 42" in result


# ── Grounding files ──────────────────────────────────────────


class TestGroundingFiles:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_grounding_files_included(self, store, tmp_path):
        gdir = tmp_path / "grounding"
        gdir.mkdir()
        (gdir / "01-personality.md").write_text("I am Clarvis.", encoding="utf-8")
        (gdir / "02-profile.md").write_text("User likes metal.", encoding="utf-8")

        result = await build_memory_context(store, "master", grounding_dir=gdir)
        assert "I am Clarvis." in result
        assert "User likes metal." in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_grounding_files_sorted_by_name(self, tmp_path):
        gdir = tmp_path / "grounding"
        gdir.mkdir()
        (gdir / "02-second.md").write_text("Second.", encoding="utf-8")
        (gdir / "01-first.md").write_text("First.", encoding="utf-8")

        text = _read_grounding_files(gdir)
        assert text.index("First.") < text.index("Second.")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_grounding_files_without_store(self, tmp_path):
        """Grounding files work even if store is None."""
        gdir = tmp_path / "grounding"
        gdir.mkdir()
        (gdir / "01-personality.md").write_text("I am Clarvis.", encoding="utf-8")

        result = await build_memory_context(None, "master", grounding_dir=gdir)
        assert "<memory_context>" in result
        assert "I am Clarvis." in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_nonexistent_grounding_dir(self, store, tmp_path):
        """Falls back to models-only when grounding dir doesn't exist."""
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

    def test_read_grounding_files_empty_dir(self, empty_grounding):
        assert _read_grounding_files(empty_grounding) == ""

    def test_read_grounding_files_nonexistent(self, tmp_path):
        assert _read_grounding_files(tmp_path / "nope") == ""

    def test_read_grounding_files_skips_empty(self, tmp_path):
        gdir = tmp_path / "grounding"
        gdir.mkdir()
        (gdir / "01-empty.md").write_text("", encoding="utf-8")
        (gdir / "02-real.md").write_text("Real content.", encoding="utf-8")

        text = _read_grounding_files(gdir)
        assert text == "Real content."


# ── Recent facts & observations ──────────────────────────────


class TestRecentFactsAndObservations:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_recent_facts_included(self, store, empty_grounding):
        core = _model("m1", "Core", "Content", ["core"])
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

        result = await build_memory_context(store, "master", grounding_dir=empty_grounding)
        assert "**Recent facts**" in result
        assert "Trained wake word model R7" in result
        assert "[experience]" in result
        assert "2026-03-01" in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_recent_observations_included(self, store, empty_grounding):
        core = _model("m1", "Core", "Content", ["core"])
        store.list_mental_models = AsyncMock(
            side_effect=[
                [core],
                [core],  # parletre
                [],
                [],  # agora
            ]
        )
        store.list_observations = AsyncMock(
            return_value=[
                _observation("User prefers dark themes", 3),
                _observation("Single observation"),
            ]
        )

        result = await build_memory_context(store, "master", grounding_dir=empty_grounding)
        assert "**Recent observations**" in result
        assert "User prefers dark themes" in result
        assert "(x3)" in result
        assert "Single observation" in result
        assert "(x1)" not in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_facts_excluded_when_over_budget(self, store, empty_grounding):
        core = _model("m1", "Core", "X" * 80, ["core"])
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
                "items": [_fact("Should not appear", "experience")],
                "total": 1,
            }
        )

        result = await build_memory_context(
            store,
            "master",
            token_budget=30,
            grounding_dir=empty_grounding,
        )
        assert "Should not appear" not in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_facts_error_graceful(self, store, empty_grounding):
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

        result = await build_memory_context(store, "master", grounding_dir=empty_grounding)
        assert "Core" in result
        assert "Recent" not in result


# ── _format_fact / _format_observation ────────────────────────


class TestFormatters:
    def test_format_fact_with_date(self):
        f = _fact("Something happened", "experience", "2026-03-01")
        result = _format_fact(f)
        assert result == "- [experience] Something happened (2026-03-01)"

    def test_format_fact_no_date(self):
        f = _fact("Dateless fact", "world")
        result = _format_fact(f)
        assert result == "- [world] Dateless fact"

    def test_format_fact_empty_text(self):
        assert _format_fact({"text": "", "fact_type": "world"}) == ""

    def test_format_observation_with_count(self):
        result = _format_observation(_observation("Repeated pattern", 5))
        assert result == "- Repeated pattern (x5)"

    def test_format_observation_single(self):
        result = _format_observation(_observation("Once"))
        assert result == "- Once"

    def test_format_observation_empty(self):
        assert _format_observation({"text": ""}) == ""


# ── _format_model ─────────────────────────────────────────────


class TestFormatModel:
    def test_model_with_tags(self):
        result = _format_model({"name": "Taste", "content": "Heavy", "tags": ["core", "music"]})
        assert "[core, music]" in result

    def test_no_name_returns_content_only(self):
        result = _format_model({"name": "", "content": "Just content", "tags": []})
        assert result == "Just content"
