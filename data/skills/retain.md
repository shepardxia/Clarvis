# Retain Skill

You are performing memory retention -- extracting important memories from recent sessions.

## Process

1. Use the session data provided to identify salient memories
2. For each memory worth retaining:
   - Determine the fact_type: "world" (objective facts), "experience" (subjective first-person experiences), "opinion" (beliefs with confidence)
   - Call memory_add with appropriate bank, fact_type, and confidence (for opinions)
3. Focus on:
   - New facts learned (people, places, projects, preferences)
   - Preferences expressed (tools, approaches, aesthetics)
   - Decisions made or rationale given
   - Experiences described (events attended, things tried)
   - Opinions stated or implied (with confidence 0.0-1.0)
4. Skip:
   - Routine tool usage and debugging steps
   - Repetitive instructions or boilerplate
   - Content that is already stored in memory (check with memory_search first)
5. Report what was retained

## Guidelines

- Prefer specific facts over vague summaries
- Include temporal context when relevant ("as of February 2026", "started recently")
- For opinions, set confidence between 0.0 and 1.0 based on how strongly it was expressed
- Default bank is "parletre" (personal memory)
- Use "agora" bank for knowledge relevant to all agents (organizational facts, shared references)
- When in doubt about salience, retain -- the reflect skill will consolidate later
- Surface what was stored so the user can verify:
  ```
  Retained 3 facts:
  - [world] "Shepard starts at MIT CoCoSci group"
  - [world] "Working with Alex Lew on scoring rules"
  - [opinion] "Prefers GRPO over PPO" (confidence: 0.7)
  ```
