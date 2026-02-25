"""Seed initial cross-session goals from YAML config.

Goals are stored as opinion-type facts in Hindsight with confidence scores.
Only seeds if no goals exist yet (first-run detection).

Also provides scaffolding for the checkin skill prompt and seed goals YAML
in ``~/.clarvis/home/``.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from clarvis.agent.memory.hindsight_backend import HindsightBackend

logger = logging.getLogger(__name__)

# ── Default content for scaffolded files ─────────────────────────────────

DEFAULT_SEED_GOALS_YAML = """\
goals:
  - description: "Keep the document knowledge graph clean — merge duplicates, build community summaries, identify gaps"
    status: active
    confidence: 0.8
  - description: "Track music recommendation outcomes — update confidence on taste beliefs based on feedback"
    status: active
    confidence: 0.7
  - description: "Keep agora current with Sinthome organizational knowledge across all branches"
    status: active
    confidence: 0.7
  - description: "Build understanding of people and relationship dynamics, not just isolated facts"
    status: active
    confidence: 0.6
  - description: "Reflect on own performance — what worked, what didn't, what to adjust"
    status: active
    confidence: 0.5
"""

DEFAULT_CHECKIN_SKILL = """\
# Check-in Skill

You are Clarvis performing a memory check-in with Shepard. This is an interactive review session.

## Process

### Phase 1: Review Staged Changes
1. Call memory_staged to see pending changes from async reflect
2. For each staged change, present it to the user:
   - Show the proposed action (add/update/forget)
   - Show the content and reasoning
   - Ask: approve, edit, or skip?
3. Execute approved changes
4. Report summary of approved/skipped/edited

### Phase 2: Goal Review
5. Search for active goals: memory_search with fact_type="opinion" and query "active goal"
6. For each goal:
   - Show description and current status
   - Ask if there's progress to note
   - If progress noted, update the goal fact with new confidence/content
7. Ask if there are new goals to add

### Phase 3: Ad-hoc Maintenance
8. Ask if the user wants to do any ad-hoc memory maintenance:
   - Search and review specific memories
   - Manually add/update/forget facts
   - Knowledge graph operations (entity merge, cleanup)
9. When done, summarize what was changed in this checkin session

## Guidelines
- Be conversational and efficient — don't belabor each item
- Group similar changes for batch approval when possible
- For goals, focus on progress and blockers, not status reports
- Default to approve unless something looks wrong
"""


def scaffold_checkin_files(home_dir: Path | None = None) -> dict[str, bool]:
    """Ensure checkin-related files exist in the home project directory.

    Creates ``seed_goals.yaml`` and ``skills/checkin.md`` if they don't
    already exist.  Does not overwrite existing files.

    Returns a dict mapping filename to whether it was created.
    """
    if home_dir is None:
        home_dir = Path.home() / ".clarvis" / "home"

    home_dir = Path(home_dir).expanduser()
    created: dict[str, bool] = {}

    # seed_goals.yaml
    seed_path = home_dir / "seed_goals.yaml"
    if not seed_path.exists():
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_text(DEFAULT_SEED_GOALS_YAML, encoding="utf-8")
        created["seed_goals.yaml"] = True
        logger.info("Scaffolded %s", seed_path)
    else:
        created["seed_goals.yaml"] = False

    # skills/checkin.md
    skill_path = home_dir / "skills" / "checkin.md"
    if not skill_path.exists():
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(DEFAULT_CHECKIN_SKILL, encoding="utf-8")
        created["skills/checkin.md"] = True
        logger.info("Scaffolded %s", skill_path)
    else:
        created["skills/checkin.md"] = False

    return created


class GoalSeeder:
    """Seeds initial cross-session goals from YAML config.

    Goals are stored as opinion-type facts in Hindsight with confidence scores.
    Only seeds if no goals exist yet (first-run detection).
    """

    def __init__(self, seed_path: Path, backend: "HindsightBackend") -> None:
        self._seed_path = Path(seed_path).expanduser()
        self._backend = backend

    def _load_seed_goals(self) -> list[dict[str, Any]]:
        """Read seed goals from YAML file.

        Returns a list of goal dicts with keys: description, status, confidence.
        """
        if not self._seed_path.exists():
            logger.debug("Seed goals file not found: %s", self._seed_path)
            return []

        try:
            raw = yaml.safe_load(self._seed_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to parse seed goals YAML: %s", self._seed_path, exc_info=True)
            return []

        if not isinstance(raw, dict) or "goals" not in raw:
            logger.warning("Seed goals YAML missing 'goals' key: %s", self._seed_path)
            return []

        goals = raw["goals"]
        if not isinstance(goals, list):
            logger.warning("Seed goals 'goals' is not a list: %s", self._seed_path)
            return []

        return goals

    async def _goals_exist(self) -> bool:
        """Check if any goals already exist in Hindsight.

        Searches for opinion-type facts containing 'active goal' or with
        descriptions matching seed goal patterns.
        """
        try:
            result = await self._backend.recall(
                "active goal",
                bank="parletre",
                max_tokens=1024,
                fact_type=["opinion"],
            )
            facts = result.get("results") or result.get("facts") or []
            return len(facts) > 0
        except Exception:
            logger.debug("Goal existence check failed — assuming no goals exist", exc_info=True)
            return False

    async def seed_if_needed(self) -> list[dict[str, Any]]:
        """Check if goals exist, seed from YAML if not. Returns seeded goals."""
        if not self._backend.ready:
            logger.warning("HindsightBackend not ready — skipping goal seeding")
            return []

        goals = self._load_seed_goals()
        if not goals:
            return []

        if await self._goals_exist():
            logger.debug("Goals already exist in Hindsight — skipping seed")
            return []

        seeded: list[dict[str, Any]] = []
        for goal in goals:
            description = goal.get("description", "")
            if not description:
                continue

            confidence = goal.get("confidence", 0.5)
            status = goal.get("status", "active")

            content = f"[Goal] {description} (status: {status})"

            try:
                facts = await self._backend.retain(
                    content,
                    bank="parletre",
                    fact_type="opinion",
                    confidence=confidence,
                )
                seeded.append(
                    {
                        "description": description,
                        "status": status,
                        "confidence": confidence,
                        "facts": facts,
                    }
                )
                logger.info("Seeded goal: %s (confidence: %.1f)", description[:60], confidence)
            except Exception:
                logger.warning("Failed to seed goal: %s", description[:60], exc_info=True)

        if seeded:
            logger.info("Seeded %d goal(s) from %s", len(seeded), self._seed_path)

        return seeded
