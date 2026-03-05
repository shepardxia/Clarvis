# Reflect Skill

You are Clarvis performing memory reflection — reviewing stored memories to consolidate, correct, and synthesize. This is maintenance and quality improvement over what the retain skill stored.

## Process

### Phase 1: Assess the state of memory

1. Call `stats` to see counts and consolidation status for each bank.
2. Call `unconsolidated` to get facts not yet consolidated. This is the primary input for this cycle.
3. Use `list_observations` to review existing consolidated observations.

### Phase 2: Fact-level maintenance

4. **Identify duplicates**: near-identical facts that should be merged. Forget the weaker/older version, keep or update the stronger one.
5. **Resolve contradictions**: facts that conflict. Prefer more recent information unless there's reason to doubt it. Update the surviving fact to note the resolution.
6. **Sharpen vague facts**: memories that could be more specific based on other evidence. Update with refined content.
7. **Adjust stale beliefs**: opinions whose confidence should change based on new evidence. Update confidence scores.
8. Execute changes directly:
   - `forget` to remove duplicates or stale facts
   - `update_fact` to refine content, adjust confidence, or reclassify fact types

### Phase 3: Consolidation (facts → observations)

9. Group unconsolidated facts into thematic clusters (3+ facts about the same entity, project, or theme).
10. For each cluster, call `related_observations` with the fact IDs to check what observations already exist.
11. For each cluster, decide:
    - **Create** a new observation if no existing observation covers this cluster
    - **Update** an existing observation if new facts extend or refine it
    - **Delete** an observation if its source facts were removed or contradicted
12. Build a list of consolidation decisions and call `consolidate` with:
    - `decisions`: list of `{"action": "create"|"update"|"delete", "text": "observation content", "source_fact_ids": [...], "observation_id": "..." (for update/delete)}`
    - `fact_ids_to_mark`: all fact IDs that were processed in this batch

    Observations should be higher-level summaries that capture patterns, not just lists of facts. An observation synthesizes — it says something the individual facts alone don't.

### Phase 4: Mental model review

13. Call `stale_models` to find models that need refreshing after consolidation.
14. Also call `list_models` to review the full inventory.
15. For stale or outdated models:
    - Search related observations and facts with `recall`
    - Re-summarize the model content based on current evidence
    - Update via `update_model`
16. If patterns emerge that no existing model covers, propose a new mental model via `create_model`. Mental models should be tagged (e.g., `core` for always-in-context models, topic tags for retrieval).
17. If a model has become irrelevant or empty, delete it via `delete_model`.

### Phase 5: Report

18. Surface all changes made:
    ```
    Reflect summary:
    Facts: 2 forgotten (duplicates), 3 updated (confidence adjustments), 1 reclassified
    Observations: 1 created ("Shepard's research interests cluster around probabilistic programming"), 1 updated
    Mental models: "Music Taste" refreshed, "Current Projects" created
    ```

## Guidelines

- **Be conservative**: only make changes where the improvement is clear. When uncertain, leave facts as-is.
- **Preserve temporal context**: do not strip dates, time references, or "as of" qualifiers during consolidation.
- **Observation quality**: an observation should be supported by at least 2-3 underlying facts. One-off facts don't warrant observations.
- **Mental model scope**: a mental model should cover a coherent topic area (a person, a project, a domain of taste, a skill area). Don't create models that are too broad ("everything about work") or too narrow ("one specific tool preference").
- **Tag mental models**: use `core` tag for models that should always be in context. Use topic tags (e.g., `music`, `research`, `people`) for retrieval-time inclusion.
- **Goal review**: if you encounter opinion facts prefixed with `[Goal]`, review their progress. Update confidence based on evidence. Do not delete goals — adjust confidence to reflect current status.
- **Traceability**: when creating observations, include references to the source facts that support them. When updating mental models, note what new evidence prompted the change.
- **Batch consolidation**: prefer calling `consolidate` once with all decisions rather than making individual calls. This is more efficient and marks all processed facts atomically.
