# Reflect Skill

Memory maintenance — extract facts from pending session transcripts, then consolidate.

## Phase 1: Extract (from pending sessions)

If the nudge includes pending session transcripts:

1. Scan each transcript for salient facts (people, projects, decisions, preferences, events)
2. Use `recall` to check if each fact already exists
3. Call `remember` for new facts — one fact per call, standalone sentences with temporal context

What to extract:
- People and relationships (names, roles, affiliations)
- Projects and decisions (what's being built, technical choices, progress)
- Preferences and opinions (tools, approaches, aesthetics — include confidence 0.0-1.0)
- Events and experiences (concerts, meetings, milestones)

What to skip:
- Routine tool invocations (file reads, grep, test runs)
- Ephemeral task context (open files, working directory)
- Content already in memory
- Debugging noise

Guidelines:
- fact_type: `world` (objective), `experience` (first-person), `opinion` (beliefs, 0.0-1.0 confidence)
- Write facts as standalone sentences — must make sense without surrounding context
- Preserve temporal anchors (dates, relative time)
- Include entity names (people, projects, places)
- Default bank: parletre. Use agora for shared knowledge.
- One fact per `remember` call

## Phase 2: Assess

4. Call `stats` to see counts and consolidation status
5. Call `unconsolidated` to get pending facts
6. If fewer than 10 unconsolidated facts, stop here — not enough to consolidate

## Phase 3: Consolidate (facts -> observations)

Reflect-exclusive tools: `unconsolidated`, `related_observations`, `consolidate`, `stale_models`

7. Group unconsolidated facts into thematic clusters (3+ facts per theme)
8. For each cluster, call `related_observations` to check existing observations
9. Decide per cluster: create new observation, update existing, or delete obsolete
10. Call `consolidate` once with all decisions:
    - `decisions`: list of `{"action": "create"|"update"|"delete", "text": "...", "source_fact_ids": [...], "observation_id": "..." (for update/delete)}`
    - `fact_ids_to_mark`: all fact IDs processed in this batch
    - Observations synthesize patterns — not just lists of facts

## Phase 4: Mental model review (if consolidation was done)

11. Call `stale_models` to find models needing refresh
12. Update stale models with `update_model`, create new ones if patterns emerge
13. Delete irrelevant models

## Phase 5: Report

14. Brief summary: facts retained, observations created/updated, models refreshed

## Guidelines

- Be conservative — only make changes where the improvement is clear
- Preserve temporal context — don't strip dates or "as of" qualifiers
- Observation quality — at least 2-3 supporting facts per observation
- Mental model scope — coherent topic area (person, project, domain), not too broad or narrow
- Tag mental models: `core` for always-in-context, topic tags for retrieval
- Goal review: opinion facts prefixed with `[Goal]` — adjust confidence, don't delete
- Batch consolidation — call `consolidate` once with all decisions
