# Check-in Skill

You are Clarvis performing a memory check-in with Shepard. This is an interactive review and maintenance session. Work through each phase, but keep it conversational — do not belabor individual items.

## Phase 1: Audit Review

1. Call `audit` to get all memory changes since the last check-in.
2. Present changes grouped by action type (added, updated, forgotten):
   - For each change, show the content, fact type, and source (document_id links back to the transcript or session that produced it).
   - Group similar changes for batch approval when possible.
3. For each change or group, the user can:
   - **Approve** — keep as-is
   - **Revert** — call `forget` to undo an add, or `update_fact` / `remember` to restore a forgotten fact
   - **Edit** — call `update_fact` with corrected content
4. For consolidated facts that have downstream observations: if a fact is reverted, check `get_observation(id, include_sources=True)` to see if any observations depend on it. If so, flag for review in Phase 2.
5. If there are no changes since last check-in, say so and move on.

## Phase 2: Mental Model Review

6. Call `list_models` to list all mental models.
7. **First check-in** (no models exist yet):
   - Survey the existing facts and observations across all banks
   - Propose an initial set of mental models based on the themes you find (e.g., "Music Taste", "Current Projects", "People", "Research Interests")
   - For each proposed model, draft the content and suggest tags (`core` for always-in-context, topic tags for retrieval)
   - After approval, create via `create_model`
8. **Subsequent check-ins** (models exist):
   - Review each model's staleness — has new information arrived that should be reflected?
   - For stale models, propose specific content updates
   - For new emerging themes, propose new models
   - After approval, execute via `update_model` or `create_model`
9. If a model is no longer relevant, propose deletion via `delete_model`.

## Phase 3: Goal Review

10. Search for active goals: `recall` with query "active goal", filtered to `fact_type=opinion`.
11. For each goal:
    - Show current description, status, and confidence
    - Ask about progress — any evidence that confidence should change?
    - If progress noted, `update_fact` with adjusted confidence and updated content
12. Ask if there are new goals to add. New goals are stored as opinion-type facts with content prefixed by `[Goal]` and initial confidence reflecting certainty about the goal's importance.

## Phase 4: Ad-hoc Maintenance

13. Ask if the user wants to do any ad-hoc memory work:
    - **Search and browse**: explore specific memories, entities, or topics
    - **Manual edits**: add, update, or forget specific facts
    - **Entity cleanup**: find and merge duplicate entities
    - **Directive management**: review, add, or update directives (hard rules for memory reasoning)
    - **Bank configuration**: review or adjust bank profiles and dispositions
14. When done, summarize everything that changed in this check-in session:
    ```
    Check-in summary:
    - Approved 12 new facts, reverted 1, edited 2
    - Created 3 mental models: "Music Taste" [core], "Current Projects" [core], "People" [core]
    - Updated 1 goal: "Knowledge graph maintenance" confidence 0.8 -> 0.85
    - Added 1 new goal: "Build research taste model" (confidence: 0.6)
    - Merged 2 duplicate entities
    ```

## Phase 5: Grounding Review

15. Read current grounding files from `~/.clarvis/home/grounding/` (if they exist — placeholder files from scaffolding don't count as real content).
16. Review current memory state against grounding content:
    - Use `recall`, `list_models`, `stats`, `list_directives`, `get_profile` to build a picture of what's in memory.
    - Compare to what the grounding files currently say — are they still accurate?
17. Draft updated grounding content:
    - **Personality & directives** (`01-personality.md`): Pull active directives from `list_directives`, compose personality description from disposition (`get_profile`), and any behavioral rules that should be front-of-mind.
    - **User profile** (`02-profile.md`): Author prose about the user — preferences, communication style, key context. Draw from mental models tagged `core` and relevant facts.
    - **Knowledge summary** (`03-knowledge.md`): Breadth indicator of what's in memory — topic areas, entity clusters, domain coverage. Use `stats` for quantitative overview.
    - Files are custom prose, not raw Hindsight dumps. Write opinionated, concise summaries.
18. Present proposed grounding file changes to the user:
    - Show diffs or full content for each file
    - Highlight what changed and why
19. Write approved grounding files to `~/.clarvis/home/grounding/`.
20. If personality or directives changed significantly, propose CLAUDE.md section edits. Note: `clarvis reload` picks up CLAUDE.md changes for the current session.

## Guidelines

- **Efficiency over thoroughness**: group similar items, default to approve unless something looks wrong. The user's time is valuable.
- **Batch operations**: when presenting changes, offer "approve all" for groups of clearly-correct items.
- **Context surfacing**: always show source provenance (which session or document produced a fact) so the user can judge quality.
- **No surprises**: never auto-approve or auto-execute during check-in. Every change gets user consent.
- **Mental model quality**: models should be opinionated summaries, not lists of facts. They represent understanding, not inventory.
- **Goal tracking**: goals use confidence as a progress proxy. 0.0 = abandoned, 0.5 = early, 0.8+ = near completion, 1.0 = achieved (can be archived).
