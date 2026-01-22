# Smart Status System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the simple status.sh with a Python-based smart status system that uses message history and weighted voting to determine coherent status states.

**Architecture:** Python script reads last 15 JSONL messages, classifies each by tool/type, applies recency-weighted voting to determine status, and uses a smoother to prevent rapid state changes. Outputs JSON to /tmp/claude-status.json for the Swift overlay to consume.

**Tech Stack:** Python 3.12, standard library only (json, pathlib, time), uv for execution

---

## Task 1: Create Test Fixtures

**Files:**
- Create: `tests/fixtures/reading_sequence.jsonl`
- Create: `tests/fixtures/writing_sequence.jsonl`
- Create: `tests/fixtures/mixed_sequence.jsonl`

**Step 1: Create tests directory**

```bash
mkdir -p "/Users/shepardxia/Library/Application Support/Übersicht/widgets/claude-status.widget/tests/fixtures"
```

**Step 2: Create reading sequence fixture**

Create `tests/fixtures/reading_sequence.jsonl` with 5 consecutive Read/Glob messages:

```json
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Glob","input":{}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"1"}]}}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"2"}]}}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{}}]}}
```

**Step 3: Create writing sequence fixture**

Create `tests/fixtures/writing_sequence.jsonl` with Edit/Write messages:

```json
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"1"}]}}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"2"}]}}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{}}]}}
```

**Step 4: Create mixed sequence fixture**

Create `tests/fixtures/mixed_sequence.jsonl` with varied activity:

```json
{"type":"user","message":{"content":[{"type":"text","text":"Fix the bug"}]}}
{"type":"assistant","message":{"content":[{"type":"text","text":"I'll investigate..."}]}}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Grep","input":{}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"1"}]}}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"2"}]}}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"3"}]}}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{}}]}}
```

**Step 5: Commit**

```bash
cd "/Users/shepardxia/Library/Application Support/Übersicht/widgets/claude-status.widget"
git add tests/
git commit -m "test: add JSONL fixtures for status classification"
```

---

## Task 2: Create Message Classifier Module

**Files:**
- Create: `status_lib/classifier.py`
- Create: `tests/test_classifier.py`

**Step 1: Create status_lib directory**

```bash
mkdir -p "/Users/shepardxia/Library/Application Support/Übersicht/widgets/claude-status.widget/status_lib"
touch "/Users/shepardxia/Library/Application Support/Übersicht/widgets/claude-status.widget/status_lib/__init__.py"
```

**Step 2: Write the failing test**

Create `tests/test_classifier.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from status_lib.classifier import classify_message, Activity

def test_read_tool_classifies_as_reading():
    msg = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}}
    assert classify_message(msg) == Activity.READING

def test_edit_tool_classifies_as_writing():
    msg = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit"}]}}
    assert classify_message(msg) == Activity.WRITING

def test_bash_tool_classifies_as_executing():
    msg = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}
    assert classify_message(msg) == Activity.EXECUTING

def test_text_response_classifies_as_thinking():
    msg = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Let me think..."}]}}
    assert classify_message(msg) == Activity.THINKING

def test_user_message_classifies_as_thinking():
    msg = {"type": "user", "message": {"content": [{"type": "text", "text": "Help me"}]}}
    assert classify_message(msg) == Activity.THINKING

def test_tool_result_classifies_as_reviewing():
    msg = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "123"}]}}
    assert classify_message(msg) == Activity.REVIEWING
```

**Step 3: Run test to verify it fails**

```bash
cd "/Users/shepardxia/Library/Application Support/Übersicht/widgets/claude-status.widget"
python -m pytest tests/test_classifier.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'status_lib.classifier'"

**Step 4: Write classifier implementation**

Create `status_lib/classifier.py`:

```python
"""Message classifier for Claude status detection."""

from enum import Enum
from typing import Any

class Activity(Enum):
    IDLE = "idle"
    AWAITING = "awaiting"
    THINKING = "thinking"
    READING = "reading"
    WRITING = "writing"
    EXECUTING = "executing"
    REVIEWING = "reviewing"

# Tool name to activity mapping
TOOL_ACTIVITIES = {
    # Reading tools
    "Read": Activity.READING,
    "Glob": Activity.READING,
    "Grep": Activity.READING,
    "LS": Activity.READING,
    "NotebookRead": Activity.READING,
    # Writing tools
    "Edit": Activity.WRITING,
    "Write": Activity.WRITING,
    "NotebookEdit": Activity.WRITING,
    # Executing tools
    "Bash": Activity.EXECUTING,
    "Task": Activity.EXECUTING,
    "WebFetch": Activity.EXECUTING,
    "WebSearch": Activity.EXECUTING,
}

