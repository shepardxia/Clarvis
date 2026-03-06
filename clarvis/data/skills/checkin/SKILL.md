---
name: checkin
description: Interactive memory review — audit recent changes, review mental models, check goals
---

# Check-in

Interactive memory review and maintenance session with Shepard.

## Phase 1: Audit Review

1. Run `audit` to see recent memory activity
2. Present changes grouped by action type (added, updated, forgotten)
3. For each change or group: approve, revert (`forget` / `remember`), or edit (`update_fact`)
4. If consolidated facts have downstream observations, flag for review

## Phase 2: Mental Model Review

1. Call `list_models` to list all mental models
2. Review staleness — has new information arrived that should be reflected?
3. Propose updates to stale models, new models for emerging themes
4. After approval, execute via `update_model` or `create_model`

## Phase 3: Goal Review

1. Search for active goals: `recall` with query "active goal", filtered to `fact_type=opinion`
2. For each goal: show description, status, confidence
3. Ask about progress — update confidence as needed
4. Ask if there are new goals to add

## Phase 4: Ad-hoc Maintenance

1. Ask if the user wants to do any ad-hoc memory work:
   - Search and browse specific memories
   - Manual edits (add, update, forget)
   - Entity cleanup (merge duplicates)
   - Directive management
2. Summarize everything that changed in this session

## Phase 5: Grounding Review

1. Read grounding files from `~/.clarvis/clarvis/grounding/`
2. Review memory state vs grounding content
3. Draft updated grounding files (personality, profile, knowledge)
4. Present changes for approval, write approved files
5. If personality/directives changed, propose CLAUDE.md edits

## Guidelines

- Efficiency over thoroughness — group similar items, default to approve
- Batch operations — offer "approve all" for clearly-correct groups
- No surprises — every change gets user consent
- Mental models are opinionated summaries, not lists of facts
