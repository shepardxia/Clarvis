# Reflect Skill

You are performing memory reflection -- reviewing and maintaining memory quality.

## Process

1. Search recent memories using memory_search and memory_list
2. Look for:
   - **Duplicates**: near-identical facts that should be merged (stage a forget for the weaker one + add for the consolidated version)
   - **Contradictions**: facts that conflict with each other (stage an update with the more recent or more reliable version, noting the contradiction in the reason)
   - **Vague facts**: memories that could be more specific based on other evidence (stage an update with refined content)
   - **Consolidation opportunities**: multiple related facts that should become a higher-level observation (stage an add with fact_type "observation")
   - **Stale beliefs**: opinions whose confidence should be adjusted based on new evidence
3. Stage each proposed change using the staging system
4. Do NOT directly modify memories -- stage changes for user review during checkin
5. Report what was staged and why

## Staging Format

For each proposed change, provide:
- **Action**: add, update, or forget
- **Reason**: clear explanation of why this change improves memory quality
- **Content**: the new or updated memory text
- **fact_type**: world, experience, opinion, or observation
- **confidence**: for opinions, the proposed confidence score

## Guidelines

- Be conservative: only stage changes where the improvement is clear
- Preserve temporal context -- do not strip dates or time references during consolidation
- When resolving contradictions, prefer the most recent information unless there is reason to doubt it
- Observation-type consolidations should be supported by at least 2-3 underlying facts
- Review active goals (fact_type "opinion", content starts with "[Goal]") and update their progress if evidence warrants it
- Report a summary of what was staged:
  ```
  Staged 4 changes:
  - [forget] Duplicate: "Shepard works at MIT" (superseded by more detailed version)
  - [add] Consolidated observation: "Shepard is deeply interested in probabilistic programming"
  - [update] Confidence adjustment: "Prefers GRPO over PPO" 0.7 -> 0.85
  - [update] Goal progress: "Taste model evolution" confidence 0.3 -> 0.4
  ```