def get_tool_name(msg: dict[str, Any]) -> str | None:
    """Extract tool name from message if present."""
    try:
        content = msg.get("message", {}).get("content", [])
        if content and isinstance(content, list):
            first = content[0]
            if first.get("type") == "tool_use":
                return first.get("name")
    except (KeyError, IndexError, TypeError):
        pass
    return None

def is_tool_result(msg: dict[str, Any]) -> bool:
    """Check if message is a tool result."""
    try:
        content = msg.get("message", {}).get("content", [])
        if content and isinstance(content, list):
            return content[0].get("type") == "tool_result"
    except (KeyError, IndexError, TypeError):
        pass
    return False

def classify_message(msg: dict[str, Any]) -> Activity:
    """Classify a single message into an activity type."""
    msg_type = msg.get("type", "")

    # Skip non-message types
    if msg_type in ("progress", "system", "file-history-snapshot"):
        return Activity.THINKING  # Neutral default

    # Check for tool use
    tool_name = get_tool_name(msg)
    if tool_name:
        return TOOL_ACTIVITIES.get(tool_name, Activity.EXECUTING)

    # Check for tool result (reviewing output)
    if is_tool_result(msg):
        return Activity.REVIEWING

    # Default: thinking (processing text)
    return Activity.THINKING
```

**Step 5: Run test to verify it passes**

```bash
cd "/Users/shepardxia/Library/Application Support/Übersicht/widgets/claude-status.widget"
python -m pytest tests/test_classifier.py -v
```

Expected: All 6 tests PASS

**Step 6: Commit**

```bash
git add status_lib/ tests/test_classifier.py
git commit -m "feat: add message classifier with tool-based activity detection"
```

---

## Task 3: Create Weighted Voter Module

**Files:**
- Create: `status_lib/voter.py`
- Create: `tests/test_voter.py`

**Step 1: Write the failing test**

Create `tests/test_voter.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from status_lib.classifier import Activity
from status_lib.voter import weighted_vote

def test_single_reading_message_returns_reading():
    activities = [Activity.READING]
    assert weighted_vote(activities) == Activity.READING

def test_recent_activity_wins_over_older():
    # Older thinking, recent reading -> reading wins
    activities = [Activity.THINKING, Activity.THINKING, Activity.READING]
    assert weighted_vote(activities) == Activity.READING

def test_multiple_same_activity_reinforces():
    # Multiple readings beat single recent writing
    activities = [Activity.READING, Activity.READING, Activity.READING, Activity.WRITING]
    assert weighted_vote(activities) == Activity.READING

def test_empty_returns_thinking():
    assert weighted_vote([]) == Activity.THINKING

def test_reviewing_after_tool_wins():
    # Tool result after execution -> reviewing
    activities = [Activity.EXECUTING, Activity.REVIEWING]
    assert weighted_vote(activities) == Activity.REVIEWING
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_voter.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'status_lib.voter'"

**Step 3: Write voter implementation**

Create `status_lib/voter.py`:

```python
"""Weighted voting for status inference."""

from collections import defaultdict
from status_lib.classifier import Activity

# Recency weights: most recent gets highest weight
WEIGHTS = [1.0, 0.7, 0.5, 0.3, 0.2, 0.15, 0.1, 0.1, 0.1, 0.1]

def weighted_vote(activities: list[Activity]) -> Activity:
    """
    Determine overall activity from list of classified messages.

    Most recent message is last in list.
    Returns the activity with highest weighted vote.
    """
    if not activities:
        return Activity.THINKING

    votes: dict[Activity, float] = defaultdict(float)

    # Process from most recent to oldest
    reversed_activities = list(reversed(activities))

    for i, activity in enumerate(reversed_activities):
        weight = WEIGHTS[min(i, len(WEIGHTS) - 1)]
        votes[activity] += weight

    # Return activity with highest vote
    return max(votes.keys(), key=lambda a: votes[a])
```

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_voter.py -v
```

Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add status_lib/voter.py tests/test_voter.py
git commit -m "feat: add weighted voter for activity inference"
```

---

## Task 4: Create State Smoother Module

