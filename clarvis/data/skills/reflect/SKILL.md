---
name: reflect
description: Process conversation history and staged items — extract facts, consolidate, then reset sessions
---

# Reflect

Memory maintenance — extract facts from conversation history and staging inbox, then consolidate.

## Phase 1: Read pending material

Three sources to check:
1. **Your current session** — already in your context. Extract facts from what you know.
2. **Inbox** — check `~/.clarvis/staging/inbox/` for prior session transcripts (flushed automatically on session reset), user-submitted summaries, and staged files.
3. **Factoria transcript** — read `~/.clarvis/factoria/pi-session.jsonl` for Factoria's conversations since last reflect.

If nothing new across all three sources, report "nothing to reflect on" and stop.

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

1. Check `stats` for the current state of each bank
2. Run `unconsolidated` to find facts not yet grouped
3. If fewer than 10 unconsolidated facts, skip consolidation
4. Use `related_observations` to find existing observations that cover the cluster
5. Apply consolidation decisions via `consolidate`

## Phase 4: Mental model review

1. Check `stale_models` for models that need refreshing
2. Update stale models with new consolidated information

## Phase 5: Complete

1. Call `reflect_complete` to reset all agent sessions
2. Report what was processed
