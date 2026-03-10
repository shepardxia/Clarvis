---
name: reflect
description: Process conversation history and staged items — extract facts, consolidate, then reset sessions
---

# Reflect

Memory maintenance — extract facts from conversation history and staging inbox, then consolidate.

## Phase 1: Read pending material

Three sources to check:
1. **Your current session** — already in your context. Extract facts from what you know.
2. **Inbox sessions** — list `~/.clarvis/staging/inbox/` for `session_*.jsonl` files. Parse each with `ctools read_sessions '{"path": "<file>"}'`.
3. **Factoria's live session** — parse `~/.clarvis/factoria/pi-session.jsonl` with `read_sessions` (still active, not in inbox).
4. **Other inbox items** — check for non-session files in inbox (user-submitted summaries from `/remember`, staged markdown files).

If nothing new across all sources, report "nothing to reflect on" and stop.

## Phase 2: Extract facts

For each piece of pending content (including your current session):
1. Scan for salient facts (people, projects, decisions, preferences, events)
2. Use `recall` to check if each fact already exists
3. Use `remember` to store genuinely new facts with appropriate type and entities

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

## Phase 3: Consolidate

### Entity hierarchy

The memory system has three levels of abstraction:
- **Facts** — atomic units of knowledge (`remember`). Raw input.
- **Observations** — consolidated summaries grouping related facts (`consolidate` with action `create`). Each observation tracks its source fact IDs.
- **Mental models** — high-level structured knowledge (`create_model`). Authored by you, not auto-generated.

### Consolidation workflow

1. Check `stats` for the current state of each bank
2. Run `unconsolidated` to find facts not yet grouped
3. If fewer than 10 unconsolidated facts, skip consolidation
4. Use `related_observations '{"fact_ids": [...]}' ` to find existing observations that overlap
5. Apply consolidation decisions via `consolidate`

### Consolidation actions

Each decision in the `decisions` array has an `action`:

- **`create`** — New observation from a cluster of related facts.
  ```json
  {"action": "create", "text": "Summary of facts", "source_fact_ids": ["f1", "f2", "f3"]}
  ```
- **`update`** — Revise an existing observation with new source facts. Requires `observation_id`.
  ```json
  {"action": "update", "text": "Revised summary", "observation_id": "obs-1", "source_fact_ids": ["f4"]}
  ```
- **`delete`** — Remove an observation that's outdated or wrong. Requires `observation_id`.
  ```json
  {"action": "delete", "observation_id": "obs-1"}
  ```

### Order of operations

1. **Create** new observations first (group fresh facts)
2. **Update** existing observations if new facts add to them
3. **Delete** observations only if they're clearly wrong or superseded
4. Set `fact_ids_to_mark` to all fact IDs you've processed — marks them as consolidated

## Phase 4: Mental model review

1. Check `stale_models` for models that need refreshing
2. Update stale models with new consolidated information

## Phase 5: Complete

1. Call `reflect_complete` — moves inbox to `staging/digested/`, resets all agent sessions (current sessions move to inbox and restart fresh)
2. Report what was processed
