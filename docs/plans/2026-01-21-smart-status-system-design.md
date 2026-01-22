# Smart Status System Design

## Problem Statement

The current `status.sh` maps single JSONL messages directly to status states. This causes:

1. **State flicker** - Status jumps between "thinking" and "running" during multi-tool sequences
2. **Coarse activity detection** - Can't distinguish reading files vs writing code vs running commands
3. **No context** - Each message evaluated in isolation; can't infer actual workflow phase

## Goals

- Stable, coherent status that reflects Claude's actual workflow phase
- Granular activity states (reading, writing, executing, thinking)
- Use recent message history to infer context and smooth transitions
- Minimal latency impact on polling

## Design

### Status States

| State | Meaning | Visual |
|-------|---------|--------|
| `idle` | No activity for 5+ minutes | Gray, static |
| `awaiting` | Finished, waiting for user input | Blue, gentle pulse |
| `thinking` | Processing user input, planning | Yellow, wave animation |
| `reading` | Reading files, exploring codebase | Blue, scanning animation |
| `writing` | Editing files, writing code | Green, typing animation |
| `executing` | Running bash commands, agents | Green, active pulse |
| `reviewing` | Looking at results, tool outputs | Yellow, contemplative |

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      status.sh                               │
├─────────────────────────────────────────────────────────────┤
│  1. File watcher (existing)                                  │
│     - Detect JSONL changes via stat                          │
│     - Cache for unchanged files                              │
├─────────────────────────────────────────────────────────────┤
│  2. Message window (NEW)                                     │
│     - Read last N messages (N=10-20)                         │
│     - Extract: type, tool_name, timestamp                    │
│     - Build activity timeline                                │
├─────────────────────────────────────────────────────────────┤
│  3. State inference engine (NEW)                             │
│     - Analyze message patterns                               │
│     - Apply state machine rules                              │
│     - Output: status + confidence                            │
├─────────────────────────────────────────────────────────────┤
│  4. State smoother (NEW)                                     │
│     - Prevent rapid state changes                            │
│     - Minimum dwell time per state                           │
│     - Hysteresis for transitions                             │
└─────────────────────────────────────────────────────────────┘
```

### State Inference Rules

**Rule 1: Tool-based classification**
```
Read, Glob, Grep, Task(Explore) → reading
Edit, Write, NotebookEdit       → writing
Bash, Task(other)               → executing
```

**Rule 2: Pattern detection (look at last 5-10 messages)**
```
Multiple Read/Glob in sequence  → reading (high confidence)
Edit followed by Bash           → writing (running tests/build)
User message → assistant text   → thinking
Tool result → assistant text    → reviewing
```

**Rule 3: Recency weighting**
- Last message: weight 1.0
- 2nd to last: weight 0.7
- 3rd to last: weight 0.4
- Older: weight 0.2

**Rule 4: State persistence (smoother)**
```
Minimum dwell times:
- thinking: 2 seconds (allow quick transitions to action)
- reading: 3 seconds
- writing: 3 seconds
- executing: 5 seconds (bash can be quick, but don't flicker)
- reviewing: 2 seconds
```

### Data Flow

```
JSONL file changed
       │
       ▼
┌──────────────────┐
│ Read last 15     │
│ messages         │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Extract features │
│ - tool_name      │
│ - message_type   │
│ - has_text       │
│ - timestamp      │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Classify each    │
│ message's intent │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Weighted vote    │
│ for current      │
│ activity phase   │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Apply smoother   │
│ (check dwell     │
│  time, hysteresis│
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Output status    │
│ JSON             │
└──────────────────┘
```

### Implementation Approach

**Option A: Enhanced bash script**
- Keep status.sh, add jq-based message window analysis
- Pros: No new dependencies, simple deployment
- Cons: Complex jq queries, harder to maintain

**Option B: Python script** (Recommended)
- Rewrite as `status.py`, use existing `github-tools` uv environment
- Pros: Clean logic, easy to extend, better JSON handling
- Cons: Slightly slower startup (mitigated by caching)

**Option C: Swift integration**
- Move logic into ClaudeStatusOverlay.swift
- Pros: Single binary, native performance
- Cons: More complex build, harder to iterate

### Recommended: Option B (Python)

```python
# Pseudocode structure

def get_status():
    session_file = find_latest_session()
    if not changed_since_last_check(session_file):
        return cached_status_with_timeout_check()

    messages = read_last_n_messages(session_file, n=15)
    features = extract_features(messages)
    raw_status = infer_status(features)
    smoothed = apply_smoother(raw_status)

    return smoothed

def infer_status(features):
    # Weighted voting based on recent activity
    votes = defaultdict(float)

    for i, msg in enumerate(reversed(features)):
        weight = [1.0, 0.7, 0.4, 0.2, 0.1][min(i, 4)]
        activity = classify_message(msg)
        votes[activity] += weight

    return max(votes, key=votes.get)

def classify_message(msg):
    if msg.tool in ['Read', 'Glob', 'Grep']:
        return 'reading'
    if msg.tool in ['Edit', 'Write']:
        return 'writing'
    if msg.tool in ['Bash', 'Task']:
        return 'executing'
    if msg.type == 'assistant' and msg.has_text:
        return 'thinking' if no_recent_tool else 'reviewing'
    return 'thinking'
```

### Cache Strategy

```
/tmp/claude-status-cache.json
{
  "session_file": "/path/to/session.jsonl",
  "file_mtime": 1234567890,
  "file_size": 12345,
  "last_status": "writing",
  "status_since": 1234567880,
  "last_check": 1234567895
}
```

- Check file stat first (fast)
- If unchanged and status_since within dwell time, return cached
- If unchanged and past timeout threshold, return awaiting/idle
- If changed, do full analysis

### Testing Plan

1. **Unit tests** for classify_message() with various message types
2. **Scenario tests** with recorded JSONL sequences:
   - Multi-file read sequence → should stay "reading"
   - Edit-Bash-Edit cycle → should show "writing" not flicker
   - Long thinking pause → should transition smoothly to "thinking"
3. **Visual testing** with actual Claude sessions

### Migration Path

1. Create `status.py` alongside `status.sh`
2. Update widget.json or restart.sh to call Python version
3. Test for a few days
4. Remove status.sh once stable

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `status.py` | Create | New smart status logic |
| `status.sh` | Keep (backup) | Fallback if Python fails |
| `restart.sh` | Modify | Call status.py instead |
| `ClaudeStatusOverlay.swift` | Minor update | Add new status states to avatar |

## Open Questions

1. Should we add a "compacting" state when context is being summarized?
2. Should tool-specific substates be shown (e.g., "Reading: config.py")?
3. Should we track token usage / cost in the status display?

---

*Design created: 2026-01-21*
*Status: Ready for implementation*