**Files:**
- Create: `status_lib/smoother.py`
- Create: `tests/test_smoother.py`

**Step 1: Write the failing test**

Create `tests/test_smoother.py`:

```python
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from status_lib.classifier import Activity
from status_lib.smoother import StateSmoother

def test_first_state_is_accepted():
    smoother = StateSmoother()
    result = smoother.smooth(Activity.READING)
    assert result == Activity.READING

def test_same_state_is_maintained():
    smoother = StateSmoother()
    smoother.smooth(Activity.READING)
    result = smoother.smooth(Activity.READING)
    assert result == Activity.READING

def test_state_change_within_dwell_time_is_blocked():
    smoother = StateSmoother()
    smoother.smooth(Activity.EXECUTING)
    # Immediately try to change - should be blocked
    result = smoother.smooth(Activity.THINKING)
    assert result == Activity.EXECUTING  # Still executing due to dwell time

def test_state_change_after_dwell_time_is_allowed():
    smoother = StateSmoother(dwell_times={Activity.READING: 0.1})
    smoother.smooth(Activity.READING)
    time.sleep(0.15)  # Wait past dwell time
    result = smoother.smooth(Activity.WRITING)
    assert result == Activity.WRITING

def test_reset_clears_state():
    smoother = StateSmoother()
    smoother.smooth(Activity.READING)
    smoother.reset()
    result = smoother.smooth(Activity.WRITING)
    assert result == Activity.WRITING
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_smoother.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'status_lib.smoother'"

**Step 3: Write smoother implementation**

Create `status_lib/smoother.py`:

```python
"""State smoother to prevent rapid status changes."""

import time
from status_lib.classifier import Activity

# Default minimum dwell times in seconds
DEFAULT_DWELL_TIMES = {
    Activity.IDLE: 0,       # Can always transition from idle
    Activity.AWAITING: 0,   # Can always transition from awaiting
    Activity.THINKING: 2,
    Activity.READING: 3,
    Activity.WRITING: 3,
    Activity.EXECUTING: 5,
    Activity.REVIEWING: 2,
}

class StateSmoother:
    """Prevents rapid state changes by enforcing minimum dwell times."""

    def __init__(self, dwell_times: dict[Activity, float] | None = None):
        self.dwell_times = dwell_times or DEFAULT_DWELL_TIMES
        self.current_state: Activity | None = None
        self.state_since: float = 0

    def smooth(self, new_state: Activity) -> Activity:
        """
        Apply smoothing to state transition.

        Returns the actual state to display (may differ from new_state
        if dwell time hasn't elapsed).
        """
        now = time.time()

        # First state or same state - always accept
        if self.current_state is None or new_state == self.current_state:
            self.current_state = new_state
            self.state_since = now
            return new_state

        # Check dwell time
        dwell = self.dwell_times.get(self.current_state, 0)
        elapsed = now - self.state_since

        if elapsed >= dwell:
            # Dwell time passed - allow transition
            self.current_state = new_state
            self.state_since = now
            return new_state

        # Still within dwell time - maintain current state
        return self.current_state

    def reset(self):
        """Reset smoother state."""
        self.current_state = None
        self.state_since = 0
```

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_smoother.py -v
```

Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add status_lib/smoother.py tests/test_smoother.py
git commit -m "feat: add state smoother with dwell time enforcement"
```

---

## Task 5: Create Main Status Script

**Files:**
- Create: `status.py`
- Create: `tests/test_status.py`

**Step 1: Write integration test**

Create `tests/test_status.py`:

```python
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from status_lib.classifier import Activity
from status import parse_messages, infer_status

def test_parse_messages_extracts_relevant_fields():
    lines = [
        '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read"}]}}',
        '{"type":"progress","data":{"type":"hook_progress"}}',
    ]
    messages = parse_messages(lines)
    assert len(messages) == 2
    assert messages[0]["type"] == "assistant"

def test_infer_status_from_reading_sequence():
    fixtures_dir = Path(__file__).parent / "fixtures"
    lines = (fixtures_dir / "reading_sequence.jsonl").read_text().strip().split("\n")
    messages = parse_messages(lines)
    status = infer_status(messages)
    assert status["status"] == "reading"

def test_infer_status_from_writing_sequence():
    fixtures_dir = Path(__file__).parent / "fixtures"
    lines = (fixtures_dir / "writing_sequence.jsonl").read_text().strip().split("\n")
    messages = parse_messages(lines)
    status = infer_status(messages)
    assert status["status"] == "writing"

