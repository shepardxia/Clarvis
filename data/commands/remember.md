---
description: Stage a session summary for Clarvis's next reflect cycle (not Claude Code's own memory)
---

Write a single concise summary of this session's knowledge-level takeaways.
Focus on **what was learned, decided, or accomplished** — not implementation
details or code changes. Combine everything into one paragraph.

Good summary example:
"Built out Clarvis memory tooling — added delete/list tools so the knowledge
graph can shrink, not just grow. Added audit logging for memory_add since cognee
discards raw files after processing. Fixed accumulator file divergence with
merge-on-save. Decided /remember should produce one consolidated summary, not
multiple atomic items — atomic splitting happens at check-in time."

Include: insights, decisions, rationale, progress, connections, preferences.
Exclude: code-level details, file paths, line numbers, verbose play-by-play.

Write the summary to a new file at `~/.clarvis/staging/remember/<unix_epoch>.md`.
Create the directory if needed. It will be processed during Clarvis's next reflect cycle.
