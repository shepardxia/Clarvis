"""Tests for GoalSeeder — seed cross-session goals from YAML."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

pytest.importorskip("asyncpg", reason="asyncpg not installed (memory extra required)")

from clarvis.memory.goals import (
    DEFAULT_SEED_GOALS_YAML,
    GoalSeeder,
    scaffold_checkin_files,
)

# -- Tests ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_goal_seeding_lifecycle(tmp_path: Path):
    """First seed → idempotent skip → backend not ready → store failure."""
    seed_yaml = tmp_path / "seed_goals.yaml"
    seed_yaml.write_text(DEFAULT_SEED_GOALS_YAML, encoding="utf-8")

    # first seed creates goals
    backend = MagicMock()
    type(backend).ready = PropertyMock(return_value=True)
    backend.store_facts = AsyncMock(return_value=["goal-1", "goal-2", "goal-3", "goal-4", "goal-5"])
    backend.recall = AsyncMock(return_value={"results": []})

    seeder = GoalSeeder(seed_path=seed_yaml, backend=backend)
    seeded = await seeder.seed_if_needed()

    assert len(seeded) == 5
    backend.store_facts.assert_awaited_once()
    call_args = backend.store_facts.call_args
    fact_inputs = call_args.args[0]
    assert len(fact_inputs) == 5
    assert "[Goal]" in fact_inputs[0].fact_text
    assert "knowledge graph" in fact_inputs[0].fact_text
    assert fact_inputs[0].fact_type == "opinion"
    assert fact_inputs[0].confidence == 0.8
    assert call_args.kwargs.get("bank") == "parletre"

    # re-seed skips when goals already exist
    backend_with_goals = MagicMock()
    type(backend_with_goals).ready = PropertyMock(return_value=True)
    backend_with_goals.store_facts = AsyncMock(return_value=["goal-1"])
    backend_with_goals.recall = AsyncMock(
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

    seeder2 = GoalSeeder(seed_path=seed_yaml, backend=backend_with_goals)
    seeded = await seeder2.seed_if_needed()
    assert seeded == []
    backend_with_goals.store_facts.assert_not_awaited()

    # backend not ready returns empty
    backend_not_ready = MagicMock()
    type(backend_not_ready).ready = PropertyMock(return_value=False)

    seeder3 = GoalSeeder(seed_path=seed_yaml, backend=backend_not_ready)
    seeded = await seeder3.seed_if_needed()
    assert seeded == []

    # store failure returns empty
    backend_fail = MagicMock()
    type(backend_fail).ready = PropertyMock(return_value=True)
    backend_fail.store_facts = AsyncMock(side_effect=RuntimeError("DB error"))
    backend_fail.recall = AsyncMock(return_value={"results": []})

    seeder4 = GoalSeeder(seed_path=seed_yaml, backend=backend_fail)
    seeded = await seeder4.seed_if_needed()
    assert seeded == []
    backend_fail.store_facts.assert_awaited_once()


def test_scaffold_file_creation(tmp_path: Path):
    """Creation of scaffold files from bundled templates and idempotency on re-run."""
    home = tmp_path / "home"
    home.mkdir()

    checkin_key = ".pi/skills/checkin/SKILL.md"
    reflect_key = ".pi/skills/reflect/SKILL.md"

    # first run creates files from bundled templates
    created = scaffold_checkin_files(home)
    assert created["seed_goals.yaml"] is True
    assert created[checkin_key] is True
    assert created[reflect_key] is True
    assert (home / "seed_goals.yaml").exists()
    assert (home / ".pi" / "skills" / "checkin" / "SKILL.md").exists()
    assert (home / ".pi" / "skills" / "reflect" / "SKILL.md").exists()

    seed_content = (home / "seed_goals.yaml").read_text()
    assert "goals:" in seed_content
    assert "knowledge graph" in seed_content

    # Skills are copied from bundled data/skills/ templates (not Python strings)
    checkin_content = (home / ".pi" / "skills" / "checkin" / "SKILL.md").read_text()
    assert "Check-in" in checkin_content
    assert "name: checkin" in checkin_content

    reflect_content = (home / ".pi" / "skills" / "reflect" / "SKILL.md").read_text()
    assert "Reflect" in reflect_content
    assert "name: reflect" in reflect_content

    # overwrite existing files with custom content
    (home / "seed_goals.yaml").write_text("custom: true", encoding="utf-8")
    (home / ".pi" / "skills" / "checkin" / "SKILL.md").write_text("# Custom checkin", encoding="utf-8")

    # re-run does not overwrite
    created = scaffold_checkin_files(home)
    assert created["seed_goals.yaml"] is False
    assert created[checkin_key] is False
    assert created[reflect_key] is False
    assert (home / "seed_goals.yaml").read_text() == "custom: true"
    assert (home / ".pi" / "skills" / "checkin" / "SKILL.md").read_text() == "# Custom checkin"