def test_output_format_is_valid_json():
    fixtures_dir = Path(__file__).parent / "fixtures"
    lines = (fixtures_dir / "mixed_sequence.jsonl").read_text().strip().split("\n")
    messages = parse_messages(lines)
    status = infer_status(messages)
    # Should have required fields
    assert "status" in status
    assert "color" in status
    assert "text" in status
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_status.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'status'"

**Step 3: Write main status script**

Create `status.py`:

```python
#!/usr/bin/env python3
"""
Smart status detection for Claude Code sessions.

Reads JSONL session files, analyzes recent message history,
and outputs coherent status JSON.
"""

import json
import os
import time
from pathlib import Path

from status_lib.classifier import Activity, classify_message
from status_lib.voter import weighted_vote
from status_lib.smoother import StateSmoother

# Status display configuration
STATUS_CONFIG = {
    Activity.IDLE: {"color": "gray", "text": "Idle"},
    Activity.AWAITING: {"color": "blue", "text": "Awaiting input..."},
    Activity.THINKING: {"color": "yellow", "text": "Thinking..."},
    Activity.READING: {"color": "blue", "text": "Reading..."},
    Activity.WRITING: {"color": "green", "text": "Writing..."},
    Activity.EXECUTING: {"color": "green", "text": "Executing..."},
    Activity.REVIEWING: {"color": "yellow", "text": "Reviewing..."},
}

# Cache configuration
CACHE_FILE = Path("/tmp/claude-status-cache.json")
STATUS_OUTPUT = Path("/tmp/claude-status.json")
IDLE_TIMEOUT = 300  # 5 minutes
AWAITING_THRESHOLD = 30  # 30 seconds

# Global smoother instance
_smoother = StateSmoother()


def find_latest_session() -> Path | None:
    """Find the most recently modified Claude session file."""
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        return None

    sessions = list(claude_dir.glob("*/*.jsonl"))
    if not sessions:
        return None

    return max(sessions, key=lambda p: p.stat().st_mtime)


def read_last_n_lines(filepath: Path, n: int = 15) -> list[str]:
    """Read last n lines from file efficiently."""
    try:
        with open(filepath, "rb") as f:
            # Seek to end and work backwards
            f.seek(0, 2)
            size = f.tell()

            # Read chunks from end until we have enough lines
            chunk_size = 8192
            lines = []
            position = size

            while position > 0 and len(lines) < n + 1:
                read_size = min(chunk_size, position)
                position -= read_size
                f.seek(position)
                chunk = f.read(read_size).decode("utf-8", errors="ignore")
                lines = chunk.split("\n") + lines

            # Return last n non-empty lines
            return [l for l in lines if l.strip()][-n:]
    except (OSError, IOError):
        return []


def parse_messages(lines: list[str]) -> list[dict]:
    """Parse JSONL lines into message dictionaries."""
    messages = []
    for line in lines:
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return messages


def load_cache() -> dict:
    """Load status cache from disk."""
    try:
        return json.loads(CACHE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(cache: dict):
    """Save status cache to disk."""
    try:
        CACHE_FILE.write_text(json.dumps(cache))
    except OSError:
        pass


def infer_status(messages: list[dict]) -> dict:
    """Infer current status from message history."""
    if not messages:
        return {"status": "idle", "color": "gray", "text": "No activity"}

    # Classify each message
    activities = [classify_message(msg) for msg in messages]

    # Get weighted vote
    raw_activity = weighted_vote(activities)

    # Apply smoothing
    smoothed = _smoother.smooth(raw_activity)

    # Build output
    config = STATUS_CONFIG[smoothed]
    return {
        "status": smoothed.value,
        "color": config["color"],
        "text": config["text"],
        "tool": "",  # Could extract from last tool_use if needed
        "context_percent": 0,  # Could parse from session if needed
    }


def get_status() -> dict:
    """Main entry point: get current Claude status."""
    session = find_latest_session()

    if not session:
        return {"status": "offline", "color": "gray", "text": "No session"}

    # Check file modification time
    try:
        stat = session.stat()
        mtime = stat.st_mtime
        size = stat.st_size
    except OSError:
        return {"status": "offline", "color": "gray", "text": "No session"}

    now = time.time()
    seconds_ago = now - mtime

    # Load cache
    cache = load_cache()

    # Check if file unchanged
    if (cache.get("session") == str(session) and
        cache.get("mtime") == mtime and
        cache.get("size") == size):

        # File unchanged - check timeouts
        if seconds_ago > IDLE_TIMEOUT:
            return {"status": "idle", "color": "gray", "text": "Idle"}
        elif seconds_ago > AWAITING_THRESHOLD:
            return {"status": "awaiting", "color": "blue", "text": "Awaiting input..."}
        else:
            # Return cached status
            return cache.get("status", {"status": "thinking", "color": "yellow", "text": "..."})

    # File changed - do full analysis
    lines = read_last_n_lines(session, 15)
    messages = parse_messages(lines)
    status = infer_status(messages)

    # Update cache
    save_cache({
        "session": str(session),
        "mtime": mtime,
        "size": size,
        "status": status,
    })

    return status


def main():
    """Output status as JSON."""
    status = get_status()

    # Write to status file for Swift overlay
    try:
        STATUS_OUTPUT.write_text(json.dumps(status))
    except OSError:
        pass

    # Also print for shell compatibility
    print(json.dumps(status))


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_status.py -v
```

Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add status.py tests/test_status.py
git commit -m "feat: add main status script with caching and timeout handling"
```

---

## Task 6: Update Swift Overlay for New States

**Files:**
- Modify: `ClaudeStatusOverlay.swift:13-46` (AvatarComponents)

**Step 1: Add new status states to avatar components**

In `ClaudeStatusOverlay.swift`, update the AvatarComponents struct to include `reading`, `writing`, `executing`, and `reviewing` states:

```swift
// MARK: - Avatar Components
struct AvatarComponents {
    static func border(for status: String) -> String {
        switch status {
        case "working", "running", "executing": return "═"
        case "thinking", "reviewing": return "~"
        case "awaiting": return "⋯"
        case "reading": return "·"
        case "writing": return "▪"
        case "offline": return "·"
        default: return "─"  // idle, resting
        }
    }

