"""Tests for GoalSeeder — seed cross-session goals from YAML."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

pytest.importorskip("asyncpg", reason="asyncpg not installed (memory extra required)")

from clarvis.agent.memory.goals import (
    DEFAULT_SEED_GOALS_YAML,
    GoalSeeder,
    scaffold_checkin_files,
)

# -- Fixtures ---------------------------------------------------------------


@pytest.fixture()
def seed_yaml(tmp_path: Path) -> Path:
    """Write default seed goals YAML to a temp file."""
    path = tmp_path / "seed_goals.yaml"
    path.write_text(DEFAULT_SEED_GOALS_YAML, encoding="utf-8")
    return path


@pytest.fixture()
def empty_yaml(tmp_path: Path) -> Path:
    """Write an empty YAML file."""
    path = tmp_path / "empty.yaml"
    path.write_text("{}", encoding="utf-8")
    return path


@pytest.fixture()
def bad_yaml(tmp_path: Path) -> Path:
    """Write invalid YAML content."""
    path = tmp_path / "bad.yaml"
    path.write_text("goals: not_a_list", encoding="utf-8")
    return path


@pytest.fixture()
def mock_backend():
    """Mocked HindsightStore for goal tests."""
    backend = MagicMock()
    type(backend).ready = PropertyMock(return_value=True)
    backend.store_facts = AsyncMock(return_value=["goal-1", "goal-2", "goal-3", "goal-4", "goal-5"])
    backend.recall = AsyncMock(return_value={"results": []})
    return backend


@pytest.fixture()
def mock_backend_with_goals():
    """Mocked HindsightStore that already has goals."""
    backend = MagicMock()
    type(backend).ready = PropertyMock(return_value=True)
    backend.store_facts = AsyncMock(return_value=["goal-1"])
    backend.recall = AsyncMock(
        return_value={
            "results": [
                {
                    "id": "existing-goal",
                    "fact_type": "opinion",
                    "content": "[Goal] Some existing goal (status: active)",
                }
            ]
        }
    )
    return backend


# -- seed_if_needed tests ---------------------------------------------------


@pytest.mark.asyncio
async def test_seed_if_needed_creates_goals(seed_yaml, mock_backend):
    """seed_if_needed should store all goals as FactInput objects."""
    seeder = GoalSeeder(seed_path=seed_yaml, backend=mock_backend)
    seeded = await seeder.seed_if_needed()

    assert len(seeded) == 5
    mock_backend.store_facts.assert_awaited_once()

    # Verify FactInput objects were constructed correctly
    call_args = mock_backend.store_facts.call_args
    fact_inputs = call_args.args[0]
    assert len(fact_inputs) == 5
    assert "[Goal]" in fact_inputs[0].fact_text
    assert "knowledge graph" in fact_inputs[0].fact_text
    assert fact_inputs[0].fact_type == "opinion"
    assert fact_inputs[0].confidence == 0.8
    assert call_args.kwargs.get("bank") == "parletre"


@pytest.mark.asyncio
async def test_seed_if_needed_skips_when_goals_exist(seed_yaml, mock_backend_with_goals):
    """seed_if_needed should not store anything if goals already exist."""
    seeder = GoalSeeder(seed_path=seed_yaml, backend=mock_backend_with_goals)
    seeded = await seeder.seed_if_needed()

    assert seeded == []
    mock_backend_with_goals.store_facts.assert_not_awaited()


@pytest.mark.asyncio
async def test_seed_if_needed_skips_when_backend_not_ready(seed_yaml):
    """seed_if_needed should return empty list if backend is not ready."""
    backend = MagicMock()
    type(backend).ready = PropertyMock(return_value=False)

    seeder = GoalSeeder(seed_path=seed_yaml, backend=backend)
    seeded = await seeder.seed_if_needed()

    assert seeded == []


@pytest.mark.asyncio
async def test_seed_if_needed_handles_store_failure(seed_yaml, mock_backend):
    """seed_if_needed should return empty on store_facts failure."""
    mock_backend.store_facts = AsyncMock(side_effect=RuntimeError("DB error"))

    seeder = GoalSeeder(seed_path=seed_yaml, backend=mock_backend)
    seeded = await seeder.seed_if_needed()

    # Batch store failed, no goals seeded
    assert seeded == []
    mock_backend.store_facts.assert_awaited_once()


# -- scaffold_checkin_files tests -------------------------------------------


def test_scaffold_creates_files(tmp_path):
    """scaffold_checkin_files should create both files in empty directory."""
    home = tmp_path / "home"
    home.mkdir()

    created = scaffold_checkin_files(home)

    assert created["seed_goals.yaml"] is True
    assert created["skills/checkin.md"] is True
    assert (home / "seed_goals.yaml").exists()
    assert (home / "skills" / "checkin.md").exists()

    # Verify content is correct
    seed_content = (home / "seed_goals.yaml").read_text()
    assert "goals:" in seed_content
    assert "knowledge graph" in seed_content

    skill_content = (home / "skills" / "checkin.md").read_text()
    assert "Check-in Skill" in skill_content
    assert "Phase 1" in skill_content


def test_scaffold_skips_existing_files(tmp_path):
    """scaffold_checkin_files should not overwrite existing files."""
    home = tmp_path / "home"
    home.mkdir()

    # Pre-create files with custom content
    seed = home / "seed_goals.yaml"
    seed.write_text("custom: true", encoding="utf-8")

    skills_dir = home / "skills"
    skills_dir.mkdir()
    skill = skills_dir / "checkin.md"
    skill.write_text("# Custom checkin", encoding="utf-8")

    created = scaffold_checkin_files(home)

    assert created["seed_goals.yaml"] is False
    assert created["skills/checkin.md"] is False

    # Verify original content preserved
    assert seed.read_text() == "custom: true"
    assert skill.read_text() == "# Custom checkin"
