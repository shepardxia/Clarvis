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
    from clarvis.memory.store import HindsightStore

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

### Phase 1: Audit Review
1. Run audit to see recent changes (facts added/updated since last check-in)
2. Summarize what's new — highlight anything that looks wrong or worth discussing
3. Ask: any corrections or things to forget?

### Phase 2: Mental Model Review
1. Use list_models to list current mental models
2. For each model, show title and summary
3. Ask if any models need updating or if new ones should be created

### Phase 3: Goal Review
1. Search for active goals: recall with fact_type="opinion" and query "active goal"
2. For each goal: show description and current status
3. Ask if there's progress to note — update confidence/content as needed
4. Ask if there are new goals to add

### Phase 4: Ad-hoc Maintenance
1. Ask if the user wants to do any ad-hoc memory maintenance:
   - Search and review specific memories
   - Manually add/update/forget facts
   - Knowledge graph operations (entity merge, cleanup)
2. When done, summarize what was changed in this checkin session

### Phase 5: Grounding Review
1. Read current grounding files from `~/.clarvis/home/grounding/` (placeholder files don't count)
2. Review memory state vs grounding content using recall, list_models, stats, list_directives, get_profile
3. Draft updated grounding files:
   - `01-personality.md`: directives + personality disposition + behavioral rules
   - `02-profile.md`: user preferences, communication style, key context
   - `03-knowledge.md`: breadth indicator of what's in memory
4. Present proposed changes for approval, then write approved files
5. If personality/directives changed, propose CLAUDE.md edits (clarvis reload picks them up)

## Guidelines
- Be conversational and efficient — don't belabor each item
- Group similar changes for batch approval when possible
- For goals, focus on progress and blockers, not status reports
"""


# Placeholder content for grounding files — filled in by Clarvis during first checkin.
_GROUNDING_PLACEHOLDERS: dict[str, str] = {
    "01-personality.md": """\
<!-- Clarvis personality & directives — authored during checkin -->
<!-- Replace this with personality description, active directives, and behavioral rules -->
""",
    "02-profile.md": """\
<!-- User profile — authored during checkin -->
<!-- Replace this with user preferences, communication style, and key context -->
""",
    "03-knowledge.md": """\
<!-- Knowledge summary — authored during checkin -->
<!-- Replace this with a breadth indicator of what's in memory: topics, entities, domains -->
""",
}


def scaffold_checkin_files(home_dir: Path | None = None) -> dict[str, bool]:
    """Ensure checkin-related files exist in the home project directory.

    Creates ``seed_goals.yaml``, ``skills/checkin.md``, and
    ``grounding/*.md`` placeholder files if they don't already exist.
    Does not overwrite existing files.

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

    # grounding/*.md placeholders
    grounding_dir = home_dir / "grounding"
    for filename, content in _GROUNDING_PLACEHOLDERS.items():
        rel_key = f"grounding/{filename}"
        file_path = grounding_dir / filename
        if not file_path.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            created[rel_key] = True
            logger.info("Scaffolded %s", file_path)
        else:
            created[rel_key] = False

    return created


class GoalSeeder:
    """Seeds initial cross-session goals from YAML config.

    Goals are stored as opinion-type facts in Hindsight with confidence scores.
    Only seeds if no goals exist yet (first-run detection).
    """

    def __init__(self, seed_path: Path, backend: "HindsightStore") -> None:
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
            logger.warning("HindsightStore not ready — skipping goal seeding")
            return []

        goals = self._load_seed_goals()
        if not goals:
            return []

        if await self._goals_exist():
            logger.debug("Goals already exist in Hindsight — skipping seed")
            return []

        from clarvis.vendor.hindsight.engine.retain.types import FactInput

        fact_inputs: list[FactInput] = []
        goal_meta: list[dict[str, Any]] = []

        for goal in goals:
            description = goal.get("description", "")
            if not description:
                continue

            confidence = goal.get("confidence", 0.5)
            status = goal.get("status", "active")
            content = f"[Goal] {description} (status: {status})"

            fact_inputs.append(
                FactInput(
                    fact_text=content,
                    fact_type="opinion",
                    confidence=confidence,
                )
            )
            goal_meta.append({"description": description, "status": status, "confidence": confidence})

        if not fact_inputs:
            return []

        try:
            fact_ids = await self._backend.store_facts(fact_inputs, bank="parletre")
            seeded = [{**meta, "fact_id": fid} for meta, fid in zip(goal_meta, fact_ids)]
            logger.info("Seeded %d goal(s) from %s", len(seeded), self._seed_path)
            return seeded
        except Exception:
            logger.warning("Failed to seed goals from %s", self._seed_path, exc_info=True)
            return []