    static let eyes: [String: [String]] = [
        "idle": ["·"], "resting": ["·"], "thinking": ["˘"], "working": ["●"],
        "awaiting": ["?"], "offline": ["·"], "reading": ["◦"], "writing": ["●"],
        "executing": ["●"], "reviewing": ["˘"]
    ]
    static let eyePositions: [String: [(Int, Int, Int)]] = [
        "idle": [(2,3,2)],
        "resting": [(2,3,2)],
        "thinking": [(2,3,2), (3,3,1), (2,3,2), (1,3,3)],
        "working": [(2,3,2)],
        "awaiting": [(2,3,2), (3,3,1), (2,3,2), (1,3,3)],
        "offline": [(2,3,2)],
        "reading": [(2,3,2), (3,3,1), (2,3,2), (1,3,3)],  // scanning left-right
        "writing": [(2,3,2)],
        "executing": [(2,3,2)],
        "reviewing": [(2,3,2), (3,3,1), (2,3,2), (1,3,3)]
    ]
    static let mouths: [String: String] = [
        "idle": "◡", "resting": "◡", "thinking": "~", "working": "◡",
        "awaiting": "·", "offline": "─", "reading": "○", "writing": "◡",
        "executing": "▬", "reviewing": "~"
    ]
    static let substrates: [String: [String]] = [
        "idle": [" ·  ·  · "],
        "resting": [" ·  ·  · ", "·  ·  ·  ", " ·  ·  · ", "  ·  ·  ·"],
        "thinking": [" • ◦ • ◦ ", " ◦ • ◦ • "],
        "working": [" • ● • ● ", " ● • ● • "],
        "awaiting": [" · · · · ", "· · · ·  ", " · · · · ", "  · · · ·"],
        "offline": ["  · · ·  "],
        "reading": [" ▸ · · · ", " · ▸ · · ", " · · ▸ · ", " · · · ▸ "],  // scanning
        "writing": [" ▪ ▪ ▪ ▪ ", " ▫ ▪ ▪ ▪ ", " ▫ ▫ ▪ ▪ ", " ▫ ▫ ▫ ▪ "],  // typing
        "executing": [" ▶ ▶ ▶ ▶ ", " ▷ ▶ ▶ ▶ ", " ▷ ▷ ▶ ▶ ", " ▷ ▷ ▷ ▶ "],  // progress
        "reviewing": [" ◇ ◇ ◇ ◇ ", " ◆ ◇ ◇ ◇ ", " ◆ ◆ ◇ ◇ ", " ◆ ◆ ◆ ◇ "]
    ]
}
```

**Step 2: Update isActive check**

In `ClaudeStatusOverlay.swift:106`, update the isActive computed property:

```swift
var isActive: Bool {
    ["running", "thinking", "awaiting", "resting", "reading", "writing", "executing", "reviewing"].contains(status)
}
```

**Step 3: Rebuild the widget**

```bash
cd "/Users/shepardxia/Library/Application Support/Übersicht/widgets/claude-status.widget"
swiftc -o ClaudeStatusOverlay ClaudeStatusOverlay.swift -framework Cocoa
```

Expected: Compiles without errors

**Step 4: Commit**

```bash
git add ClaudeStatusOverlay.swift
git commit -m "feat: add reading/writing/executing/reviewing avatar states"
```

---

## Task 7: Update Restart Script to Use Python

**Files:**
- Modify: `restart.sh`

**Step 1: Update restart.sh to run status.py**

Replace `restart.sh` content:

```bash
#!/bin/bash
# Restart the Claude Status Overlay widget

WIDGET_DIR="$(cd "$(dirname "$0")" && pwd)"

pkill -f ClaudeStatusOverlay
rm -f /tmp/claude-status-overlay.lock
rm -f /tmp/claude-status-cache.json

cd "$WIDGET_DIR"

# Rebuild Swift overlay
swiftc -o ClaudeStatusOverlay ClaudeStatusOverlay.swift -framework Cocoa

# Start overlay (it watches /tmp/claude-status.json)
./ClaudeStatusOverlay &

echo "Widget restarted"
echo "Note: Status updates via 'python status.py' or hook"
```

**Step 2: Test restart**

```bash
cd "/Users/shepardxia/Library/Application Support/Übersicht/widgets/claude-status.widget"
./restart.sh
```

Expected: Widget restarts, no errors

**Step 3: Test Python status script**

```bash
cd "/Users/shepardxia/Library/Application Support/Übersicht/widgets/claude-status.widget"
python status.py
```

Expected: Outputs valid JSON like `{"status": "thinking", "color": "yellow", "text": "Thinking..."}`

**Step 4: Commit**

```bash
git add restart.sh
git commit -m "chore: update restart script for Python status system"
```

---

## Task 8: Create Status Hook for Real-time Updates

**Files:**
- Create: `hooks/status-update.sh`
- Modify: `~/.claude/hooks/status-hook.sh` (if exists)

**Step 1: Create hook script**

Create `hooks/status-update.sh`:

```bash
#!/bin/bash
# Hook to update status widget on Claude activity
# Called by Claude Code hooks on tool use events

WIDGET_DIR="/Users/shepardxia/Library/Application Support/Übersicht/widgets/claude-status.widget"

cd "$WIDGET_DIR"
python3 status.py > /dev/null 2>&1
```

**Step 2: Make executable**

```bash
mkdir -p "/Users/shepardxia/Library/Application Support/Übersicht/widgets/claude-status.widget/hooks"
chmod +x "/Users/shepardxia/Library/Application Support/Übersicht/widgets/claude-status.widget/hooks/status-update.sh"
```

**Step 3: Commit**

```bash
git add hooks/
git commit -m "feat: add status update hook for real-time widget refresh"
```

---

## Task 9: Run Full Test Suite and Verify

**Step 1: Run all tests**

```bash
cd "/Users/shepardxia/Library/Application Support/Übersicht/widgets/claude-status.widget"
python -m pytest tests/ -v
```

Expected: All tests pass (approximately 20 tests)

**Step 2: Manual integration test**

```bash
# Terminal 1: Watch status output
watch -n 1 'python status.py'

# Terminal 2: Observe widget behavior while using Claude
```

**Step 3: Final commit**

```bash
git add -A
git commit -m "docs: complete smart status system implementation"
```

---

## Summary

| Task | Files | Tests |
|------|-------|-------|
| 1. Fixtures | 3 fixture files | - |
| 2. Classifier | classifier.py | 6 tests |
| 3. Voter | voter.py | 5 tests |
| 4. Smoother | smoother.py | 5 tests |
| 5. Main Script | status.py | 4 tests |
| 6. Swift UI | ClaudeStatusOverlay.swift | - |
| 7. Restart | restart.sh | - |
| 8. Hook | hooks/status-update.sh | - |
| 9. Verify | - | Full suite |

**Total: 9 tasks, ~20 tests, 8 commits**
